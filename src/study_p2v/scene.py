"""Trusted vector templates and a single frame clock; no caller code is executed."""

from __future__ import annotations

import argparse
import json
import math
import time
import unicodedata
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    Animation,
    Arrow,
    Line,
    Rectangle,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    VMobject,
    linear,
    tempconfig,
)

from .errors import RenderError
from .math_render import MathRenderer
from .models import MathExpression

THEMES = {
    "midnight": {
        "bg": "#101827",
        "fg": "#F2F5FA",
        "muted": "#B5C3D6",
        "accent": "#60D5BC",
        "secondary": "#F4B56A",
        "panel": "#1B2A40",
    },
    "paper": {
        "bg": "#F8F6EF",
        "fg": "#202D3D",
        "muted": "#516171",
        "accent": "#167A6A",
        "secondary": "#AB5A20",
        "panel": "#E9E7DF",
    },
}


def wrap(text: str, columns: int) -> str:
    def width(char):
        return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1

    out, line, used = [], "", 0
    for char in text:
        if char == "\n":
            out.append(line)
            line, used = "", 0
            continue
        if used + width(char) > columns and line:
            if char.isspace():
                out.append(line.rstrip())
                line, used = "", 0
                continue
            boundary = max((i for i, value in enumerate(line) if value.isspace()), default=-1)
            if boundary > 0 and line[:boundary].strip():
                # Carry the whole trailing word instead of cutting it at the column limit.
                out.append(line[:boundary].rstrip())
                line = line[boundary + 1 :]
                used = sum(width(value) for value in line)
            else:
                # Unspaced text and oversized tokens still wrap by display width.
                out.append(line)
                line, used = "", 0
        line += char
        used += width(char)
    if line:
        out.append(line)
    return "\n".join(out)


class FrameTimeline(Animation):
    """One animation avoids per-transition frame rounding and cumulative time drift."""

    def __init__(self, objects, events, frames, fps, accent, exclusive=False):
        self.objects, self.events, self.frames, self.fps = objects, events, frames, fps
        self.accent, self.exclusive = accent, exclusive
        first = {}
        for event in events:
            first.setdefault(event["target"], event["action"])
        self.initial = {key: first.get(key) != "reveal" for key in objects}
        self.originals = {key: obj.copy() for key, obj in objects.items()}
        super().__init__(VGroup(*objects.values()), run_time=frames / fps, rate_func=linear)

    def interpolate_mobject(self, alpha):
        frame = min(self.frames - 1, int(round(alpha * self.frames)))
        visible, latest = self.initial.copy(), {}
        for event in self.events:
            if event["frame"] > frame:
                break
            target, action = event["target"], event["action"]
            if action == "reveal":
                if self.exclusive and target.startswith("step-"):
                    for key in visible:
                        if key.startswith("step-"):
                            visible[key] = False
                visible[target] = True
            elif action == "exit":
                visible[target] = False
            latest[target] = event
        for key, obj in self.objects.items():
            obj.become(self.originals[key])
            if not visible[key]:
                obj.set_opacity(0)
                continue
            event = latest.get(key)
            if not event:
                continue
            length = max(1, min(round(0.35 * self.fps), event["end_frame"] - event["frame"]))
            progress = min(1, (frame - event["frame"] + 1) / length)
            if event["action"] == "highlight" and frame < event["end_frame"]:
                obj.set_color(self.accent)
            elif event["action"] == "reveal" and progress < 1:
                if key.startswith("bar-"):
                    # Label/value stay legible while only the bar grows from its left edge.
                    obj[1].stretch(max(0.03, progress), 0, about_point=obj[1].get_left())
                else:
                    obj.shift(DOWN * 0.12 * (1 - progress))


class StoryScene(Scene):
    def __init__(self, spec: dict, **kwargs):
        self.spec, self.palette, self.font = spec, THEMES[spec["theme"]], spec["font"]
        self.text_objects = []
        self.objects = {}
        self.diagnostics = {}
        super().__init__(**kwargs)

    def text(self, value, *, width=11.8, height=1.2, size=36, color=None, columns=54):
        # Prefer an unbroken line when it fits; avoid a one-character orphan caused by a fixed count.
        obj = Text(
            value,
            font=self.font,
            font_size=size,
            color=color or self.palette["fg"],
            line_spacing=0.65,
        )
        if obj.width > width * 1.08 or obj.height > height * 1.08:
            for _ in range(6):
                obj = Text(
                    wrap(value, columns),
                    font=self.font,
                    font_size=size,
                    color=color or self.palette["fg"],
                    line_spacing=0.65,
                )
                if obj.width <= width + 0.01 or columns <= 4:
                    break
                columns = max(4, int(columns * width / obj.width * 0.97))
        scale = min(1, width / max(obj.width, 0.001), height / max(obj.height, 0.001))
        if size * scale < 18:
            raise RenderError("text_overflow")
        obj.scale(scale)
        self.text_objects.append((obj, round(size * scale, 2)))
        return obj

    def heading(self, value):
        title = self.text(value, width=12, height=0.85, size=42, columns=50).set_y(3.15)
        rule = Line(LEFT * 6.1, RIGHT * 6.1, color=self.palette["accent"], stroke_width=3).set_y(
            2.45
        )
        self.add(title, rule)

    def register(self, key, obj):
        self.objects[key] = obj

    def construct(self):
        begin = time.monotonic()
        s, p = self.spec["segment"], self.palette
        kind = s["template"]
        if kind == "title":
            self.register(
                "title", self.text(s["title"], width=11.8, height=2, size=64, columns=32).set_y(0.7)
            )
            self.register(
                "subtitle",
                self.text(
                    s["subtitle"], width=10.8, height=1.6, size=30, color=p["muted"], columns=54
                ).set_y(-1.1),
            )
        else:
            self.heading(s["title"])
            if kind in {"bullets", "checklist", "priority"}:
                n = len(s["items"])
                for i, value in enumerate(s["items"]):
                    y = 1.65 - i * 4.35 / max(n, 1)
                    height = min(1.4, 4.1 / n)
                    txt = self.text(value, width=10.1, height=height, size=32, columns=62)
                    txt.move_to([0.3, y, 0]).align_to(LEFT * 4.7, LEFT)
                    if kind == "checklist":
                        box = RoundedRectangle(
                            width=0.48, height=0.48, corner_radius=0.07, stroke_color=p["muted"]
                        ).move_to([-5.65, y, 0])
                        self.add(box)
                        marker = VMobject(color=p["accent"], stroke_width=4).set_points_as_corners(
                            [[-5.8, y, 0], [-5.67, y - 0.12, 0], [-5.46, y + 0.17, 0]]
                        )
                    else:
                        marker = self.text(
                            f"{i + 1:02d}",
                            width=0.65,
                            height=0.6,
                            size=28,
                            color=p["accent"] if kind == "bullets" else p["secondary"],
                        ).move_to([-5.65, y, 0])
                    if kind == "priority":
                        bar = Line(
                            [-4.7, y - height / 2 - 0.08, 0],
                            [-4.7 + 9.8 * (n - i) / n, y - height / 2 - 0.08, 0],
                            color=p["accent"],
                            stroke_width=2,
                        )
                        self.register(f"item-{i + 1}", VGroup(marker, txt, bar))
                    else:
                        self.register(f"item-{i + 1}", VGroup(marker, txt))
            elif kind == "compare":
                for side, x, color in [("left", -3.2, p["accent"]), ("right", 3.2, p["secondary"])]:
                    column = s[side]
                    panel = RoundedRectangle(
                        width=5.9,
                        height=5,
                        corner_radius=0.18,
                        stroke_width=1,
                        stroke_color=color,
                        fill_color=p["panel"],
                        fill_opacity=1,
                    ).move_to([x, -0.2, 0])
                    self.add(panel)
                    self.register(
                        f"{side}-heading",
                        self.text(
                            column["heading"],
                            width=5.2,
                            height=0.75,
                            size=34,
                            columns=24,
                            color=color,
                        ).move_to([x, 1.6, 0]),
                    )
                    for i, item in enumerate(column["items"]):
                        y = 0.45 - i * 3 / len(column["items"])
                        self.register(
                            f"{side}-{i + 1}",
                            self.text(
                                item,
                                width=5.1,
                                height=min(1.1, 2.7 / len(column["items"])),
                                size=29,
                                columns=29,
                            ).move_to([x, y, 0]),
                        )
            elif kind == "bars":
                maximum = max((v["value"] for v in s["points"]), default=1) or 1
                for i, point in enumerate(s["points"]):
                    y = 1.65 - i * 4.5 / len(s["points"])
                    label = self.text(
                        point["label"], width=2.6, height=0.62, size=26, columns=18
                    ).move_to([-4.85, y, 0])
                    width = max(0.035, 7 * point["value"] / maximum)
                    bar = Rectangle(
                        width=width,
                        height=0.42,
                        fill_color=p["accent"],
                        fill_opacity=1,
                        stroke_width=0,
                    ).move_to([-3.1 + width / 2, y, 0])
                    value = self.text(
                        f"{point['value']:g}", width=1.35, height=0.5, size=24, color=p["secondary"]
                    ).move_to([5.1, y, 0])
                    self.register(f"bar-{i + 1}", VGroup(label, bar, value))
            elif kind == "flow":
                n = len(s["steps"])
                width, spacing = min(3.8, 10.4 / n), 12 / n
                for i, label in enumerate(s["steps"]):
                    x = (i - (n - 1) / 2) * spacing
                    box = RoundedRectangle(
                        width=width,
                        height=2.2,
                        corner_radius=0.15,
                        stroke_color=p["accent"],
                        fill_color=p["panel"],
                        fill_opacity=1,
                    ).move_to([x, -0.25, 0])
                    txt = self.text(
                        label,
                        width=width - 0.3,
                        height=1.7,
                        size=30,
                        columns=max(8, int(width * 6)),
                    ).move_to(box.get_center())
                    group = VGroup(box, txt)
                    if i:
                        group.add(
                            Arrow(
                                [x - spacing + width / 2, -0.25, 0],
                                [x - width / 2, -0.25, 0],
                                buff=0.04,
                                color=p["secondary"],
                                stroke_width=2,
                            )
                        )
                    self.register(f"step-{i + 1}", group)
            elif kind == "timeline":
                self.add(Line([-5.6, 0.1, 0], [5.6, 0.1, 0], color=p["accent"]))
                for i, label in enumerate(s["steps"]):
                    w = min(3.5, 10.2 / len(s["steps"]))
                    extent = 6.1 - w / 2
                    x = -extent + i * 2 * extent / (len(s["steps"]) - 1)
                    num = self.text(
                        str(i + 1), width=0.5, height=0.5, size=26, color=p["secondary"]
                    ).move_to([x, 0.6, 0])
                    txt = self.text(label, width=w, height=2, size=27, columns=14).move_to(
                        [x, -1.25, 0]
                    )
                    self.register(f"step-{i + 1}", VGroup(num, txt))
            elif kind == "cycle":
                n, centers = len(s["steps"]), []
                for i in range(n):
                    angle = math.pi / 2 - i * 2 * math.pi / n
                    centers.append([3.8 * math.cos(angle), -0.2 + 1.65 * math.sin(angle), 0])
                for i, label in enumerate(s["steps"]):
                    box = RoundedRectangle(
                        width=2.45,
                        height=1.15,
                        corner_radius=0.2,
                        stroke_color=p["accent"],
                        fill_color=p["panel"],
                        fill_opacity=1,
                    ).move_to(centers[i])
                    txt = self.text(label, width=2.1, height=0.85, size=28, columns=12).move_to(
                        centers[i]
                    )
                    origin, dest = centers[i - 1], centers[i]
                    dx, dy = dest[0] - origin[0], dest[1] - origin[1]
                    edge = min(1.225 / max(abs(dx), 1e-9), 0.575 / max(abs(dy), 1e-9))
                    start = [origin[0] + dx * edge, origin[1] + dy * edge, 0]
                    end = [dest[0] - dx * edge, dest[1] - dy * edge, 0]
                    if n == 2:
                        offset = 0.16 if i == 0 else -0.16
                        start[0] += offset
                        end[0] += offset
                    arrow = Arrow(
                        start,
                        end,
                        buff=0.12,
                        color=p["secondary"],
                        stroke_width=2,
                        tip_length=0.18,
                        max_tip_length_to_length_ratio=0.35,
                    )
                    self.register(f"step-{i + 1}", VGroup(arrow, box, txt))
            elif kind == "definition":
                self.register(
                    "term",
                    self.text(s["term"], size=52, height=1.2, color=p["accent"], columns=36).set_y(
                        1.2
                    ),
                )
                self.register(
                    "body",
                    self.text(s["body"], width=10.8, height=2.8, size=34, columns=54).set_y(-1.0),
                )
            elif kind == "example":
                self.register(
                    "prompt",
                    self.text(
                        s["prompt"], width=11.5, height=1, size=32, color=p["secondary"], columns=60
                    ).set_y(1.55),
                )
                for i, value in enumerate(s["steps"]):
                    self.register(
                        f"step-{i + 1}",
                        self.text(value, width=11.5, height=2.9, size=40, columns=48).set_y(-0.8),
                    )
            elif kind == "equation":
                if s.get("math_steps"):
                    math_renderer = MathRenderer(Path(self.spec["math_dir"]), p["fg"])
                    for i, value in enumerate(s["math_steps"]):
                        first_symbol = len(math_renderer.symbols)
                        obj = math_renderer.render(MathExpression.model_validate(value))
                        obj.scale(
                            min(1.6, 11.5 / max(obj.width, 0.01), 3.7 / max(obj.height, 0.01))
                        )
                        if any(
                            32 * symbol.height / height < 18
                            for symbol, height in math_renderer.symbols[first_symbol:]
                        ):
                            raise RenderError("math_overflow")
                        self.register(f"step-{i + 1}", obj.move_to([0, -0.2, 0]))
                else:
                    for i, value in enumerate(s["steps"]):
                        self.register(
                            f"step-{i + 1}",
                            self.text(value, width=11.5, height=3.7, size=52, columns=40).set_y(
                                -0.2
                            ),
                        )
        fps, frames = self.spec["output"]["fps"], self.spec["frames"]
        events = self.spec.get("events", [])
        if not events:
            window = max(len(self.objects), round(frames * 0.65))
            for i, key in enumerate(self.objects):
                start = int(i * window / len(self.objects))
                end = max(start + 1, int((i + 1) * window / len(self.objects)))
                events.append(
                    {
                        "target": key,
                        "action": "reveal",
                        "frame": start,
                        "end_frame": min(end, frames),
                    }
                )
        boxes = []
        for obj, size in self.text_objects:
            x, y = obj.get_center()[:2]
            if abs(x) + obj.width / 2 > 6.45 or abs(y) + obj.height / 2 > 3.7:
                raise RenderError("layout_out_of_bounds")
            boxes.append(
                {
                    "x": round(float(x), 3),
                    "y": round(float(y), 3),
                    "width": round(obj.width, 3),
                    "height": round(obj.height, 3),
                    "font_size": size,
                }
            )
        self.diagnostics = {
            "layout_seconds": round(time.monotonic() - begin, 4),
            "text_boxes": boxes,
            "events": events,
            "frames": frames,
        }
        animation = FrameTimeline(
            self.objects,
            events,
            frames,
            fps,
            p["secondary"],
            exclusive=kind in {"equation", "example"},
        )
        self.play(animation, run_time=frames / fps, rate_func=linear)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = args.output.parent / "scene-report.json"
    try:
        spec = json.loads(args.spec.read_text())
        spec["math_dir"] = str(args.output.parent / "math")
        out = spec["output"]
        spec.setdefault("frames", round(spec["segment"]["duration"] * out["fps"]))
        with tempconfig(
            {
                "renderer": "cairo",
                "pixel_width": out["width"],
                "pixel_height": out["height"],
                "frame_width": 128 / 9,
                "frame_height": 8,
                "frame_rate": out["fps"],
                "background_color": THEMES[spec["theme"]]["bg"],
                "output_file": str(args.output.resolve()),
                "media_dir": str(args.output.parent / "media"),
                "write_to_movie": True,
                "format": "mp4",
                "disable_caching": True,
                "verbosity": "ERROR",
                "progress_bar": "none",
                "preview": False,
            }
        ):
            scene = StoryScene(spec)
            scene.render()
        report.write_text(json.dumps(scene.diagnostics))
    except RenderError as exc:
        report.write_text(json.dumps({"error_code": exc.code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
