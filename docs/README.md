# Documentation

These guides describe study-p2v **0.2.0**: a single-host service that renders bounded JSON
storyboards with Manim and assembles verified MP4 artifacts with FFmpeg. Supply the content
and optional audio yourself. The service does not generate scripts, voices, images, or video
footage.

## Choose a guide

| Goal | Guide | What it covers |
| --- | --- | --- |
| Make your first video | [Quickstart](quickstart.md) | Install dependencies, select a font, render, and verify output |
| Automate local rendering | [CLI](cli.md) | `doctor`, `render`, `serve`, output handling, and exit codes |
| Connect an application | [API](api.md) | Authentication, upload, idempotent submission, polling, download verification, cancel, and retry |
| Write a storyboard | [Templates and mathematics](templates.md) | All 12 templates, limits, targets, and mathematical data |
| Host the service | [Deployment](deployment.md) | Configuration, Compose, persistent storage, resources, and deployment acceptance |
| Maintain an installation | [Operations](operations.md) | Health, failures, data ownership, backup, and recovery |
| Understand the design | [Architecture](architecture.md) | State, timing, caching, encoding, and durable publication |
| Extend the code | [Development](development.md) | Source responsibilities, extension points, and relevant checks |
| Establish acceptance evidence | [Validation](validation.md) | Unit, real-media, visual, and deployment checks |
| Measure throughput | [Performance](performance.md) | Controlled workloads and interpretation of metrics |
| Estimate resources | [Costs](costs.md) | Hardware and operating-cost assumptions |
| Understand failure modes | [Lessons](lessons.md) | Rendering, timing, media, and persistence pitfalls |

The [project README](../README.md) is the short entry point. The
[third-party notice](../THIRD_PARTY.md) covers dependency and font licensing. See
[contributing](../CONTRIBUTING.md) for contribution requirements and
[security](../SECURITY.md) for vulnerability reporting.

## Choose an example

| File | Schema | Use |
| --- | --- | --- |
| [minimal.json](../examples/minimal.json) | V1 | A small, silent title video for checking the environment |
| [storyboard.json](../examples/storyboard.json) | V1 | The seven V1 template types |
| [v2-templates.json](../examples/v2-templates.json) | V2 | All 12 templates, including structured mathematics |
| [Narration examples](api.md) | V2 | Timed audio or individual clips, with subtitles |

The JSON examples contain English demonstration content and no bundled narration. Generate
videos on your own installation. Runtime data, local output, virtual environments, and caches
are not part of the source distribution.

## Contracts and evidence

The authoritative input contract is implemented in `src/study_p2v` and exposed by the
authenticated `GET /v1/templates` endpoint. Unknown fields are rejected. Successful schema
validation does not guarantee that a particular text or formula fits; layout is checked
during rendering.

Acceptance evidence must identify the exact source candidate, runtime, font, configuration,
and entry point. A passing control-plane test does not prove real video rendering. A local
render does not prove a container or target-server installation. Follow the
[validation guide](validation.md) to establish the evidence needed for your deployment.
