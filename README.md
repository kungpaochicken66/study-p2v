# study-p2v

Turn structured storyboards into animated MP4 videos with Manim and FFmpeg.

study-p2v is a self-hosted rendering service for explainers, lessons, and presentations.
You provide bounded JSON and optional audio; the service renders the visuals, aligns the
media, and publishes an artifact with a SHA256 receipt. A CLI and an authenticated HTTP API
use the same rendering engine.

Version **0.2.0** supports 12 templates: title, bullets, compare, bars, flow, timeline,
equation, definition, example, cycle, checklist, and priority. V2 storyboards add structured
mathematics, timed narration or individual audio clips, and sidecar or burned subtitles.
Both V1 and V2 inputs are supported.

## Render your first video

Use Linux or WSL2 with Python 3.12, [uv](https://docs.astral.sh/uv/), FFmpeg/ffprobe,
Fontconfig, and Cairo/Pango. On Ubuntu or Debian, prepare the system dependencies:

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libcairo2-dev libpango1.0-dev \
  ffmpeg fontconfig fonts-dejavu-core
```

From the source checkout:

```bash
uv sync --locked --python 3.12
uv run study-p2v doctor
uv run study-p2v render examples/minimal.json --output .artifacts/first.mp4
```

The default font is `DejaVu Sans`. Select another installed family with `P2V_FONT`;
`doctor` checks that the configured family exists. Text rendering supports Unicode when
suitable glyphs are available in the installed fonts. All distributed examples use English.
Dependencies are installed during setup or image building, never at application startup.

A successful render prints the job ID, artifact receipt, and performance metrics. Compare
the exported file's SHA256 and byte count with the receipt, then play it to review the
layout. The CLI refuses to overwrite existing output files. Without supplied audio, the
video includes a silent AAC track.

For all templates, render `examples/v2-templates.json`. See the
[quickstart](docs/quickstart.md) for installation, verification, and API setup.

## Run the API

Create a token and map it to a namespace before starting the service:

```bash
export P2V_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export P2V_API_KEYS="$(python3 -c 'import json,os; print(json.dumps({os.environ["P2V_TOKEN"]:"demo"}))')"
export P2V_DATA_DIR="$PWD/.data/api"
uv run study-p2v serve --host 127.0.0.1 --port 8090
```

Provide the same token to your client through your own credential management.
`P2V_TOKEN` is a client variable used by the examples; the server reads `P2V_API_KEYS`.
CLI commands do not load `.env`. Docker Compose reads it for variable interpolation;
`.env.example` contains placeholders that must be replaced.

The API derives namespace access from the Bearer token. Job IDs and asset IDs do not grant
access by themselves. A token can access every job and asset in its namespace.

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live`, `GET /health/ready` | Unauthenticated liveness and readiness |
| `GET /v1/templates` | Supported templates, actions, targets, and JSON Schema |
| `POST /v1/assets` | Upload a raw audio body and receive an asset ID |
| `POST /v1/jobs` | Persist a storyboard; optional `Idempotency-Key` |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | List or inspect jobs in the authenticated namespace |
| `POST /v1/jobs/{id}/cancel` | Cancel a queued or running job |
| `POST /v1/jobs/{id}/retry` | Create a new job from a failed or cancelled one |
| `GET /v1/jobs/{id}/artifact` | Download a verified, successful MP4 |
| `GET /v1/jobs/{id}/subtitles` | Download a verified SRT when requested |

A `202` response means the job was persisted, not that rendering finished. Poll until a
terminal state, then verify the downloaded bytes against `result`. The
[API guide](docs/api.md) includes a complete standard-library client. Interactive API
reference pages are available at `/docs`; `/v1/*` calls still require authentication.

## Rendering and persistence

- A shared frame clock drives visual actions, audio placement, and subtitle timing.
- Structured mathematics uses bounded data and MathText; no external TeX installation is required.
- Compatible silent H.264 segments are concatenated by stream copy. A continuous 48 kHz
  stereo audio timeline is encoded to AAC once during final composition.
- Namespace-isolated visual and composition caches use content, asset digests, fonts,
  code, dependencies, and output settings. Cache hits are checked before reuse.
- Changing audio can reuse unchanged visuals. Changing one segment can reuse the others.
  Changing sidecar subtitle text can reuse the MP4 when visuals and audio stay the same.
- SQLite WAL stores jobs and idempotency keys. Queued jobs remain queued after restart;
  interrupted running jobs receive an explicit terminal outcome.
- Success requires durable publication of the MP4, manifest, and optional SRT, followed by
  independent read-back. Downloads recheck the persisted files.
- Cancellation and timeouts terminate subprocess groups. Requests accept structured data,
  not caller-supplied Python, shell commands, paths, or download URLs.

## Scope and limits

This is a single-host service for trusted callers. It uses one engine owner per data
directory, local filesystem storage, and namespace concurrency quotas. Run one Uvicorn
process; extra HTTP processes or a shared SQLite directory do not provide distributed workers.
Native media processing also needs deployment-level resource and network controls.

Storyboards contain 1-24 segments, with requested durations of 1-60 seconds each and at most
600 seconds in total. Output is landscape, approximately 16:9, with even dimensions up to
1920x1080 at 15, 24, or 30 fps. Text and mathematics must fit the template at render time.

The project does not include script generation, TTS, speech recognition, external image or
video import, an editing UI, distributed scheduling, cloud storage, or automatic garbage
collection. Prepare narration outside the service and upload the audio bytes.

## Documentation and checks

Use the [documentation index](docs/README.md) to find
[templates](docs/templates.md), [CLI options](docs/cli.md),
[deployment](docs/deployment.md), [operations](docs/operations.md),
[architecture](docs/architecture.md), and [development](docs/development.md).

```bash
uv run ruff check .
uv run pytest
P2V_REAL_TESTS=1 uv run pytest
uv run python scripts/visual_acceptance.py
```

The real-media and visual checks require the rendering dependencies. See
[validation](docs/validation.md) for acceptance procedures and evidence boundaries,
[performance](docs/performance.md) for measurement methodology, and
[costs](docs/costs.md) for capacity planning.

See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute and [SECURITY.md](SECURITY.md) for
security reporting.

Licensed under [MIT](LICENSE). Dependency and font licenses are described in
[THIRD_PARTY.md](THIRD_PARTY.md).
