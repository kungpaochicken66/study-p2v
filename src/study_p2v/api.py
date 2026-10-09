import hmac
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .engine import Engine
from .errors import RenderError
from .media import probe, sha256
from .models import TEMPLATE_NAMES, Storyboard, asset_ids
from .runtime import check_disk
from .storage import checked, fsync_dir


def public_job(row: dict) -> dict:
    return {
        "id": row["id"],
        "state": row["state"],
        "created": row["created"],
        "updated": row["updated"],
        "completed_segments": row["progress"],
        "cancel_requested": bool(row["cancel_requested"]),
        "error_code": row["error_code"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "metrics": json.loads(row["metrics"]) if row["metrics"] else {},
    }


class BodyLimit:
    """Bound JSON decoding and asset buffering before application processing."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        limit = (
            self.settings.max_asset_bytes
            if scope["path"] == "/v1/assets"
            else self.settings.max_request_bytes
        )
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                return await JSONResponse({"error": "request_too_large"}, 413)(scope, receive, send)
            chunks.append(body)
            if not message.get("more_body"):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.api_keys:
        raise RenderError("api_keys_required")
    engine = engine or Engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(engine.start)
        try:
            yield
        finally:
            await run_in_threadpool(engine.close)

    app = FastAPI(title="study-p2v", version="0.2.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, settings=settings)
    app.state.engine = engine

    @app.exception_handler(RenderError)
    async def render_error(request, exc):
        statuses = {
            "unauthorized": 401,
            "job_not_found": 404,
            "audio_asset_not_found": 404,
            "idempotency_conflict": 409,
            "artifact_not_ready": 409,
            "job_not_retryable": 409,
            "queue_full": 429,
            "insufficient_disk_space": 507,
            "request_too_large": 413,
            "artifact_verification_failed": 409,
        }
        return JSONResponse({"error": exc.code}, status_code=statuses.get(exc.code, 422))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default response contains rejected input values: do not echo user content.
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({"error": "internal_error"}, status_code=500)

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise RenderError("unauthorized")
        token = authorization[7:]
        if len(token) > 512:
            raise RenderError("unauthorized")
        for configured, namespace in settings.api_keys.items():
            if hmac.compare_digest(token.encode(), configured.encode()):
                return namespace
        raise RenderError("unauthorized")

    Namespace = Annotated[str, Depends(authenticate)]

    def required_job(namespace: str, job_id: str):
        checked(job_id)
        row = engine.store.get(namespace, job_id)
        if not row:
            raise RenderError("job_not_found")
        return row

    @app.get("/health/live")
    def live():
        return {"ok": True}

    @app.get("/health/ready")
    def ready():
        try:
            check_disk(settings)
            ok = engine.ready and all(t.is_alive() for t in engine.threads)
        except RenderError:
            ok = False
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    @app.get("/v1/templates")
    def templates(namespace: Namespace):
        return {
            "schema_version": 2,
            "supported_schema_versions": [1, 2],
            "templates": TEMPLATE_NAMES,
            "actions": ["reveal", "highlight", "exit"],
            "target_conventions": {
                "title": ["title", "subtitle"],
                "bullets/checklist/priority": "item-N (1-based)",
                "bars": "bar-N (1-based)",
                "flow/timeline/cycle/equation": "step-N (1-based)",
                "compare": "left-heading, right-heading, left-N, right-N (1-based)",
                "definition": ["term", "body"],
                "example": "prompt, step-N (1-based)",
            },
            "examples": [
                {
                    "schema_version": 2,
                    "segments": [
                        {
                            "template": "definition",
                            "title": "Definition",
                            "term": "Cache",
                            "body": "Reuse verified results",
                        }
                    ],
                }
            ],
            "storyboard_schema": Storyboard.model_json_schema(),
        }

    @app.post("/v1/jobs")
    def submit(
        spec: Storyboard,
        namespace: Namespace,
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
            raise RenderError("invalid_idempotency_key")
        check_disk(settings)
        for segment in spec.segments:
            for asset_id in asset_ids(segment):
                if not engine.store.get_asset(namespace, asset_id):
                    raise RenderError("audio_asset_not_found")
        row, created = engine.store.submit(namespace, spec, idempotency_key, settings.queue_limit)
        engine.wakeup.set()
        return JSONResponse(public_job(row), status_code=202 if created else 200)

    @app.get("/v1/jobs")
    def jobs(namespace: Namespace):
        return {"jobs": [public_job(r) for r in engine.store.list_jobs(namespace)]}

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str, namespace: Namespace):
        return public_job(required_job(namespace, job_id))

    @app.post("/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str, namespace: Namespace):
        required_job(namespace, job_id)
        row = engine.store.cancel(namespace, job_id)
        engine.wakeup.set()
        return public_job(row)

    @app.post("/v1/jobs/{job_id}/retry")
    def retry(job_id: str, namespace: Namespace):
        old = required_job(namespace, job_id)
        if old["state"] not in {"failed", "cancelled"}:
            raise RenderError("job_not_retryable")
        # A retry creates a new identity, retaining the old outcome for inspection.
        spec = Storyboard.model_validate_json(old["request"])
        row, _ = engine.store.submit(namespace, spec, None, settings.queue_limit)
        engine.wakeup.set()
        return JSONResponse(public_job(row), 202)

    @app.get("/v1/jobs/{job_id}/artifact")
    def artifact(job_id: str, namespace: Namespace):
        row = required_job(namespace, job_id)
        if row["state"] != "succeeded":
            raise RenderError("artifact_not_ready")
        path = engine.storage.verify(namespace, job_id, json.loads(row["result"]))
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=f"{job_id}.mp4",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/v1/jobs/{job_id}/subtitles")
    def subtitles(job_id: str, namespace: Namespace):
        row = required_job(namespace, job_id)
        if row["state"] != "succeeded":
            raise RenderError("artifact_not_ready")
        receipt = json.loads(row["result"])
        video = engine.storage.verify(namespace, job_id, receipt)
        if "subtitles" not in receipt.get("attachments", {}):
            return JSONResponse({"error": "subtitles_not_available"}, status_code=404)
        return FileResponse(
            video.with_name("subtitles.srt"),
            media_type="application/x-subrip",
            filename=f"{job_id}.srt",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/v1/assets")
    async def upload(request: Request, namespace: Namespace):
        # Raw audio body. No filename, external URL, or caller-selected path is used.
        check_disk(settings)
        asset_id = uuid.uuid4().hex
        path = engine.storage.asset_path(namespace, asset_id)
        try:
            size = 0
            with path.open("xb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > settings.max_asset_bytes:
                        raise RenderError("request_too_large")
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            fsync_dir(path.parent)
            info = await run_in_threadpool(probe, path, settings)
            streams = info["streams"]
            if (
                len(streams) != 1
                or streams[0].get("codec_type") != "audio"
                or info["duration"] > 600
            ):
                raise RenderError("audio_only_asset_required")
            digest = await run_in_threadpool(sha256, path)
            await run_in_threadpool(
                engine.store.add_asset, namespace, asset_id, digest, size, info["duration"]
            )
            return JSONResponse(
                {
                    "id": asset_id,
                    "sha256": digest,
                    "size_bytes": size,
                    "duration": info["duration"],
                },
                201,
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    return app
