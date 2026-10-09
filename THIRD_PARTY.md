# Open-source foundations

Study P2V combines a task orchestration layer and structured animation templates with the
following open-source components. These dependencies are installed rather than vendored.

- [Manim Community](https://github.com/ManimCommunity/manim), 0.21.0: programmatic animation.
- [FFmpeg](https://ffmpeg.org/): probe, normalization, audio mux and concatenation, invoked as binaries.
- [FastAPI](https://github.com/fastapi/fastapi) and [Uvicorn](https://github.com/encode/uvicorn): HTTP API.
- [Pydantic](https://github.com/pydantic/pydantic): structured request schemas.
- [Matplotlib](https://matplotlib.org/), 3.10.8: MathText symbol paths; no external TeX runtime.
- [psutil](https://github.com/giampaolo/psutil): sampled process-tree resource measurements.
- [SQLite](https://sqlite.org/): local transactional queue and outcome persistence.
- DejaVu fonts: default container font family, supplied by the OS package `fonts-dejavu-core`.

LICENSE covers this repository's original code. Dependencies, system libraries, codecs and fonts
retain their own licenses. FFmpeg build flags affect the delivered binary's licensing; record the
actual build and retain upstream notices when distributing images. No third-party code is relicensed
by this repository's LICENSE. Python versions are in uv.lock; OS package versions are recorded by the
image build and are not claimed to be bit-for-bit reproducible by uv.lock.
