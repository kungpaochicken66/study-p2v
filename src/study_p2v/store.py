from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import Conflict, QueueFull
from .models import Storyboard, canonical

TERMINAL = {"succeeded", "failed", "cancelled"}


class Store:
    """Short, explicit SQLite transactions; never hold one across a rendering operation."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
                    request TEXT NOT NULL, request_hash TEXT NOT NULL,
                    idempotency_key TEXT, state TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, result TEXT, metrics TEXT,
                    UNIQUE(namespace, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state, created);
                CREATE INDEX IF NOT EXISTS jobs_namespace ON jobs(namespace, state);
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                    duration REAL NOT NULL, created REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def transaction(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def submit(self, namespace: str, spec: Storyboard, key: str | None, limit: int):
        payload = canonical(spec)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.transaction() as c:
            if key:
                old = c.execute(
                    "SELECT * FROM jobs WHERE namespace=? AND idempotency_key=?", (namespace, key)
                ).fetchone()
                if old:
                    if (
                        old["request_hash"] != digest
                        and canonical(Storyboard.model_validate_json(old["request"])) != payload
                    ):
                        raise Conflict("idempotency_conflict")
                    return dict(old), False
            n = c.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0]
            if n >= limit:
                raise QueueFull("queue_full")
            job_id, now = uuid.uuid4().hex, time.time()
            c.execute(
                "INSERT INTO jobs(id,namespace,request,request_hash,idempotency_key,state,created,updated) "
                "VALUES(?,?,?,?,?,'queued',?,?)",
                (job_id, namespace, payload, digest, key, now, now),
            )
            return dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()), True

    def claim(self, per_namespace: int):
        with self.transaction() as c:
            row = c.execute(
                "SELECT q.* FROM jobs q WHERE q.state='queued' AND "
                "(SELECT COUNT(*) FROM jobs r WHERE r.namespace=q.namespace AND r.state='running')<? "
                "ORDER BY q.created,q.id LIMIT 1",
                (per_namespace,),
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), row["id"])
            )
            out = dict(row)
            out["state"] = "running"
            return out

    def get(self, namespace: str, job_id: str):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE namespace=? AND id=?", (namespace, job_id)
            ).fetchone()
            return dict(row) if row else None

    def list_jobs(self, namespace: str, limit: int = 50):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM jobs WHERE namespace=? ORDER BY created DESC LIMIT ?",
                    (namespace, limit),
                )
            ]

    def cancel(self, namespace: str, job_id: str):
        with self.transaction() as c:
            row = c.execute(
                "SELECT state FROM jobs WHERE namespace=? AND id=?", (namespace, job_id)
            ).fetchone()
            if not row:
                return None
            if row["state"] not in TERMINAL:
                c.execute(
                    "UPDATE jobs SET cancel_requested=1, state=CASE WHEN state='queued' THEN 'cancelled' "
                    "ELSE state END, updated=? WHERE namespace=? AND id=?",
                    (time.time(), namespace, job_id),
                )
        return self.get(namespace, job_id)

    def cancelled(self, namespace: str, job_id: str) -> bool:
        row = self.get(namespace, job_id)
        return not row or bool(row["cancel_requested"])

    def progress(self, job_id: str, count: int):
        with self.connect() as c:
            c.execute(
                "UPDATE jobs SET progress=?,updated=? WHERE id=? AND state='running'",
                (count, time.time(), job_id),
            )

    def finish(
        self,
        job_id: str,
        *,
        result: dict | None = None,
        error: str | None = None,
        metrics: dict | None = None,
    ):
        with self.transaction() as c:
            row = c.execute(
                "SELECT state,cancel_requested FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row or row["state"] != "running":
                return False
            if row["cancel_requested"] or error == "cancelled":
                state, result, error = "cancelled", None, "cancelled"
            else:
                state = "failed" if error else "succeeded"
            c.execute(
                "UPDATE jobs SET state=?,result=?,error_code=?,metrics=?,updated=? WHERE id=?",
                (
                    state,
                    json.dumps(result) if result else None,
                    error,
                    json.dumps(metrics or {}),
                    time.time(),
                    job_id,
                ),
            )
            return state == "succeeded"

    def recover(self) -> int:
        # Called only under the exclusive engine lock; never relabel another live worker's jobs.
        with self.connect() as c:
            return c.execute(
                "UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed' END, "
                "error_code=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END, "
                "result=NULL,updated=? WHERE state='running'",
                (time.time(),),
            ).rowcount

    def add_asset(self, namespace: str, asset_id: str, digest: str, size: int, duration: float):
        with self.connect() as c:
            c.execute(
                "INSERT INTO assets VALUES(?,?,?,?,?,?)",
                (asset_id, namespace, digest, size, duration, time.time()),
            )

    def get_asset(self, namespace: str, asset_id: str):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM assets WHERE namespace=? AND id=?", (namespace, asset_id)
            ).fetchone()
            return dict(row) if row else None
