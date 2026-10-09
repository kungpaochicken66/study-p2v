# Contributing to Study P2V

Study P2V is a Linux/Python 3.12 service for rendering bounded storyboards with Manim and FFmpeg. Read the [documentation index](docs/README.md), [architecture](docs/architecture.md), and [development guide](docs/development.md) before changing rendering contracts.

## Set up a development environment

Install the native libraries and fonts listed in the [quickstart](docs/quickstart.md), then run:

```bash
uv sync --locked
uv run study-p2v doctor
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Use `P2V_FONT` to select an installed font. Tests requiring real media are opt-in:

```bash
P2V_REAL_TESTS=1 uv run pytest -q
```

The default test run does not establish that real rendering works. Changes to timing, media, layout, storage, or caches need relevant real-media tests and artifact inspection. See the development guide for focused test selection.

## Propose a change

Describe the user-visible problem, expected behavior, and reproduction steps. Keep changes focused and preserve unrelated work. For rendering changes, include a small synthetic storyboard and the output properties you checked. Never include credentials, customer content, private infrastructure addresses, or raw operational logs.

Use English for source comments, documentation, and distributed examples. Tests for multilingual behavior may use explicit Unicode escapes to keep source text consistent while preserving coverage. Mathematical notation and Unicode rendering remain supported.

New templates must declare bounded inputs and stable target IDs, reuse the shared clock, and participate in cache invalidation. Do not introduce arbitrary Python/TeX execution, caller-controlled paths, runtime package installation, or network downloads during rendering.

## Validate and submit

- Run lint, formatting checks, and tests appropriate to the change.
- Keep request schema, examples, documentation, and package versions consistent.
- Check actual frames/audio and cache or encoding counts when those behaviors change.
- Build the package with `uv build` when packaging changes.
- State checks that were not run and environmental limits, including container or server validation.

The GitHub Actions workflow runs lint, real-media tests, and package builds on Linux. A local passing run does not imply a workflow or deployment has already passed.

Open a pull request with a concise description of behavior and validation. Do not publish generated caches, runtime data, credentials, virtual environments, or local video artifacts. Source distributions use an explicit file allowlist.

Contributions are accepted under the repository's [MIT license](LICENSE). Third-party components retain their own licenses; preserve applicable notices when changing dependencies or distributing images.
