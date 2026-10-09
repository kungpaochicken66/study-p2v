# Performance measurement

This page explains how to measure Study P2V on a fixed candidate and choose worker/FFmpeg settings. It describes measurement methodology rather than a capacity guarantee. Record new measurements for the application, input mix, and target environment you intend to use.

## Reproducible benchmark

[scripts/benchmark.py](../scripts/benchmark.py) runs real queue and renderer work in three modes:

| Mode | Input/cache condition | Enforced work counts per job |
| --- | --- | --- |
| `cold` | Fresh configuration data directory; distinct titles avoid reuse within the first batch | Two rendered segments, zero visual hits, one post-render video reencode |
| `warm` | Repeat each complete storyboard after its cold render | Zero rendered segments, zero additional visual-cache lookups counted as hits, zero video reencodes |
| `partial` | Change only the second segment's title | One rendered segment, one visual hit, one post-render video reencode |

The fixture has two two-second segments at 1280x720/24 fps: bullets and bars, timed synthetic audio, and burned captions. It measures template rendering and composition; the audio is not human narration or TTS. The additional video reencode in non-hit cases is subtitle burning, beyond Manim's initial visual encoding.

Default configuration choices are workers 1, 2, and 4 crossed with FFmpeg threads 1 and 2. Each mode requires at least twenty jobs. The benchmark sets per-namespace concurrency equal to worker count and queue capacity above the batch size. That differs from the product default of one active job per namespace.

Run from the repository root with an installed font and fresh paths:

```bash
P2V_FONT='DejaVu Sans' uv run python scripts/benchmark.py \
  --cpus 4 --jobs 20 --workers 1 2 4 --threads 1 2 \
  --output .artifacts/benchmark-run --data .data/benchmark-run
```

Adjust `--cpus` to an available logical CPU affinity count. Affinity is inherited by subprocesses; it does not reserve exclusive physical cores. The script refuses an existing data directory or `report.json`. Use new directories rather than deleting evidence to force a rerun.

Do not edit source, `uv.lock`, or the benchmark script while it runs. Do not run concurrent media tests or other benchmark loads. The script hashes all application Python modules, the lockfile, and itself, then checks that candidate identity before and after each mode. The report includes host information, runtime fingerprints, settings, per-job observations, output hashes, and final status.

The benchmark independently verifies every published artifact's manifest, size, and hash and enforces render/cache/video-reencode counts. A failed or interrupted report is incomplete evidence, even when some batches finished. Its integrity checks are not a full decode or manual visual assessment; use [validation](validation.md) for those layers.

## Read the metrics correctly

| Metric | Meaning and limits |
| --- | --- |
| Service latency | Renderer `total_seconds`; excludes queue waiting and the Engine's final state commit |
| Queue latency | Time from accepted creation to worker claim |
| End-to-end estimate | Per-job queue plus renderer time; not a measured remote HTTP round trip |
| Jobs per minute | Completed batch size divided by wall-clock batch duration |
| p50/p95 | NumPy interpolated percentiles of the finite batch; observations rather than established SLOs |
| Sampled CPU utilization | External-process sampled CPU seconds divided by batch elapsed time and selected logical CPUs |
| Process-tree RSS peak | Sampled controller/descendant RSS sum; shared pages can be counted more than once |
| Peak CPU and threads | Periodic process-tree samples; short-lived activity can be missed |

CPU estimates omit some controller and short-lived process costs. RSS sampling is not a guaranteed cgroup peak or billable memory figure. Use host/cgroup monitoring alongside the report when sizing limits.

`layout_seconds` is inside `render_seconds`; `subtitle_seconds` is inside `mux_seconds`. Do not add those subsets a second time. `video_reencodes` counts normalization and subtitle encoding after Manim, not its initial visual encoding. Composition hits avoid rendering and encoding but still validate assets/cache bytes and publish a separate job artifact.

## Configuration choices

The application defaults are two workers, two external FFmpeg threads, and one active job per namespace. The last setting reserves opportunities for other namespaces. A single namespace with a limit of one will not reproduce benchmark concurrency equal to the worker count.

Choose a single worker when contention or memory headroom makes concurrency undesirable. Increase worker count only when representative workloads show useful throughput gains with acceptable latency and disk/memory/PID headroom. Tune one variable at a time and retain failed measurements as failed.

`P2V_FFMPEG_THREADS` controls explicitly configured external FFmpeg encoding threads. It does not limit Manim/PyAV thread creation or total host CPU use. Compose CPU and memory limits supply a separate deployment boundary. Increasing threads cannot remove Python imports, layout work, probes, or filesystem publication overhead.

Compare cold, warm, and partial batches separately, then weight them using the real cache mix. Warm throughput can be sensitive to disk reads, hash verification, queue polling, batch boundaries, and measurement overhead; it need not rise monotonically with workers.

## Limits and reporting

A short fixture does not scale linearly to long videos: process startup is a fixed cost, while layout density, mathematics, actual narration, subtitle content, segment count, and media duration change the workload. Test representative longer requests and sustained queue behavior before declaring production capacity. No GPU or OpenGL comparison is provided.

A shareable report should identify the candidate and dependency lock, fixture/benchmark version, font/runtime fingerprint, target environment, affinity/resource limits, workers/namespace limit/threads, job count, cache mode, output verification, and status. Keep raw private media and credentials out of benchmark evidence. Cost allocation is described in [costs](costs.md).
