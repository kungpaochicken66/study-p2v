# CLI reference

The installed command is `study-p2v`. From a source checkout, use `uv run study-p2v`.
Configuration comes from the same `Settings` as the API. Commands do not load `.env`;
export variables explicitly. See [deployment](deployment.md) for configuration details.

## Commands and options

| Command | Option | Default and behavior |
| --- | --- | --- |
| `doctor` | None | Check installed packages, font, FFmpeg/ffprobe, and subtitle capability |
| `render SPEC` | `--output PATH` | Required; export the verified video without overwriting |
| `render SPEC` | `--namespace NAME` | `local`; must match `[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}` |
| `serve` | `--host HOST` | `127.0.0.1`; HTTP bind address |
| `serve` | `--port PORT` | `8090`; runs one Uvicorn process |

```bash
uv run study-p2v --help
uv run study-p2v render --help
P2V_DATA_DIR="$PWD/.data/cli" uv run study-p2v render \
  examples/v2-templates.json --namespace local --output .artifacts/cli-demo.mp4
```

`doctor` checks the runtime without installing anything. It can create the data directory,
but does not start an engine or render a video. Its JSON output contains `ok`, `font`,
`packages`, and `capabilities`.

`render` reads a local JSON file, validates it, starts an engine, submits a job, and waits
for a terminal state. It forces one worker and one running job per namespace, regardless of
`P2V_WORKERS` or `P2V_PER_NAMESPACE`; use the service for concurrency measurements.

`--namespace` selects a local storage partition. It is an administrator capability, not an
authentication mechanism. The API always derives the namespace from the Bearer token.

## Data ownership and configuration

`P2V_DATA_DIR` defaults to `.data` resolved relative to the current working directory. Use a
fixed absolute directory for a long-running installation. Only one engine may own a data
directory; a running `serve` and a CLI `render` cannot share it concurrently.

Useful environment variables include `P2V_FONT`, `P2V_FFMPEG`, `P2V_FFPROBE`,
`P2V_STAGE_TIMEOUT` (180 seconds), `P2V_JOB_TIMEOUT` (1800 seconds), and
`P2V_FFMPEG_THREADS` (2). The job execution budget begins when rendering starts, so it does
not include queue waiting. `serve` also requires a valid `P2V_API_KEYS` mapping.

## Audio, subtitles, and output

The CLI accepts the same storyboard schema as the API. It has no audio-upload command and
does not accept local audio paths as `audio_asset_id`. Use the API's upload-and-submit flow
for narrated content. To use existing uploaded assets offline, stop the service and render
with the same data directory and namespace that own the asset records. Do not construct
SQLite rows manually.

Use an `.mp4` output suffix. The output is always MP4; the filename suffix does not choose an
encoder. For `subtitle_mode=sidecar` or `burn`, the CLI also exports a same-stem `.srt`.
Existing video or subtitle files cause `output_already_exists`. An output path whose SRT
path would equal the video path causes `subtitle_output_conflicts_with_video`. Without
narration cues, a requested SRT is empty.

The durable artifact remains in the data directory; `--output` creates an exported copy.
Removing that copy does not remove the job or its durable artifact. Export errors may leave
an incomplete local copy, so file existence alone does not establish success. Check the
receipt, exported byte count, and SHA256.

## Output and exit codes

| Result | Output | Exit code |
| --- | --- | --- |
| Successful `doctor` | One JSON diagnostic object on stdout | 0 |
| Successful `render` | One JSON object with `job_id`, `state`, `result`, and `metrics` on stdout | 0 |
| Application error | `{"error":"static_code"}` on stderr | 1 |
| File, JSON, or configuration parsing error | `{"error":"invalid_input_or_configuration"}` on stderr | 1 |
| Invalid command-line syntax | argparse usage or help text | Usually 2 |

Ctrl-C while `render` is waiting requests cancellation and closes the engine; it does not
report success. Cancellation terminates active subprocess groups. `serve` is a foreground
server, so normal startup does not produce a render receipt.

For batch work, check the exit code and `state`, then verify the exported file against
`result.size_bytes` and `result.sha256`. See [operations](operations.md) for failure handling
and [API](api.md) for the distinct HTTP job-state contract.
