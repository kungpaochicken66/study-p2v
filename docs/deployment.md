# Deployment

This guide describes self-hosting Study P2V 0.2.0. Start with the [quickstart](quickstart.md) for a local render and use [operations](operations.md) for backups and recovery. Recipes are not evidence that a particular container, proxy, or server has passed acceptance.

All application state lives under `P2V_DATA_DIR`: SQLite, uploaded audio, caches, scratch, and published artifacts. Install dependencies and fonts before starting the application. Runtime startup does not install packages or download models.

## Docker Compose

Use a Linux Docker Engine with Compose. The supplied resource limits are a starting configuration, not a capacity guarantee: four CPUs, 4 GiB memory, 256 PIDs, two worker threads, one active job per namespace, and two external FFmpeg encoding threads. Leave additional host capacity for the operating system and disk cache.

From the repository root, generate a private token mapping for an initial installation:

```bash
umask 077
python3 - <<'PYCODE'
import json
import secrets
from pathlib import Path

mapping = {secrets.token_urlsafe(32): "demo"}
with Path(".env").open("x", encoding="utf-8") as handle:
    handle.write("P2V_API_KEYS='" + json.dumps(mapping) + "'\n")
PYCODE
docker compose build
docker compose up -d
docker compose exec -T renderer study-p2v doctor
curl --fail http://127.0.0.1:8090/health/ready
```

The exclusive file creation refuses to overwrite an existing `.env`. Existing installations should edit their controlled configuration rather than rerun this bootstrap. Keep tokens out of Git, tickets, shell tracing, and public logs. The placeholder in `.env.example` is deliberately rejected. Configure your client from the private mapping without printing the token.

The Compose service binds only `127.0.0.1:8090`. Its root filesystem is read-only, `/tmp` is a bounded tmpfs, and `/data` is a persistent named volume. The process runs as UID 10001 with capabilities dropped and `no-new-privileges`. A bind-mounted replacement data directory must be writable by that UID; do not use world-writable permissions as a substitute for correct ownership.

The Dockerfile fixes the Python and uv image versions and installs Python dependencies from `uv.lock`. OS packages are installed from apt repositories without a repository snapshot, and base images are referenced by tags. Record the built image digest rather than claiming byte-for-byte reproducible image builds. Images contain the installed runtime, not the repository's examples or manuals; submit examples from a client.

## Reverse proxy and access

For access from another machine, place the loopback service behind a TLS reverse proxy. Preserve `Authorization` and `Idempotency-Key`. Apply request size limits, upload/read timeouts, rate limits, and connection limits appropriate to your callers. An audio request body cannot exceed 25 MiB under the default application configuration; storyboard requests have a smaller 256 KiB limit.

Rendering is asynchronous: submit a job, poll its state, then download its verified artifact. Proxy timeouts need to cover submission and download requests, not the full render duration.

`/health/live`, `/health/ready`, `/docs`, and `/openapi.json` do not require application authentication. Restrict their exposure at the proxy when appropriate. The application buffers bounded request bodies before authenticating them and does not include a public traffic protection layer. Native media decoders also require deployment resource and network isolation. The supplied container configuration does not enforce an outbound network policy.

## Application configuration

`Settings.from_env()` reads the following variables at process startup:

| Variable | Default | Contract |
| --- | --- | --- |
| `P2V_DATA_DIR` | `.data` for native commands; `/data` in the image | Sole persistent data root; resolved to an absolute path |
| `P2V_FONT` | `DejaVu Sans` | Installed font family; startup checks its availability |
| `P2V_API_KEYS` | Empty mapping | JSON object mapping tokens to namespaces; required by `serve` |
| `P2V_WORKERS` | `2` | One through eight render worker threads |
| `P2V_PER_NAMESPACE` | `1` | One through the worker count; maximum running jobs per namespace |
| `P2V_QUEUE_LIMIT` | `100` | At least one; global queued capacity, excluding running jobs |
| `P2V_STAGE_TIMEOUT` | `180` | Positive finite seconds for major render/encode stages; probes use shorter limits |
| `P2V_JOB_TIMEOUT` | `1800` | Positive finite execution budget; queue waiting is excluded |
| `P2V_FFMPEG_THREADS` | `2` | One through sixteen external FFmpeg encoding threads; not a host CPU limit |
| `P2V_CACHE_EPOCH` | `1` | Operator-controlled string for cache invalidation |
| `P2V_FFMPEG` | `ffmpeg` | Trusted operator's executable name or path |
| `P2V_FFPROBE` | `ffprobe` | Trusted operator's executable name or path |

Tokens must be strings of at least twenty-four characters and must not contain the placeholder marker `replace-with`. Use randomly generated values. Namespaces are one to sixty-four characters, begin with a letter or digit, and otherwise contain only letters, digits, hyphens, and underscores.

Four additional defaults are fields of `Settings`, with no environment mapping: maximum request size 256 KiB, audio asset size 25 MiB, output size 1 GiB, and minimum free disk 512 MiB. Inventing `P2V_MAX_*` variables does not configure them. These are per-operation checks, not tenant storage quotas; the output limit is checked after media has been generated. Direct Python integrations can construct `Settings`, but the provided CLI uses `from_env()`.

## Which variables Compose forwards

A project `.env` file supplies Compose interpolation; it does not automatically inject every variable into the container. The supplied `compose.yaml` forwards only:

```text
P2V_API_KEYS
P2V_WORKERS
P2V_PER_NAMESPACE
P2V_FFMPEG_THREADS
P2V_STAGE_TIMEOUT
P2V_JOB_TIMEOUT
```

For example, writing `P2V_CACHE_EPOCH=2` to `.env` alone has no effect. Add an explicit environment entry, such as this `compose.override.yaml`:

```yaml
services:
  renderer:
    environment:
      P2V_CACHE_EPOCH: "2"
      P2V_QUEUE_LIMIT: "100"
    # Measure the target workload before changing resource limits.
    cpus: 4
    mem_limit: 4g
```

Validate configuration without expanding secrets into the terminal, then recreate the service during a maintenance window:

```bash
docker compose config --quiet
docker compose up -d --force-recreate renderer
docker compose exec -T renderer study-p2v doctor
curl --fail http://127.0.0.1:8090/health/ready
```

`docker compose restart` does not apply changed environment values. A source change also requires rebuilding the image. Recreating the container can interrupt running jobs; pause new submissions and allow work to finish when interruption is undesirable.

Changing the data path requires a corresponding writable persistent mount. Naming a host font does not install that font in the container; customize the image or reviewed font mount and run `doctor` again.

## Native service

For a native Linux installation, complete the dependency steps in the quickstart, then use a fixed virtual environment and data directory. Invoke its installed `study-p2v` executable directly so service startup does not invoke dependency synchronization.

The following systemd unit is an installation example. It assumes an unprivileged `renderer` user, a prepared environment at `/opt/study-p2v/.venv`, a private token environment file at `/etc/study-p2v.env`, and writable state at `/var/lib/study-p2v`. These are administrator-selected installation paths, not required application paths.

```ini
[Unit]
Description=Study P2V renderer
After=network.target

[Service]
Type=simple
User=renderer
Group=renderer
WorkingDirectory=/opt/study-p2v
EnvironmentFile=/etc/study-p2v.env
Environment=P2V_DATA_DIR=/var/lib/study-p2v
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/study-p2v/.venv/bin/study-p2v serve --host 127.0.0.1 --port 8090
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
KillMode=mixed
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

After installing the unit, reload systemd, start it, and apply the acceptance checks below. Keep the environment file readable only by the appropriate administrator/service identity. Add host-specific filesystem and network restrictions as needed; this example is not a complete native decoder sandbox.

## Ownership, shutdown, and upgrades

Run exactly one Engine for each data directory. Do not add Uvicorn worker processes, share a directory between a live API and CLI render, or share SQLite over NFS to scale. The file lock rejects a second Engine; never delete its live lock file.

Normal shutdown requests worker cancellation and terminates controlled subprocess groups. Queued jobs remain persisted. At startup, abandoned running jobs become `failed` with `interrupted`, or `cancelled` when cancellation was already requested. Retry creates a new identity; it does not rewrite the original record. Cancelling a succeeded job does not delete its artifact.

Before upgrading, stop submissions, drain or interrupt work deliberately, stop the service, and back up the entire data volume as one consistent snapshot. Include SQLite and any WAL files, assets, artifacts, and manifests. Keep the API mapping in a separate secret backup. Retain a compatible image/environment and test restoration before relying on rollback. Compatibility must include every queued request and the database format; accepting schema version 1 does not establish arbitrary binary downgrade compatibility.

There is no automatic retention cleanup or database migration framework. Monitor disk growth and use the stopped-service cleanup procedure in [operations](operations.md). Do not delete assets or historical artifacts merely to recover cache space.

## Target acceptance checklist

A deployment record should bind the application/source identity, lockfile or image digest, target environment, configured font and runtime fingerprint, concurrency and timeout settings, safe job IDs, output hashes, and observed states. Do not include tokens or private storyboard/audio content.

Verify on the actual target:

- `doctor`, live, and ready succeed with the installed environment and persisted volume.
- Schema version 1 and 2 fixtures render; downloaded MP4s pass independent metadata, frame-count, full-decode, and SHA256 checks.
- Repeat content hits composition cache, a one-segment edit renders only that segment, and audio changes with unchanged actions reuse visuals.
- Timed cues match decoded audio and visual trigger frames; sidecar and burn modes both publish downloadable SRT.
- Two namespaces cannot access each other's jobs, assets, or downloads. Oversized or overlong audio fails explicitly.
- Running-job cancellation stops subprocesses and prevents download. A controlled restart preserves queued work and resolves interrupted running jobs.
- Proxy/TLS behavior, resource limits, data permissions, backup restoration, and a near-full volume behave as intended.
- Submission and download still work from an independent client when the development machine is disconnected.

A healthy endpoint or a local test run alone does not establish target deployment acceptance. Record untested checks as untested; see [validation](validation.md).
