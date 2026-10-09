from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .errors import RenderError
from .media import sha256
from .process import CancelCheck

SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def checked(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise RenderError("invalid_identifier")
    return value


def durable_json(path: Path, data: dict):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DiskStorage:
    """One explicit storage target. No preview URL or unrelated backend can satisfy publication."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def namespace_dir(self, namespace: str) -> Path:
        path = self.root / "namespaces" / checked(namespace)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def artifact_dir(self, namespace: str, job_id: str) -> Path:
        return self.namespace_dir(namespace) / "artifacts" / checked(job_id)

    def asset_path(self, namespace: str, asset_id: str) -> Path:
        folder = self.namespace_dir(namespace) / "assets"
        folder.mkdir(exist_ok=True, mode=0o700)
        return folder / checked(asset_id)

    def publish(
        self,
        namespace: str,
        job_id: str,
        source: Path,
        metadata: dict,
        *,
        attachments: dict[str, Path] | None = None,
    ) -> dict:
        final = self.artifact_dir(namespace, job_id)
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=final.parent))
        try:
            target = stage / "video.mp4"
            with source.open("rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            if (
                target.stat().st_size != metadata["size_bytes"]
                or sha256(target) != metadata["sha256"]
            ):
                raise RenderError("artifact_verification_failed")
            receipt = dict(metadata, storage="filesystem", namespace=namespace, job_id=job_id)
            if attachments:
                receipt["attachments"] = {}
                for name, source_attachment in attachments.items():
                    if name != "subtitles":
                        raise RenderError("unsupported_attachment")
                    destination = stage / "subtitles.srt"
                    with source_attachment.open("rb") as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                        dst.flush()
                        os.fsync(dst.fileno())
                    receipt["attachments"][name] = {
                        "filename": "subtitles.srt",
                        "size_bytes": destination.stat().st_size,
                        "sha256": sha256(destination),
                    }
            durable_json(stage / "manifest.json", receipt)
            os.replace(stage, final)
            fsync_dir(final.parent)
            self.verify(namespace, job_id, receipt)
            return receipt
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def verify(self, namespace: str, job_id: str, receipt: dict) -> Path:
        final = self.artifact_dir(namespace, job_id)
        try:
            manifest = json.loads((final / "manifest.json").read_text())
            target = final / "video.mp4"
            if (
                manifest != receipt
                or manifest["namespace"] != namespace
                or manifest["job_id"] != job_id
                or manifest["storage"] != "filesystem"
                or target.stat().st_size != manifest["size_bytes"]
                or sha256(target) != manifest["sha256"]
            ):
                raise ValueError
            for name, meta in manifest.get("attachments", {}).items():
                if name != "subtitles" or meta["filename"] != "subtitles.srt":
                    raise ValueError
                attached = final / "subtitles.srt"
                if (
                    attached.stat().st_size != meta["size_bytes"]
                    or sha256(attached) != meta["sha256"]
                ):
                    raise ValueError
            return target
        except (OSError, ValueError, KeyError, TypeError):
            raise RenderError("artifact_verification_failed") from None

    @contextmanager
    def cache_lock(self, namespace: str, key: str, cancel: CancelCheck, timeout: float):
        folder = self.namespace_dir(namespace) / "cache"
        folder.mkdir(exist_ok=True, mode=0o700)
        lock = folder / (checked(key) + ".lock")
        with lock.open("a") as f:
            end = time.monotonic() + timeout
            while True:
                if cancel():
                    raise RenderError("cancelled")
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise RenderError("deadline_exceeded")
                    time.sleep(0.05)
            try:
                yield folder / key
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def cache_get(self, folder: Path, expected_key: str) -> Path | None:
        try:
            meta = json.loads((folder / "manifest.json").read_text())
            video = folder / "video.mp4"
            if (
                meta["key"] == expected_key
                and video.stat().st_size == meta["size_bytes"]
                and sha256(video) == meta["sha256"]
            ):
                return video
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def cache_put(self, folder: Path, source: Path, key: str, metadata: dict):
        # Caller holds the per-key lock. A crash leaves at worst an unused hidden staging directory.
        stage = Path(tempfile.mkdtemp(prefix=".cache-", dir=folder.parent))
        try:
            shutil.copyfile(source, stage / "video.mp4")
            with (stage / "video.mp4").open("rb") as f:
                os.fsync(f.fileno())
            durable_json(stage / "manifest.json", dict(metadata, key=key))
            if folder.exists():
                shutil.rmtree(folder)
            os.replace(stage, folder)
            fsync_dir(folder.parent)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
