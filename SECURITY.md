# Security policy

## Supported scope

Security fixes target the latest released 0.2.x version. This project does not provide a support SLA or a guarantee that all older versions receive patches.

Study P2V is intended for authenticated, trusted callers on a controlled single-host deployment. It accepts bounded structured data and uploaded audio, not arbitrary Python, shell commands, external media URLs, or caller-selected storage roots.

Native media parsers and rendering libraries are not a complete sandbox. Run the service as an unprivileged account, constrain CPU/memory/process counts, protect the persistent volume, and use TLS and a reverse proxy for cross-machine access. The [deployment guide](docs/deployment.md) and [operations guide](docs/operations.md) describe the current limits.

## Report a vulnerability privately

Use the repository's **Security → Report a vulnerability** option if private vulnerability reporting is enabled. If it is unavailable, request a private reporting channel from the repository maintainers without posting exploit details or sensitive data in a public issue.

A useful report includes the affected version, the security boundary crossed, a minimal synthetic reproduction, and the expected versus observed behavior. Do not include real API tokens, private audio, customer storyboards, private network addresses, or unredacted production logs. Coordinate disclosure with maintainers before publishing a working exploit.

## Deployment responsibilities

API tokens map to namespaces, not individual users. Every token for a namespace grants access to that namespace's tasks and assets. Authentication does not provide per-user permissions, billing, rate limiting, or resource quotas beyond the documented queue and concurrency controls.

The database contains original requests and asset metadata; files contain original audio and generated media. Protect backups and the data volume as application data. Health endpoints and API documentation are not authenticated by the application and may need proxy-level restrictions.

Do not bypass artifact integrity checks, remove an active engine lock, run multiple engines against one data directory, or distribute `.env` files and generated runtime data. Dependency and container updates should be tested against real-media cases and deployed through a controlled process.
