"""Render a bounded math AST without executing TeX, Python, or shell input."""

from __future__ import annotations

import hashlib
from pathlib import Path

from manim import DOWN, LEFT, RIGHT, UP, Line, SVGMobject, VGroup, VMobject
from matplotlib import rc_context
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import math_to_image

from .errors import RenderError
from .models import MathExpression


class MathRenderer:
    def __init__(self, directory: Path, color: str):
        self.directory, self.color = directory, color
        self.symbols = []
        directory.mkdir(parents=True, exist_ok=True)

    def symbol(self, value: str):
        # Input symbols have already passed a strict alphabet; commands here are authored by us.
        safe = value.replace("%", r"\%")
        digest = hashlib.sha256((safe + self.color).encode()).hexdigest()
        path = self.directory / f"{digest}.svg"
        if not path.exists():
            try:
                with rc_context(
                    {"text.usetex": False, "svg.fonttype": "path", "mathtext.fontset": "dejavusans"}
                ):
                    math_to_image(
                        f"${safe}$",
                        path,
                        prop=FontProperties(size=32),
                        format="svg",
                        color=self.color,
                    )
                # Drop the generated figure background instead of relying on SVG importer defaults.
                import xml.etree.ElementTree as ET

                tree = ET.parse(path)
                for parent in tree.iter():
                    for child in list(parent):
                        if child.get("id") == "patch_1":
                            parent.remove(child)
                tree.write(path, encoding="utf-8", xml_declaration=True)
            except (ValueError, RuntimeError):
                raise RenderError("math_layout_failed") from None
        result = SVGMobject(str(path), height=None, width=None)
        # SVG units are points; a constant conversion preserves baseline size across symbols.
        result.scale(0.019)
        self.symbols.append((result, max(result.height, 0.001)))
        return result

    def render(self, expression: MathExpression):
        kind = expression.kind
        if kind == "symbol":
            return self.symbol(expression.value)
        if kind == "matrix":
            rows = [[self.render(cell) for cell in row] for row in expression.rows]
            heights = [max(cell.height for cell in row) for row in rows]
            widths = [max(row[col].width for row in rows) for col in range(len(rows[0]))]
            gap_x, gap_y = 0.4, 0.32
            width = sum(widths) + gap_x * (len(widths) - 1)
            height = sum(heights) + gap_y * (len(heights) - 1)
            y, cells = height / 2, []
            for row, h in zip(rows, heights, strict=True):
                x = -width / 2
                for cell, w in zip(row, widths, strict=True):
                    cell.move_to([x + w / 2, y - h / 2, 0])
                    cells.append(cell)
                    x += w + gap_x
                y -= h + gap_y
            x, y = width / 2 + 0.2, height / 2 + 0.15
            brackets = []
            for side in (-1, 1):
                brackets.append(
                    VMobject(color=self.color, stroke_width=2).set_points_as_corners(
                        [
                            [side * (x - 0.12), y, 0],
                            [side * x, y, 0],
                            [side * x, -y, 0],
                            [side * (x - 0.12), -y, 0],
                        ]
                    )
                )
            return VGroup(*cells, *brackets)
        parts = [self.render(part) for part in expression.parts]
        if kind == "row":
            return VGroup(*parts).arrange(RIGHT, buff=0.15)
        if kind == "fraction":
            numerator, denominator = parts
            numerator.scale(0.88)
            denominator.scale(0.88)
            width = max(numerator.width, denominator.width) + 0.25
            line = Line(LEFT * width / 2, RIGHT * width / 2, color=self.color, stroke_width=2)
            numerator.next_to(line, UP, buff=0.13)
            denominator.next_to(line, DOWN, buff=0.13)
            return VGroup(numerator, line, denominator)
        if kind == "root":
            content = parts[0]
            x, y = content.width / 2, content.height / 2
            radical = VMobject(color=self.color, stroke_width=2).set_points_as_corners(
                [
                    [-x - 0.55, 0, 0],
                    [-x - 0.43, 0.1, 0],
                    [-x - 0.28, -y - 0.08, 0],
                    [-x - 0.12, y + 0.15, 0],
                    [x + 0.12, y + 0.15, 0],
                ]
            )
            return VGroup(radical, content)
        base, script = parts
        script.scale(0.58)
        script.next_to(base, RIGHT, buff=0.07)
        script.set_y(base.get_top()[1] if kind == "sup" else base.get_bottom()[1])
        return VGroup(base, script)
