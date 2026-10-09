"""Bounded, reproducible CPU benchmark; no external API, GPU, or production traffic.
Every configuration runs N cold, N warm, and N one-segment-edit jobs through the real queue.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import statistics
import time
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import psutil

from study_p2v.config import Settings
from study_p2v.engine import Engine
from study_p2v.media import sha256
from study_p2v.models import Storyboard
from study_p2v.process import sample_tree


def candidate(root):
    h = hashlib.sha256()
    for path in sorted((root / "src/study_p2v").glob("*.py")) + [
        root / "uv.lock",
        root / "scripts/benchmark.py",
    ]:
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def audio_bytes():
    t = np.arange(96000) / 48000
    data = (np.sin(t * 2 * np.pi * 440) * 6000).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(data.tobytes())
    return output.getvalue()


def spec(index, partial=False):
    def narration(prefix):
        return {
            "mode": "timed",
            "audio_asset_id": "benchmark-audio",
            "cues": [
                {"start": 0, "end": 0.5, "target": prefix + "1", "text": "Define the inputs first"},
                {
                    "start": 0.6,
                    "end": 1.1,
                    "target": prefix + "2",
                    "text": "Observe the key changes",
                },
                {
                    "start": 1.2,
                    "end": 1.8,
                    "target": prefix + "3",
                    "text": "Finally verify the output",
                },
            ],
        }

    return Storyboard.model_validate(
        {
            "schema_version": 2,
            "subtitle_mode": "burn",
            "output": {"width": 1280, "height": 720, "fps": 24},
            "segments": [
                {
                    "template": "bullets",
                    "title": f"Measured job {index:02d}",
                    "duration": 2,
                    "items": ["Define inputs", "Observe changes", "Verify results"],
                    "narration": narration("item-"),
                },
                {
                    "template": "bars",
                    "title": f"Work comparison {index:02d}" + (" updated" if partial else ""),
                    "duration": 2,
                    "points": [
                        {"label": "First render", "value": 100},
                        {"label": "Partial edit", "value": 40},
                        {"label": "Full reuse", "value": 10},
                    ],
                    "narration": narration("bar-"),
                },
            ],
        }
    )


def percentile(values, p):
    return round(float(np.percentile(values, p)), 4)


def case(engine, count, mode, expected_candidate, root, cpus):
    before = candidate(root)
    if before != expected_candidate:
        raise RuntimeError("candidate_changed")
    pending, rows, observed = {}, [], {}
    peak_rss, peak_cpu, peak_threads, previous_cpu = 0, 0.0, 0, 0.0
    begin, previous_time = time.monotonic(), time.monotonic()
    for i in range(count):
        job, _ = engine.store.submit("benchmark", spec(i, mode == "partial"), None, count + 1)
        pending[job["id"]] = i
    engine.wakeup.set()
    deadline, next_update = begin + 1800, begin
    while pending:
        now = time.monotonic()
        if now > deadline:
            raise RuntimeError("benchmark_deadline")
        rss, _ = sample_tree(os.getpid(), observed)
        total_cpu = sum(observed.values())
        # First sample includes the controller's prior lifetime; establish a baseline first.
        if previous_cpu:
            peak_cpu = max(
                peak_cpu, (total_cpu - previous_cpu) / (now - previous_time) / cpus * 100
            )
        previous_cpu, previous_time = total_cpu, now
        peak_rss = max(peak_rss, rss)
        try:
            tree = [psutil.Process(), *psutil.Process().children(recursive=True)]
            threads = sum(p.num_threads() for p in tree if p.is_running())
            peak_threads = max(peak_threads, threads)
        except psutil.Error:
            pass
        for job_id in list(pending):
            row = engine.store.get("benchmark", job_id)
            if row["state"] not in {"succeeded", "failed", "cancelled"}:
                continue
            if row["state"] != "succeeded":
                raise RuntimeError("benchmark_job_failed:" + str(row["error_code"]))
            result, metrics = json.loads(row["result"]), json.loads(row["metrics"])
            engine.storage.verify("benchmark", job_id, result)
            wanted = {"cold": (2, 0, 1), "warm": (0, 0, 0), "partial": (1, 1, 1)}[mode]
            actual = (
                metrics["rendered_segments"],
                metrics["visual_cache_hits"],
                metrics["video_reencodes"],
            )
            if actual != wanted:
                raise RuntimeError("benchmark_cache_or_encode_contract_failed")
            rows.append(
                {
                    "job_id": job_id,
                    "index": pending.pop(job_id),
                    "metrics": metrics,
                    "sha256": result["sha256"],
                    "duration": result["duration"],
                }
            )
        if now >= next_update:
            print(
                json.dumps({"mode": mode, "completed": len(rows), "remaining": len(pending)}),
                flush=True,
            )
            next_update = now + 20
        time.sleep(0.1)
    elapsed = time.monotonic() - begin
    if candidate(root) != before:
        raise RuntimeError("candidate_changed")
    service = [r["metrics"]["total_seconds"] for r in rows]
    queue = [r["metrics"]["queue_seconds"] for r in rows]
    total = [a + b for a, b in zip(service, queue, strict=True)]
    cpu = sum(r["metrics"].get("cpu_seconds_sampled", 0) for r in rows)
    stages = {
        key: round(statistics.mean(r["metrics"][key] for r in rows), 4)
        for key in (
            "layout_seconds",
            "render_seconds",
            "normalize_seconds",
            "audio_seconds",
            "concat_seconds",
            "mux_seconds",
            "subtitle_seconds",
            "publish_seconds",
        )
    }
    return {
        "mode": mode,
        "count": count,
        "elapsed_seconds": round(elapsed, 4),
        "jobs_per_minute": round(count / elapsed * 60, 3),
        "service_p50": percentile(service, 50),
        "service_p95": percentile(service, 95),
        "queue_p95": percentile(queue, 95),
        "end_to_end_p95": percentile(total, 95),
        "cpu_seconds_sampled": round(cpu, 3),
        "sampled_cpu_utilization_percent": round(cpu / elapsed / cpus * 100, 2),
        "sampled_peak_cpu_utilization_percent": round(peak_cpu, 2),
        "process_tree_peak_rss_bytes": peak_rss,
        "process_tree_peak_threads": peak_threads,
        "mean_stage_seconds": stages,
        "jobs": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=20)
    parser.add_argument("--cpus", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path(".artifacts/benchmark-v2"))
    parser.add_argument("--data", type=Path, default=Path(".data/benchmark-v2"))
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2, 4])
    parser.add_argument("--threads", nargs="+", type=int, default=[1, 2])
    args = parser.parse_args()
    if args.jobs < 20:
        parser.error("at least 20 jobs per mode are required")
    available = sorted(os.sched_getaffinity(0))
    if args.cpus < 1 or args.cpus > len(available):
        parser.error("requested CPU affinity is unavailable")
    os.sched_setaffinity(0, available[: args.cpus])
    root, output, data = Path.cwd(), args.output.resolve(), args.data.resolve()
    output.mkdir(parents=True, exist_ok=True)
    identity = candidate(root)
    report = {
        "candidate": identity,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "cpu_affinity": available[: args.cpus],
            "logical_cpus_available": len(available),
            "memory_bytes": psutil.virtual_memory().total,
        },
        "fixture": "2x2s, 1280x720, 24fps, bullets+bars, timed audio, burned subtitles",
        "results": [],
    }
    # Refuse silently warm "cold" measurements on rerun; use a fresh output/data pair.
    if (output / "report.json").exists() or data.exists():
        parser.error("benchmark data or report already exists; select a fresh run directory")
    try:
        for workers in args.workers:
            for threads in args.threads:
                config = f"w{workers}-t{threads}"
                settings = replace(
                    Settings.from_env(),
                    data_dir=data / config,
                    workers=workers,
                    per_namespace=workers,
                    ffmpeg_threads=threads,
                    queue_limit=args.jobs + 1,
                )
                engine = Engine(settings)
                path = engine.storage.asset_path("benchmark", "benchmark-audio")
                path.write_bytes(audio_bytes())
                engine.store.add_asset(
                    "benchmark", "benchmark-audio", sha256(path), path.stat().st_size, 2
                )
                engine.start()
                try:
                    record = {
                        "workers": workers,
                        "ffmpeg_threads": threads,
                        "runtime_fingerprint": engine.renderer.fingerprint,
                        "modes": [],
                    }
                    report["results"].append(record)
                    for mode in ("cold", "warm", "partial"):
                        print(json.dumps({"configuration": config, "starting": mode}), flush=True)
                        record["modes"].append(
                            case(engine, args.jobs, mode, identity, root, args.cpus)
                        )
                        (output / "report.json").write_text(json.dumps(report, indent=2))
                finally:
                    engine.close()
        report["status"] = "passed"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        raise SystemExit(130) from None
    except Exception as exc:
        # Static errors generated by this script only; do not copy arbitrary exceptions into evidence.
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "status": "passed",
                "configurations": len(report["results"]),
                "total_jobs": args.jobs * 3 * len(report["results"]),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
