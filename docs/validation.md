# Validation

Validation evidence applies to a particular candidate, environment, input contract, and execution entry point. Use the procedures below to test Study P2V 0.2.0; the presence of a script, workflow, healthy endpoint, or built package does not establish successful media or deployment acceptance.

## Record the candidate

Record the source commit when one exists, or a digest of the runtime sources and relevant dependency/test fixtures. Also record the lockfile identity, installed package version, Python/FFmpeg versions, font, runtime fingerprint, test command, data/output locations, and observed result. For a container, add the image digest and actual target configuration.

Use new ignored data/output directories and synthetic fixtures. Keep safe IDs, state, counters, output hashes, and static error codes. Do not publish token maps, private requests, uploaded audio, or raw environment dumps. Preserve failures as failures; a later passing candidate does not relabel earlier evidence.

## Lint and automated tests

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
P2V_FONT='DejaVu Sans' uv run study-p2v doctor
P2V_REAL_TESTS=1 P2V_FONT='DejaVu Sans' uv run pytest -q
```

Use a different installed family when necessary. Without `P2V_REAL_TESTS=1`, the real-media modules are skipped. An ordinary default pytest run cannot establish rendering acceptance. Pytest uses `.cache/pytest-tmp`; preserve needed outputs before another run and do not run concurrent sessions with the same base directory.

The tests exercise these observable contracts:

- Structured schema versions, bounded text/math/media inputs, valid cue targets and intervals, and persisted idempotency.
- Namespace-scoped acceptance and access, queue capacity and concurrency, single Engine ownership, restart behavior, and cancellation versus success.
- Durable publication, exact destination reads, corrupt cache/output refusal, and static errors that do not echo private input.
- Timeout/cancellation of parent and descendant processes, including descendants that outlive their parent.
- Uploaded audio through Manim, FFmpeg, API artifact download, and independent media/hash checks.
- Full composition reuse, audio-only visual reuse, one-segment edits, concurrent identical cache production, and corruption recovery.
- Sidecar/burn subtitle behavior, single final AAC encoding, decoded audio timing, visual trigger pixels, sample-rate conversion, and retained utterance gaps.
- Dense text and mathematical glyphs failing when readability cannot be retained.

Fake renderers test state transitions and storage contracts. Real-media tests add actual codec/rendering behavior through FastAPI TestClient. They do not test a network proxy, remote HTTP server, container restrictions, or target-host reliability.

The repository [CI workflow](../.github/workflows/ci.yml) runs environment checks, lint/format checks, real-media tests, and package builds on Ubuntu 24.04 with Python 3.12.13 and uv 0.11.6. Its configuration is distinct from an observed successful GitHub run.

## Visual acceptance

```bash
P2V_FONT='DejaVu Sans' uv run python scripts/visual_acceptance.py \
  --output .artifacts/visual-run --data .data/visual-run
```

The script covers twelve templates with ordinary, long-text, maximum-elements, minimum-duration, and maximum-duration variants. It renders 640x360/15 fps clips, verifies publication, exports three sampled frames per successful case, and generates contact sheets. `--case ordinary` selects a smaller first inspection.

Use a fresh output directory: exports with the same names can be overwritten. Inspect the report's failed cases and compare the expected fixture coverage. Review contact sheets and individual frames for missing content, overlap, readable mathematics, arrows, theme contrast, and safe-area use. A successful script exit or screenshot count alone does not complete visual review. Sampled frames also do not prove that every frame is correct or every valid user input fits.

## Render and independently inspect an artifact

```bash
P2V_FONT='DejaVu Sans' P2V_DATA_DIR="$PWD/.data/smoke-run" \
  uv run study-p2v render examples/v2-templates.json \
  --output .artifacts/smoke-run.mp4
ffprobe -v error -count_frames \
  -show_entries 'format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,pix_fmt,nb_frames,nb_read_frames,sample_rate,channels,duration' \
  -of json .artifacts/smoke-run.mp4
ffmpeg -nostdin -v error -xerror -i .artifacts/smoke-run.mp4 -f null -
sha256sum .artifacts/smoke-run.mp4
```

Choose unused output/data paths. Compare downloaded/exported hashes with the receipt. Confirm H.264/yuv420p video and AAC/48 kHz/stereo audio, requested dimensions/fps, and the expected frame total:

```text
expected_frames = sum(round(segment_duration * fps) for each segment)
expected_duration = expected_frames / fps
```

Check the audio stream duration as well as container duration. For subtitle requests, verify the SRT attachment's bytes/hash and cue timestamps independently. A burned subtitle also needs visual inspection. For timing changes, decode audio samples and inspect frames immediately before and at cue triggers; probing alone cannot prove audiovisual alignment.

## Distribution validation

```bash
uv lock --check
uv build
```

Inspect both wheel and source archive. Confirm required modules and the `study-p2v` entry point, consistent version 0.2.0 metadata, licensing material, and build inputs. Credentials, application state, media, caches, and local artifacts must not be included. Install the wheel without an editable checkout in an isolated environment, then run command help and `doctor` with prepared native dependencies. Record the actual artifact digest and result.

A wheel build verifies packaging, not container startup or full deployment. See [development](development.md) and [THIRD_PARTY.md](../THIRD_PARTY.md) for release and dependency details.

## Performance and deployment are separate checks

Use [performance](performance.md) for fixed-candidate cold/warm/partial benchmarking. Inspect report status, output integrity, and work counts before interpreting throughput. Do not reuse measurements from a different candidate or convert short synthetic throughput into long-video capacity.

Run the [deployment checklist](deployment.md) on the actual server to validate its image, font, persistent volume, unprivileged/read-only restrictions, proxy/TLS, resource limits, cancellation/restart, backup restoration, and independent-client operation. Local TestClient results do not cover these boundaries.

Other unestablished boundaries require separate workloads: maximum-resolution and long complex videos, sustained queues, near-full disks, power-loss durability, and target-host resource contention. Features that are not implemented, including distributed workers, automatic retention, external generation providers, object storage, and GPU comparisons, cannot be described as validated.
