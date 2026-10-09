# Operations and troubleshooting

This guide applies to one service process owning one persistent data directory. Read [deployment](deployment.md) first. Backup, restore, rotation, and restart commands must be applied to your own installation; this manual does not claim those operations have been tested on your server.

## Observe service health

```bash
curl --fail http://127.0.0.1:8090/health/live
curl --fail http://127.0.0.1:8090/health/ready
# For a Compose installation, avoid printing expanded environment values.
docker compose ps
docker compose stats --no-stream
```

Live only means the HTTP application responds. Ready checks Engine readiness, live worker threads, and the configured minimum free disk, 512 MiB by default. Neither proves that a long job is making progress or that enough disk remains for the next job.

Use authenticated job observations: state, update timestamp, completed segments, error code, and verified downloads of recent successes. The list endpoint returns the latest fifty jobs for the caller's namespace; it is not a complete cross-namespace monitoring feed. Composition-cache hits can complete with little intermediate progress. Failed jobs can have empty metrics; an absent measurement is not a zero-duration stage.

There is no `/metrics`, integrated alerting, automatic retention, or frame-by-frame progress endpoint. External monitoring should cover readiness, persistent-volume growth, container memory/PID limits, queue waiting, and repeated failures. Keep diagnostic records to safe IDs, states, counters, configuration summaries, and static error codes. Do not attach tokens, complete requests, audio, raw subprocess output, or database exports to public reports.

## Persistent layout and privacy

```text
P2V_DATA_DIR/
|-- jobs.sqlite3                    # Requests, jobs, idempotency, and asset metadata
|-- jobs.sqlite3-wal                # May exist while SQLite is active
|-- jobs.sqlite3-shm                # May exist while SQLite is active
|-- engine.lock                    # File-lock inode; existence does not mean ownership
|-- runtime-cache/                 # Library runtime caches
`-- namespaces/<namespace>/
    |-- assets/<asset-id>           # Original uploaded audio bytes
    |-- cache/<key>/
    |   |-- video.mp4
    |   `-- manifest.json
    |-- cache/<key>.lock
    |-- scratch/<job-id>/           # Active or crash-leftover temporary files
    `-- artifacts/<job-id>/
        |-- video.mp4
        |-- manifest.json
        `-- subtitles.srt          # Present when a subtitle mode was requested
```

Both visual and composition caches use the namespace's cache directory with distinct content keys. A published manifest must match the database receipt and actual MP4/SRT bytes. Download integrity checks enforce that match.

The database contains original storyboard requests, assets contain original audio, and generated artifacts contain the rendered content. Error redaction does not make the data volume public. Protect storage, backups, administrative access, and the token mapping according to their content. Downloads use `Cache-Control: private, no-store`; configure proxies so they do not override that policy or log bearer tokens.

Every job publishes its own artifact copy, including composition-cache hits. There are no tenant disk quotas or deduplicated hardlinks. PCM at 48 kHz, two channels, and sixteen bits per sample occupies about 192,000 bytes per second, roughly 11 MiB per minute. Allow space for decoded inputs, the complete audio timeline, visual scratch, cache entries, and publication copies in addition to final MP4s.

## Consistent backup and restore

The straightforward consistent backup is a copy of the complete data directory after writes have stopped. There is no application drain API.

1. Pause upstream submissions. Let running jobs finish if interruption is unacceptable, then stop the service and confirm that its process/container has exited.
2. Preserve SQLite and any remaining WAL/SHM files, uploaded assets, artifacts, and manifests in one snapshot. Including caches simplifies a complete-volume restore, although caches can be rebuilt.
3. Back up the token mapping separately in a secret store. Keep `.env` out of ordinary evidence bundles.
4. Record the application/source version, image digest where applicable, dependency lockfile, font, cache epoch, backup identity/time, and archive checksum. Confirm the archive is readable and complete before restarting.
5. Restore into a new empty directory or volume. Use a compatible runtime, correct ownership, and one Engine. Verify `doctor`, ready, hashes for restored successful downloads, and a fresh render from an independent client.

For stopped native state, the following reference creates a new archive without silently overwriting one:

```bash
# Set both variables to reviewed paths before running this stopped-service backup.
: "${P2V_SOURCE_DIR:?set stopped data directory}"
: "${P2V_BACKUP_FILE:?set new backup archive path}"
(set -C; tar -C "$P2V_SOURCE_DIR" -cpf - . > "$P2V_BACKUP_FILE")
sha256sum "$P2V_BACKUP_FILE"
```

Only a successful `tar` operation and readable archive qualify as a backup. A partial archive can still have a checksum; treat a failed copy as incomplete. For Compose named volumes, use your platform's stopped-volume backup mechanism rather than guessing Docker's host path or actual volume name.

Restore with an appropriate archive tool into an empty target and check UID/GID; the container user is UID 10001. Never overwrite a running volume. Do not edit database rows to convert failure into success.

Copying a running `jobs.sqlite3` alone can miss WAL state and all media. SQLite online backup can make a consistent database copy but cannot alone synchronize that database with filesystem publication; it is not a complete service snapshot.

## Shutdown and cleanup

`engine.lock` is protected by `flock`. The process releases ownership on exit; the file can remain. Removing the live file can allow another process to lock a new inode, breaking exclusive ownership. For `another_engine_owns_data_dir`, identify and stop the owner or select a different data directory. Do not delete the lock as a workaround.

Normal shutdown cancels controlled work and can mark active jobs `failed/interrupted`. Startup resolves any abandoned running state, while queued jobs remain eligible. If cancellation was requested first, a job stays cancelled. Use the retry endpoint for failed/cancelled work; it creates a new ID.

Before cleanup, stop the service and confirm no rendering process still uses the volume. Inspect each candidate path and its ownership. Namespace `cache/` entries can be removed to reclaim reusable bytes; they will be rebuilt on demand. Job scratch and hidden `.cache-*` or `.publish-*` staging directories can remain after a crash and require separate inspection.

Do not include assets, artifacts, database files, or unknown runtime-cache contents in a blanket cleanup. Cache lock files also must not be removed while in use. A cancelled job can leave an orphaned artifact after a publication race; its existence cannot restore a successful state. Permanent content deletion requires a retention/reference policy that this release does not implement.

## Common failures

| Error or symptom | Inspect | Action |
| --- | --- | --- |
| `render_dependency_missing`, `executable_unavailable` | Installed Python environment, FFmpeg/ffprobe, Fontconfig, PATH | Install missing dependencies before service startup |
| `configured_font_unavailable` | `fc-list family`, configured family, required glyphs | Use an installed suitable font; restart and retry |
| `another_engine_owns_data_dir` | Duplicate API, CLI, or container using the directory | Stop the duplicate or separate data roots; keep the live lock |
| `api_keys_required`, `invalid_api_key_configuration` | Valid mapping and actual process/container environment | Configure generated tokens; the CLI does not auto-load `.env` |
| HTTP 401 or 404 | Bearer header, namespace mapping, job/asset identity | Use the correct namespace token; do not move rows to bypass isolation |
| HTTP 422 `invalid_request` | Schema version, unknown fields, bounds, cue targets | Validate against the storyboard schema before resubmission |
| `audio_asset_not_found`, `audio_asset_corrupt` | Namespace and input bytes/digest | Upload valid audio again and submit a request with its new ID |
| `audio_longer_than_segment`, `cue_outside_audio` | Probed duration, final gap, effective frame duration | Shorten narration or lengthen the segment; retain complete narration |
| `cue_shorter_than_frame_or_out_of_bounds` | Rounded start/end frames | Use an interval of at least one frame within effective bounds |
| `text_overflow`, `math_overflow`, `subtitle_overflow` | Font, text density, math nesting, caption length | Split or simplify content; resolution alone does not enlarge layout |
| `subtitle_renderer_unavailable` | `doctor` capability `subtitle_burn` | Install an FFmpeg build with ASS support or select sidecar subtitles |
| `queue_full` | Global queued count and namespace concurrency | Back off submissions; size concurrency using workload measurements |
| `insufficient_disk_space`, ready 503 | Free volume space and worker health | Pause submissions, expand storage, or inspect stopped-service cleanup |
| `deadline_exceeded` | Complexity, resource contention, stage/job budgets | Reproduce with a minimal fixture; split work or tune measured limits |
| `artifact_verification_failed` | MP4/SRT, manifest, and database receipt consistency | Restore a consistent backup or create a new job; do not rewrite hashes |
| `interrupted`, `internal_render_error` | Shutdown/resource termination and safe job metadata | Preserve static evidence, investigate, then explicitly retry |
| `media_*`, `incompatible_visual_streams` | Media metadata, codecs, frame counts, runtime/cache environment | Confirm dependencies and fingerprint; invalidate caches when appropriate |

A succeeded job whose file later becomes corrupt can remain succeeded in the database while download returns HTTP 409. The stored state records the verified publication outcome; the download checks current integrity. A succeeded job is not retryable. Restore its consistent artifact backup or submit the same content with a new idempotency key to create a new job. Do not rewrite the historical record.

## Token rotation and upgrades

The token mapping is loaded at process startup. Add a new token mapped to the same namespace, restart during maintenance, update clients and verify access, then remove the old token and restart again. Existing job access follows namespace identity, so both tokens can access that namespace during overlap. Configuration changes containing credentials must stay out of logs and shared reports.

Retain a compatible image/environment and a consistent data backup before changing application versions. Check queued request compatibility as well as SQLite format. Font and template changes affect future rendering and cache identity; existing published artifacts are not automatically regenerated. Re-run the target checks in [deployment](deployment.md) for affected boundaries.
