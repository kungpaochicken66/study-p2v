# study-p2v

Independent Manim rendering service. All development writes stay in this repository.
Keep the service self-contained. Do not introduce dependencies on private infrastructure or developer workstations.

- Read README.md and docs/architecture.md before changing render contracts.
- Accept structured data, never arbitrary Python, shell, URLs or caller-selected storage roots.
- Namespace is derived from authentication; job IDs do not grant access.
- Persist state before acknowledging acceptance; `succeeded` requires an independently verified artifact.
- Never use preview URLs as proof of durable output. Cancellation must terminate subprocess groups.
- Retain unrelated work. Commit/push/deployment needs explicit authorization.
- Test persistence, wrong-namespace access, corrupt cache/output, cancellation and actual video metadata.
- No package installation or remote downloads at application startup.
- Run `uv run ruff check .`, `uv run pytest`; rendering smoke is documented in docs/validation.md.
