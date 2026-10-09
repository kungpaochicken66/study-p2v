# Quickstart

This guide uses a source checkout on Linux or WSL2 with Python 3.12. Run commands from the
repository root. POSIX file locks and process groups are part of the implementation; the
commands below are not a native Windows installation procedure.

## 1. Prepare the dependencies

Install FFmpeg, ffprobe, Fontconfig, Cairo/Pango, build tools, and the default font. On Ubuntu
or Debian:

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libcairo2-dev libpango1.0-dev \
  ffmpeg fontconfig fonts-dejavu-core
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) separately, then check
that it is available. From your checkout, for example `study-p2v/`:

```bash
cd study-p2v
uv --version
uv python install 3.12
uv sync --locked --python 3.12
```

If you already have a compatible Python 3.12 with development headers, `uv python install`
is optional. The project requires Python `>=3.12,<3.13`. `--locked` verifies that
`pyproject.toml` and `uv.lock` agree; it does not update the lockfile.

Setup and image building may need network access. Rendering does not call an online model
or media service, and application startup does not install packages. For an offline host,
prepare the complete environment or container image in advance.

## 2. Check the font and media tools

```bash
fc-list : family
uv run study-p2v doctor
```

The configured font defaults to `DejaVu Sans`. To use another family, first confirm it
is installed, then set `P2V_FONT` to its family name and rerun `doctor`. Font selection
changes layout and cache identity. Choose fonts with glyph coverage for your input language.

A successful diagnostic prints `ok`, `font`, `packages`, and `capabilities` as JSON.
`structured_math` reports the mathematics component; `subtitle_burn` reports availability
of FFmpeg's ASS subtitle filter. `doctor` may create the data directory. It does not render
a video, verify API credentials, or certify every template.

## 3. Render and verify a video

Use a dedicated data directory and a new output filename:

```bash
export P2V_DATA_DIR="$PWD/.data/quickstart"
mkdir -p .artifacts
uv run study-p2v render examples/minimal.json --output .artifacts/first.mp4 \
  > .artifacts/first-receipt.json
ffprobe -v error -show_entries \
  format=duration:stream=codec_name,width,height,avg_frame_rate,pix_fmt,sample_rate,channels \
  -of json .artifacts/first.mp4
sha256sum .artifacts/first.mp4
```

The render command waits for completion. Exit code 0 and `state=succeeded` indicate that
publication and read-back checks passed. Independently check the exported bytes against its
receipt:

```bash
python3 - <<'PYVERIFY'
import hashlib
import json
from pathlib import Path

video = Path(".artifacts/first.mp4")
receipt = json.loads(Path(".artifacts/first-receipt.json").read_text())["result"]
assert video.stat().st_size == receipt["size_bytes"], "size mismatch"
with video.open("rb") as source:
    digest = hashlib.file_digest(source, "sha256").hexdigest()
assert digest == receipt["sha256"], "hash mismatch"
print("Verified exported MP4")
PYVERIFY
```

Expected media is H.264/yuv420p video with AAC audio at 48 kHz, two channels. No supplied
audio means a silent track. Play the result and review text, glyphs, alignment, and pacing.

Render more examples with new output filenames:

```bash
uv run study-p2v render examples/minimal.json --output .artifacts/first-again.mp4
uv run study-p2v render examples/v2-templates.json --output .artifacts/twelve-templates.mp4
```

Identical content can reuse verified caches within the same data directory and namespace.
Each CLI invocation still creates a new job; cache reuse is separate from API idempotency.
The CLI never overwrites an existing MP4 or requested SRT. Do not run `render` while a
service owns the same data directory.

## 4. Start the API

The local CLI does not require an API token. The HTTP service does. Generate a token and
server mapping without printing the secret:

```bash
export P2V_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export P2V_API_KEYS="$(python3 -c 'import json,os; print(json.dumps({os.environ["P2V_TOKEN"]:"demo"}))')"
export P2V_DATA_DIR="$PWD/.data/api"
uv run study-p2v serve --host 127.0.0.1 --port 8090
```

The service runs in the foreground. In another terminal, provide the same `P2V_TOKEN` using
your credential-management method, then check readiness:

```bash
curl --fail http://127.0.0.1:8090/health/ready
```

`P2V_TOKEN` is only an example client variable; the server reads `P2V_API_KEYS`. There is no
default token, login UI, or automatic `.env` loading in the CLI. Preserve the intended token
mapping when restarting the service.

Follow the [complete API client](api.md#complete-client-example) to submit, poll, download,
and verify a video. Start with the silent example, then add audio upload and V2 narration.
Use [deployment](deployment.md) and [operations](operations.md) for persistent volumes,
restart policy, TLS, resource limits, and backup. Verify the target installation through its
actual API entry point before treating it as accepted.
