from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
from pathlib import Path

from .config import Settings
from .errors import RenderError
from .media import sha256
from .process import run


def runtime_fingerprint(settings: Settings) -> dict:
    root = settings.data_dir
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        versions = {
            p: importlib.metadata.version(p)
            for p in (
                "manim",
                "numpy",
                "Pillow",
                "manimpango",
                "pycairo",
                "av",
                "matplotlib",
                "psutil",
            )
        }
    except importlib.metadata.PackageNotFoundError:
        raise RenderError("render_dependency_missing") from None
    ffmpeg = run([settings.ffmpeg, "-version"], cwd=root, timeout=10, capture=True)
    run([settings.ffprobe, "-version"], cwd=root, timeout=10)
    filters = run([settings.ffmpeg, "-hide_banner", "-filters"], cwd=root, timeout=10, capture=True)
    subtitle_burn = any(
        len(line.split()) > 1 and line.split()[1] == b"ass" for line in filters.splitlines()
    )
    font_match = (
        run(
            ["fc-match", "-f", "%{family}\n%{file}", settings.font],
            cwd=root,
            timeout=10,
            capture=True,
        )
        .decode()
        .splitlines()
    )
    if len(font_match) != 2 or settings.font.casefold() not in font_match[0].casefold():
        raise RenderError("configured_font_unavailable")
    font_file = Path(font_match[1])
    if not font_file.is_file():
        raise RenderError("configured_font_unavailable")
    # Include code and environment, not merely template name, to prevent stale cross-version hits.
    base = Path(__file__).parent
    bundle = hashlib.sha256()
    for name in ("scene.py", "models.py", "math_render.py", "timing.py"):
        bundle.update((base / name).read_bytes())
    visual = {
        "python": platform.python_version(),
        "packages": versions,
        "font": settings.font,
        "font_sha256": sha256(font_file),
        "template_bundle": bundle.hexdigest(),
        "cache_epoch": settings.cache_epoch,
    }
    composition = hashlib.sha256()
    for name in ("media.py", "renderer.py", "timing.py"):
        composition.update((base / name).read_bytes())
    return dict(
        visual,
        visual=visual,
        ffmpeg_sha256=hashlib.sha256(ffmpeg).hexdigest(),
        composition_bundle=composition.hexdigest(),
        capabilities={"subtitle_burn": subtitle_burn, "structured_math": True},
        encoding={"ffmpeg_threads": settings.ffmpeg_threads},
    )


def child_env(settings: Settings) -> dict[str, str]:
    # Never propagate API credentials or unrelated host secrets to a rendering subprocess.
    allowed = {"PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "FONTCONFIG_FILE", "FONTCONFIG_PATH"}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    cache = settings.data_dir / "runtime-cache"
    cache.mkdir(exist_ok=True, mode=0o700)
    env.update(
        {
            "XDG_CACHE_HOME": str(cache),
            "MPLCONFIGDIR": str(cache / "matplotlib"),
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    return env


def check_disk(settings: Settings):
    if shutil.disk_usage(settings.data_dir).free < settings.min_free_bytes:
        raise RenderError("insufficient_disk_space")


def fingerprint_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
