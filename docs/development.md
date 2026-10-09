# Development

Use [architecture](architecture.md) to understand the contracts and [quickstart](quickstart.md) to install the native dependencies. All application behavior belongs to the `study_p2v` package; the command is `study-p2v`. Version 0.2.0 is a standalone service with bounded input and a verified artifact success contract.

## Source map

| Module | Responsibility | Related checks |
| --- | --- | --- |
| [models.py](../src/study_p2v/models.py) | Strict storyboard types, input bounds, stable target IDs, canonical JSON | Schema compatibility, examples, idempotency |
| [timing.py](../src/study_p2v/timing.py) | Effective frames, audio intervals, cues, SRT | Visual actions, sample boundaries, caption offsets |
| [scene.py](../src/study_p2v/scene.py) | Template layout, measured text, frame clock | Readability, target registration, exclusive steps |
| [math_render.py](../src/study_p2v/math_render.py) | Bounded math tree to SVG and primitives | Tree limits, glyph size, transparent symbol backgrounds |
| [media.py](../src/study_p2v/media.py) | Probes, normalization, stream copying, PCM, mux, ASS | Exact frames, audio duration, encode counts, cancellation |
| [renderer.py](../src/study_p2v/renderer.py) | Job pipeline, two caches, budgets, metrics | Cache identity, corruption, publication |
| [runtime.py](../src/study_p2v/runtime.py) | Environment fingerprint, font checks, child environment, disk checks | Source coverage in fingerprints, secret isolation |
| [process.py](../src/study_p2v/process.py) | Bounded subprocess execution and process-tree samples | Deadlines, cancellation, descendant termination |
| [storage.py](../src/study_p2v/storage.py) | Namespace paths, cache locks, durable publication | fsync, independent reads, corrupt manifests |
| [store.py](../src/study_p2v/store.py) | SQLite transactions, acceptance, claims, terminal states, assets | Concurrent idempotency, restart, cancellation races |
| [engine.py](../src/study_p2v/engine.py) | Data-directory ownership and worker lifecycle | One Engine, quotas, final verification |
| [api.py](../src/study_p2v/api.py) | Authentication, body limits, HTTP endpoints | Namespace isolation, static errors, response codes |
| [cli.py](../src/study_p2v/cli.py) | `doctor`, `render`, `serve` | Local export, sidecars, no overwrite, exit codes |
| [config.py](../src/study_p2v/config.py) | Settings and environment mapping | Valid ranges, defaults, Compose forwarding |

The main path is API submission, `Store.submit`, `Engine._worker`, and `Renderer.render`. Completion must pass `DiskStorage.publish` and independent storage verification before `Store.finish` records success. A rendering shortcut must preserve that path.

## Local development loop

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Default pytest skips real-media modules unless `P2V_REAL_TESTS=1`. When changing rendering, audio, timing, caches, or publication, run the affected real tests with an installed font:

```bash
P2V_REAL_TESTS=1 P2V_FONT='DejaVu Sans' \
  uv run pytest -q tests/test_v2_media.py
# Use the complete regression suite when shared behavior requires it.
P2V_REAL_TESTS=1 P2V_FONT='DejaVu Sans' uv run pytest -q
```

Replace the font family when your environment uses a different installed font. Pytest uses `.cache/pytest-tmp` as its fixed base temporary directory and can replace content there on the next run. Preserve needed media in a separate ignored artifact directory before rerunning. Do not run concurrent pytest sessions with that shared base directory.

Documentation changes should be checked for links, example syntax, and consistency with source. A performance change needs actual render/encode counts and output verification, not just faster test execution. Run the [benchmark](performance.md) with a fixed candidate and without simultaneous rendering workloads.

## Adding a template

1. Define strict fields, content bounds, and schema requirements in `models.py`; add the template to the discriminated union and template names.
2. Supply stable IDs in `target_ids`. Base IDs on the content position or explicit structure, not display text.
3. Build layout in `StoryScene.construct` using the existing text, heading, registration, theme, and safe-area helpers. Keep `FrameTimeline` as the animation clock.
4. Update API target conventions, [templates](templates.md), synthetic samples in `scripts/sample_specs.py`, and `examples/v2-templates.json`.
5. Add new rendering modules to the appropriate runtime fingerprint list. Keep dependency and font installation outside application startup.
6. Test invalid content, missing targets, bounded complexity, and explicit overflow. Inspect actual keyframes for layout and cue-trigger behavior.
7. Check side effects: editing one segment renders only that segment; audio-only changes with unchanged actions reuse visuals; concurrent identical cache keys avoid duplicate production.

A new mathematical expression kind also requires model arity/complexity checks, renderer support, and real readable examples. Do not substitute arbitrary TeX, `eval`, Python, caller paths, or shell input for bounded data.

## Select meaningful validation

| Change | Relevant evidence |
| --- | --- |
| Storyboard contract | `test_contracts.py`, `test_v2_contracts.py`, `test_timing.py`; all shipped examples validate |
| Queue, idempotency, terminal state | `test_store.py`, `test_engine.py`, `test_v2_persistence.py`; inspect persisted states and races |
| Storage/publication | `test_storage.py` and real download hashes; corruption must prevent success/download |
| HTTP boundary | `test_api.py`; add real-media API tests when output behavior changes |
| Process management | `test_process.py`; verify descendants exit on timeout and cancellation |
| Template layout | Visual matrix and inspected keyframes; full decode when needed |
| Audio and cues | Final decoded waveforms and trigger-frame pixels, short clips, sample-rate conversion, gaps |
| Performance | Same candidate/input/cache state, output verification, stage timings, actual render/encode counts |

Useful rendering tools:

```bash
P2V_FONT='DejaVu Sans' uv run python scripts/visual_acceptance.py \
  --case ordinary --output .artifacts/visual-review --data .data/visual-review
P2V_FONT='DejaVu Sans' uv run python scripts/benchmark.py \
  --cpus 4 --output .artifacts/benchmark-review --data .data/benchmark-review
```

Use fresh output and data directories for every run. The visual script can overwrite same-named exports and operates at 640x360/15 fps. Omitting `--case` selects all five variants for each template. The benchmark uses a different fixture at 1280x720/24 fps and refuses an existing data directory/report. Review [validation](validation.md) for evidence limitations.

## Packaging and CI

Keep the package version in `pyproject.toml`, `study_p2v.__init__`, and the FastAPI metadata consistent. Build and inspect distributable artifacts:

```bash
uv lock --check
uv build
```

The wheel must contain every required runtime module and exclude credentials, state, generated media, and caches. The source archive should contain the documented examples and files needed to build the release. Check entry points and installation from the built distribution, not only an editable checkout.

Repository [GitHub Actions workflow](../.github/workflows/ci.yml) provides environment checks, lint/format checks, real-media tests, and wheel/source builds on Ubuntu with Python 3.12 and the pinned uv version. Local execution and a configured workflow do not prove that a GitHub run has passed; report those independently. Contribution and security guidance are in [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md). Distribution and font obligations are described in [THIRD_PARTY.md](../THIRD_PARTY.md).

Filesystem storage is the only implemented backend. A new backend must supply durable publication and independent target reads. Distributed workers require a lease/ownership design and consistent shared artifacts; multiple Uvicorn processes or a network-mounted SQLite directory do not implement those guarantees.
