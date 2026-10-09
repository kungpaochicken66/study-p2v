from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from .config import NAMESPACE, Settings
from .engine import Engine
from .errors import RenderError
from .models import Storyboard
from .runtime import runtime_fingerprint
from .store import TERMINAL


def main():
    parser = argparse.ArgumentParser(prog="study-p2v")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Authenticated API; one Uvicorn process only")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    sub.add_parser("doctor", help="Check installed dependencies without installing anything")
    render = sub.add_parser("render", help="Render a local storyboard without an HTTP server")
    render.add_argument("spec", type=Path)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--namespace", default="local")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(
                create_app(settings), host=args.host, port=args.port, access_log=False, workers=1
            )
        elif args.command == "doctor":
            report = runtime_fingerprint(settings)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "font": report["font"],
                        "packages": report["packages"],
                        "capabilities": report["capabilities"],
                    }
                )
            )
        else:
            if not NAMESPACE.fullmatch(args.namespace):
                raise RenderError("invalid_namespace")
            if args.output.exists():
                raise RenderError("output_already_exists")
            spec = Storyboard.model_validate_json(args.spec.read_text())
            subtitle_output = args.output.with_suffix(".srt")
            if spec.subtitle_mode != "none" and subtitle_output == args.output:
                raise RenderError("subtitle_output_conflicts_with_video")
            if spec.subtitle_mode != "none" and subtitle_output.exists():
                raise RenderError("output_already_exists")
            engine = Engine(replace(settings, workers=1, per_namespace=1))
            engine.start()
            try:
                row, _ = engine.store.submit(args.namespace, spec, None, settings.queue_limit)
                engine.wakeup.set()
                try:
                    while True:
                        row = engine.store.get(args.namespace, row["id"])
                        if row["state"] in TERMINAL:
                            break
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    engine.store.cancel(args.namespace, row["id"])
                    raise RenderError("cancelled") from None
                if row["state"] != "succeeded":
                    raise RenderError(row["error_code"] or row["state"])
                receipt = json.loads(row["result"])
                artifact = engine.storage.verify(args.namespace, row["id"], receipt)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("xb") as dst, artifact.open("rb") as src:
                    shutil.copyfileobj(src, dst)
                if "subtitles" in receipt.get("attachments", {}):
                    with (
                        subtitle_output.open("xb") as dst,
                        artifact.with_name("subtitles.srt").open("rb") as src,
                    ):
                        shutil.copyfileobj(src, dst)
                print(
                    json.dumps(
                        {
                            "job_id": row["id"],
                            "state": "succeeded",
                            "result": receipt,
                            "metrics": json.loads(row["metrics"]),
                        }
                    )
                )
            finally:
                engine.close()
    except RenderError as exc:
        print(json.dumps({"error": exc.code}), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError):
        print(json.dumps({"error": "invalid_input_or_configuration"}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
