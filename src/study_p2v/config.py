from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import RenderError

NAMESPACE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(".data")
    font: str = "DejaVu Sans"
    workers: int = 2
    per_namespace: int = 1
    queue_limit: int = 100
    stage_timeout: float = 180
    job_timeout: float = 1800
    ffmpeg_threads: int = 2
    max_asset_bytes: int = 25 * 1024 * 1024
    max_request_bytes: int = 256 * 1024
    max_output_bytes: int = 1024 * 1024 * 1024
    min_free_bytes: int = 512 * 1024 * 1024
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    cache_epoch: str = "1"
    api_keys: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "data_dir", self.data_dir.expanduser().resolve())
        if not 1 <= self.workers <= 8 or not 1 <= self.per_namespace <= self.workers:
            raise RenderError("invalid_worker_configuration")
        if (
            self.queue_limit < 1
            or not math.isfinite(self.stage_timeout)
            or not math.isfinite(self.job_timeout)
            or self.stage_timeout <= 0
            or self.job_timeout <= 0
        ):
            raise RenderError("invalid_limits")
        if not 1 <= self.ffmpeg_threads <= 16:
            raise RenderError("invalid_ffmpeg_threads")
        for key, namespace in self.api_keys.items():
            if (
                not isinstance(key, str)
                or len(key) < 24
                or "replace-with" in key
                or not isinstance(namespace, str)
            ):
                raise RenderError("invalid_api_key_configuration")
            if not NAMESPACE.fullmatch(namespace):
                raise RenderError("invalid_namespace")

    @classmethod
    def from_env(cls) -> Settings:
        try:
            keys = json.loads(os.environ.get("P2V_API_KEYS", "{}"))
            if not isinstance(keys, dict):
                raise ValueError
            return cls(
                data_dir=Path(os.environ.get("P2V_DATA_DIR", ".data")),
                font=os.environ.get("P2V_FONT", "DejaVu Sans"),
                workers=int(os.environ.get("P2V_WORKERS", "2")),
                per_namespace=int(os.environ.get("P2V_PER_NAMESPACE", "1")),
                queue_limit=int(os.environ.get("P2V_QUEUE_LIMIT", "100")),
                stage_timeout=float(os.environ.get("P2V_STAGE_TIMEOUT", "180")),
                job_timeout=float(os.environ.get("P2V_JOB_TIMEOUT", "1800")),
                ffmpeg_threads=int(os.environ.get("P2V_FFMPEG_THREADS", "2")),
                ffmpeg=os.environ.get("P2V_FFMPEG", "ffmpeg"),
                ffprobe=os.environ.get("P2V_FFPROBE", "ffprobe"),
                cache_epoch=os.environ.get("P2V_CACHE_EPOCH", "1"),
                api_keys=keys,
            )
        except (ValueError, TypeError):
            raise RenderError("invalid_environment_configuration") from None
