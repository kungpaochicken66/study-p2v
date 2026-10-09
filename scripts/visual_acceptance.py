"""Render all 12 templates across five cases and export inspectable frame sheets.
Run from the repository root. Synthetic inputs only; artifacts stay under this repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw
from sample_specs import samples, variant

from study_p2v.config import Settings
from study_p2v.engine import Engine
from study_p2v.models import Storyboard
from study_p2v.process import run

CASES = ["ordinary", "long-text", "maximum-elements", "minimum-duration", "maximum-duration"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".artifacts/visual-v2"))
    parser.add_argument("--data", type=Path, default=Path(".data/visual-v2"))
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = replace(
        Settings.from_env(), data_dir=args.data.resolve(), workers=2, per_namespace=2
    )
    engine = Engine(settings)
    results = []
    engine.start()
    try:
        pending = {}
        for case in [args.case] if args.case else CASES:
            for sample in samples():
                segment = variant(sample, case)
                spec = Storyboard.model_validate(
                    {
                        "schema_version": 2,
                        "theme": "paper" if case == "long-text" else "midnight",
                        "output": {"width": 640, "height": 360, "fps": 15},
                        "segments": [segment],
                    }
                )
                row, _ = engine.store.submit("visual", spec, None, 100)
                pending[row["id"]] = (case, sample["template"], spec)
        engine.wakeup.set()
        last_update = 0
        while pending:
            for job_id in list(pending):
                row = engine.store.get("visual", job_id)
                if row["state"] not in {"succeeded", "failed", "cancelled"}:
                    continue
                case, template, spec = pending.pop(job_id)
                result = {
                    "case": case,
                    "template": template,
                    "job_id": job_id,
                    "state": row["state"],
                    "error_code": row["error_code"],
                }
                if row["state"] == "succeeded":
                    receipt = json.loads(row["result"])
                    source = engine.storage.verify("visual", job_id, receipt)
                    folder = output / case
                    folder.mkdir(exist_ok=True)
                    video = folder / f"{template}.mp4"
                    shutil.copyfile(source, video)
                    frames = round(spec.segments[0].duration * spec.output.fps)
                    selected = sorted({round((frames - 1) * q) for q in (0.25, 0.65, 0.95)})
                    select = "+".join(f"eq(n\\,{frame})" for frame in selected)
                    run(
                        [
                            "ffmpeg",
                            "-nostdin",
                            "-v",
                            "error",
                            "-y",
                            "-i",
                            str(video),
                            "-vf",
                            "select=" + select,
                            "-vsync",
                            "0",
                            "-frames:v",
                            str(len(selected)),
                            str(folder / f"{template}-%02d.png"),
                        ],
                        cwd=folder,
                        timeout=60,
                    )
                    result.update(
                        sha256=receipt["sha256"],
                        duration=receipt["duration"],
                        sample_frames=selected,
                        metrics=json.loads(row["metrics"]),
                    )
                results.append(result)
                (output / "report.json").write_text(
                    json.dumps(
                        {"runtime": engine.renderer.fingerprint, "results": results},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            if time.monotonic() - last_update > 20:
                print(
                    json.dumps(
                        {
                            "completed": len(results),
                            "remaining": len(pending),
                            "failed": sum(r["state"] != "succeeded" for r in results),
                        }
                    ),
                    flush=True,
                )
                last_update = time.monotonic()
            time.sleep(0.1)
    finally:
        engine.close()
    for case in [args.case] if args.case else CASES:
        sheet = Image.new("RGB", (3 * 480, 4 * 298), "#e5e7eb")
        draw = ImageDraw.Draw(sheet)
        for i, sample in enumerate(samples()):
            path = output / case / f"{sample['template']}-03.png"
            x, y = i % 3 * 480, i // 3 * 298
            if path.exists():
                with Image.open(path) as image:
                    sheet.paste(image.resize((480, 270)), (x, y + 28))
            draw.text((x + 8, y + 7), f"{sample['template']} / {case}", fill="#111827")
        sheet.save(output / f"{case}-sheet.png")
    failures = [r for r in results if r["state"] != "succeeded"]
    print(json.dumps({"cases": len(results), "failed": failures}, ensure_ascii=False), flush=True)
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
