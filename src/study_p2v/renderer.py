from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from dataclasses import replace

from .config import Settings
from .errors import RenderError
from .media import (
    assemble_audio,
    concat_visuals,
    mux,
    prepare_visual,
    sha256,
    validate_video,
    validate_visual,
    write_ass,
)
from .models import Storyboard, canonical
from .process import CancelCheck, measurements, run
from .runtime import check_disk, child_env, fingerprint_digest, runtime_fingerprint
from .storage import DiskStorage
from .store import Store
from .timing import resolve_timing, srt, subtitle_entries


def cache_key(layer: str, data: dict) -> str:
    return hashlib.sha256(canonical({"layer": layer, **data}).encode()).hexdigest()


class Renderer:
    def __init__(self, settings: Settings, storage: DiskStorage, store: Store):
        self.settings, self.storage, self.store = settings, storage, store
        self.fingerprint: dict = {}

    def prepare(self):
        self.fingerprint = runtime_fingerprint(self.settings)
        check_disk(self.settings)

    def asset(self, namespace: str, asset_id: str):
        row = self.store.get_asset(namespace, asset_id)
        if not row:
            raise RenderError("audio_asset_not_found")
        path = self.storage.asset_path(namespace, asset_id)
        if not path.is_file() or sha256(path) != row["sha256"]:
            raise RenderError("audio_asset_corrupt")
        return path, row["sha256"], row["duration"]

    def render(self, job: dict, cancel: CancelCheck) -> tuple[dict, dict]:
        metrics = {
            "cache_hits": 0,
            "visual_cache_hits": 0,
            "composition_cache_hits": 0,
            "rendered_segments": 0,
            "layout_seconds": 0.0,
            "render_seconds": 0.0,
            "normalize_seconds": 0.0,
            "audio_seconds": 0.0,
            "concat_seconds": 0.0,
            "mux_seconds": 0.0,
            "subtitle_seconds": 0.0,
            "publish_seconds": 0.0,
            "video_reencodes": 0,
            "audio_encodes": 0,
            "audio_decodes": 0,
        }
        with measurements(metrics):
            return self._render(job, cancel, metrics)

    def _render(self, job, cancel, metrics):
        settings = self.settings
        spec = Storyboard.model_validate_json(job["request"])
        namespace, job_id = job["namespace"], job["id"]
        scratch = self.storage.namespace_dir(namespace) / "scratch" / job_id
        scratch.mkdir(parents=True, exist_ok=False, mode=0o700)
        start = time.monotonic()
        deadline = start + settings.job_timeout

        def budget(maximum=None):
            if cancel():
                raise RenderError("cancelled")
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise RenderError("deadline_exceeded")
            return min(maximum or settings.stage_timeout, remain)

        try:
            check_disk(settings)
            timings = []
            for segment in spec.segments:
                budget()
                timings.append(
                    resolve_timing(
                        segment, spec.output.fps, lambda asset_id: self.asset(namespace, asset_id)
                    )
                )
            entries = subtitle_entries(timings)
            if (
                spec.subtitle_mode == "burn"
                and entries
                and not self.fingerprint["capabilities"]["subtitle_burn"]
            ):
                raise RenderError("subtitle_renderer_unavailable")
            attachments = {}
            if spec.subtitle_mode != "none":
                captions = scratch / "subtitles.srt"
                captions.write_text(srt(entries))
                attachments["subtitles"] = captions
            visuals = []
            for segment, timing in zip(spec.segments, timings, strict=True):
                data = segment.model_dump(mode="json", exclude={"audio_asset_id", "narration"})
                data["duration"] = timing.duration
                request = {
                    "segment": data,
                    "frames": timing.frames,
                    "events": timing.visual_events(spec.output.fps),
                    "output": spec.output.model_dump(),
                    "theme": spec.theme,
                    "font": settings.font,
                }
                key = cache_key(
                    "visual", {"request": request, "runtime": self.fingerprint["visual"]}
                )
                visuals.append((key, request))
            total_duration = sum(t.duration for t in timings)
            offset, audio_parts = 0.0, []
            for timing in timings:
                audio_parts.extend(replace(p, start=offset + p.start) for p in timing.audio)
                offset += timing.duration
            composition_key = cache_key(
                "composition",
                {
                    "visuals": [key for key, _ in visuals],
                    "audio": [
                        {"sha256": p.sha256, "start": p.start, "duration": p.duration}
                        for p in audio_parts
                    ],
                    "burn": entries if spec.subtitle_mode == "burn" else None,
                    "runtime": self.fingerprint,
                },
            )
            final = scratch / "final.mp4"
            with self.storage.cache_lock(namespace, composition_key, cancel, budget()) as folder:
                cached = self.storage.cache_get(folder, composition_key)
                if cached:
                    try:
                        metadata = validate_video(
                            cached, settings, spec.output, total_duration, cancel, budget(15)
                        )
                    except RenderError as exc:
                        if exc.code in {"cancelled", "deadline_exceeded"}:
                            raise
                        cached = None
                if cached:
                    shutil.copyfile(cached, final)
                    metrics["cache_hits"] = len(spec.segments)
                    metrics["composition_cache_hits"] = 1
                else:
                    outputs, metas = [], []
                    for index, ((key, request), timing) in enumerate(
                        zip(visuals, timings, strict=True)
                    ):
                        budget()
                        local = scratch / f"segment-{index:03}.mp4"
                        with self.storage.cache_lock(
                            namespace, key, cancel, budget()
                        ) as visual_folder:
                            cached_visual = self.storage.cache_get(visual_folder, key)
                            if cached_visual:
                                try:
                                    meta = validate_visual(
                                        cached_visual,
                                        settings,
                                        spec.output,
                                        timing.frames,
                                        cancel,
                                        budget(15),
                                    )
                                except RenderError as exc:
                                    if exc.code in {"cancelled", "deadline_exceeded"}:
                                        raise
                                    cached_visual = None
                            if cached_visual:
                                shutil.copyfile(cached_visual, local)
                                metrics["cache_hits"] += 1
                                metrics["visual_cache_hits"] += 1
                            else:
                                work = scratch / f"work-{index:03}"
                                work.mkdir(mode=0o700)
                                request_file = work / "request.json"
                                request_file.write_text(json.dumps(request, ensure_ascii=False))
                                raw = work / "raw.mp4"
                                begin = time.monotonic()
                                try:
                                    run(
                                        [
                                            sys.executable,
                                            "-m",
                                            "study_p2v.scene",
                                            "--spec",
                                            str(request_file),
                                            "--output",
                                            str(raw),
                                        ],
                                        cwd=work,
                                        timeout=budget(),
                                        cancel=cancel,
                                        env=child_env(settings),
                                        error_code="manim_render_failed",
                                    )
                                except RenderError as exc:
                                    if exc.code == "manim_render_failed":
                                        report_path = work / "scene-report.json"
                                        if report_path.is_file():
                                            report = json.loads(report_path.read_text())
                                            code = report.get("error_code")
                                            if code in {
                                                "text_overflow",
                                                "layout_out_of_bounds",
                                                "math_layout_failed",
                                                "math_overflow",
                                            }:
                                                raise RenderError(code) from None
                                    raise
                                metrics["render_seconds"] += time.monotonic() - begin
                                report = json.loads((work / "scene-report.json").read_text())
                                metrics["layout_seconds"] += report["layout_seconds"]
                                begin = time.monotonic()
                                meta, encodes = prepare_visual(
                                    raw,
                                    local,
                                    timing.frames,
                                    spec.output,
                                    settings,
                                    cancel,
                                    budget(),
                                )
                                metrics["normalize_seconds"] += time.monotonic() - begin
                                metrics["video_reencodes"] += encodes
                                self.storage.cache_put(
                                    visual_folder,
                                    local,
                                    key,
                                    dict(meta, diagnostics=report, layer="visual"),
                                )
                                metrics["rendered_segments"] += 1
                            outputs.append(local)
                            metas.append(meta)
                        self.store.progress(job_id, index + 1)
                    begin = time.monotonic()
                    joined = scratch / "joined.mp4"
                    concat_visuals(outputs, metas, joined, settings, cancel, budget())
                    metrics["concat_seconds"] = time.monotonic() - begin
                    # Verify the concatenated video frame count before muxing one continuous audio track.
                    validate_visual(
                        joined,
                        settings,
                        spec.output,
                        sum(t.frames for t in timings),
                        cancel,
                        budget(15),
                    )
                    begin = time.monotonic()
                    audio = scratch / "narration.wav"
                    metrics["audio_decodes"] = assemble_audio(
                        audio_parts, total_duration, audio, settings, cancel, budget()
                    )
                    metrics["audio_seconds"] = time.monotonic() - begin
                    burn = spec.subtitle_mode == "burn" and bool(entries)
                    if burn:
                        write_ass(entries, scratch / "captions.ass", spec.output, settings.font)
                    begin = time.monotonic()
                    mux(joined, audio, final, total_duration, settings, cancel, budget(), burn)
                    elapsed = time.monotonic() - begin
                    metrics["mux_seconds"] = elapsed
                    metrics["subtitle_seconds"] = elapsed if burn else 0
                    metrics["video_reencodes"] += int(burn)
                    metrics["audio_encodes"] = 1
                    metadata = validate_video(
                        final, settings, spec.output, total_duration, cancel, budget(15)
                    )
                    self.storage.cache_put(
                        folder, final, composition_key, dict(metadata, layer="composition")
                    )
            self.store.progress(job_id, len(spec.segments))
            metadata["runtime_fingerprint"] = fingerprint_digest(self.fingerprint)
            metadata["timeline"] = [
                {
                    "frames": t.frames,
                    "duration": t.duration,
                    "events": t.visual_events(spec.output.fps),
                }
                for t in timings
            ]
            budget()
            begin = time.monotonic()
            receipt = self.storage.publish(
                namespace, job_id, final, metadata, attachments=attachments
            )
            metrics["publish_seconds"] = time.monotonic() - begin
            budget()
            metrics["total_seconds"] = time.monotonic() - start
            return receipt, {
                k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()
            }
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
