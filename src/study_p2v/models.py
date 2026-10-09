from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=48)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
Action = Literal["reveal", "highlight", "exit"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MathExpression(StrictModel):
    """Bounded mathematical data, never TeX or a Python expression."""

    kind: Literal["symbol", "row", "fraction", "root", "sub", "sup", "matrix"]
    value: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None
    parts: list[MathExpression] = Field(default_factory=list, max_length=16)
    rows: list[list[MathExpression]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def valid_tree(self):
        if self.kind == "symbol":
            if self.parts or self.rows or not self.value or not self.value.strip():
                raise ValueError("math_symbol_required")
            if not re.fullmatch(r"[a-zA-Z0-9 .,+=()<>|:/!%\-α-ωΑ-Ω∞±×÷≤≥≠π]+", self.value):
                raise ValueError("math_symbol_not_allowed")
        elif self.value is not None:
            raise ValueError("math_value_only_for_symbol")
        if self.kind == "matrix":
            if self.parts or not self.rows or not 1 <= len(self.rows[0]) <= 4:
                raise ValueError("math_matrix_dimensions")
            if any(len(row) != len(self.rows[0]) for row in self.rows):
                raise ValueError("math_matrix_not_rectangular")
        elif self.rows:
            raise ValueError("math_rows_only_for_matrix")
        count = {"fraction": 2, "root": 1, "sub": 2, "sup": 2}.get(self.kind)
        if count is not None and len(self.parts) != count:
            raise ValueError("math_arity")
        if self.kind == "row" and not self.parts:
            raise ValueError("math_row_empty")
        # Check the entire subtree at each construction boundary, including nested matrices.
        stack, nodes = [(self, 1)], 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > 8 or nodes > 128:
                raise ValueError("math_complexity_limit")
            stack.extend((child, depth + 1) for child in item.parts)
            stack.extend((child, depth + 1) for row in item.rows for child in row)
        return self


class Cue(StrictModel):
    start: float = Field(ge=0, lt=60)
    end: float = Field(gt=0, le=60)
    target: Identifier
    action: Action = "reveal"
    text: Text

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end <= self.start:
            raise ValueError("cue_end_before_start")
        return self


class TimedNarration(StrictModel):
    mode: Literal["timed"]
    audio_asset_id: Identifier
    cues: list[Cue] = Field(min_length=1, max_length=32)


class Utterance(StrictModel):
    audio_asset_id: Identifier
    target: Identifier
    action: Action = "reveal"
    text: Text
    gap_after: float = Field(default=0, ge=0, le=5)


class ClipNarration(StrictModel):
    mode: Literal["clips"]
    utterances: list[Utterance] = Field(min_length=1, max_length=32)


Narration = Annotated[TimedNarration | ClipNarration, Field(discriminator="mode")]


class SegmentBase(StrictModel):
    title: ShortText
    duration: float = Field(default=4, ge=1, le=60)
    audio_asset_id: Identifier | None = None
    narration: Narration | None = None

    @model_validator(mode="after")
    def unambiguous_audio(self):
        if self.audio_asset_id and self.narration:
            raise ValueError("ambiguous_audio_input")
        return self


class Title(SegmentBase):
    template: Literal["title"]
    subtitle: Text = "Structured ideas, rendered clearly"


class Bullets(SegmentBase):
    template: Literal["bullets"]
    items: list[Text] = Field(min_length=1, max_length=6)


class Column(StrictModel):
    heading: ShortText
    items: list[Text] = Field(min_length=1, max_length=4)


class Compare(SegmentBase):
    template: Literal["compare"]
    left: Column
    right: Column


class Point(StrictModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
    value: float = Field(ge=0, le=1e9)


class Bars(SegmentBase):
    template: Literal["bars"]
    points: list[Point] = Field(min_length=1, max_length=6)


class Flow(SegmentBase):
    template: Literal["flow"]
    steps: list[ShortText] = Field(min_length=2, max_length=5)


class Timeline(SegmentBase):
    template: Literal["timeline"]
    steps: list[ShortText] = Field(min_length=2, max_length=5)


class Equation(SegmentBase):
    template: Literal["equation"]
    steps: list[Text] | None = Field(default=None, min_length=1, max_length=6)
    math_steps: list[MathExpression] | None = Field(default=None, min_length=1, max_length=6)

    @model_validator(mode="after")
    def exactly_one_representation(self):
        if (self.steps is None) == (self.math_steps is None):
            raise ValueError("equation_requires_one_step_representation")
        return self


class Definition(SegmentBase):
    template: Literal["definition"]
    term: ShortText
    body: Text


class Example(SegmentBase):
    template: Literal["example"]
    prompt: Text
    steps: list[Text] = Field(min_length=1, max_length=6)


class Cycle(SegmentBase):
    template: Literal["cycle"]
    steps: list[ShortText] = Field(min_length=2, max_length=5)


class Checklist(SegmentBase):
    template: Literal["checklist"]
    items: list[Text] = Field(min_length=1, max_length=6)


class Priority(SegmentBase):
    template: Literal["priority"]
    # Input order is the priority order, highest first; never sort labels lexicographically.
    items: list[Text] = Field(min_length=1, max_length=6)


Segment = Annotated[
    Title
    | Bullets
    | Compare
    | Bars
    | Flow
    | Timeline
    | Equation
    | Definition
    | Example
    | Cycle
    | Checklist
    | Priority,
    Field(discriminator="template"),
]
LEGACY_TEMPLATES = {"title", "bullets", "compare", "bars", "flow", "timeline", "equation"}
TEMPLATE_NAMES = sorted(
    LEGACY_TEMPLATES | {"definition", "example", "cycle", "checklist", "priority"}
)


def target_ids(segment: SegmentBase) -> list[str]:
    kind = segment.template
    if kind == "title":
        return ["title", "subtitle"]
    if kind == "definition":
        return ["term", "body"]
    if kind == "compare":
        return [
            f"{side}-{i}"
            for side in ("left", "right")
            for i in ["heading", *range(1, len(getattr(segment, side).items) + 1)]
        ]
    if kind in {"bullets", "checklist", "priority"}:
        return [f"item-{i + 1}" for i in range(len(segment.items))]
    if kind == "bars":
        return [f"bar-{i + 1}" for i in range(len(segment.points))]
    steps = segment.steps or getattr(segment, "math_steps", [])
    ids = [f"step-{i + 1}" for i in range(len(steps))]
    return ["prompt", *ids] if kind == "example" else ids


def asset_ids(segment: SegmentBase) -> list[str]:
    if segment.audio_asset_id:
        return [segment.audio_asset_id]
    if isinstance(segment.narration, TimedNarration):
        return [segment.narration.audio_asset_id]
    if isinstance(segment.narration, ClipNarration):
        return [u.audio_asset_id for u in segment.narration.utterances]
    return []


class OutputProfile(StrictModel):
    width: int = Field(default=1280, ge=320, le=1920)
    height: int = Field(default=720, ge=180, le=1080)
    fps: Literal[15, 24, 30] = 24

    @model_validator(mode="after")
    def valid_dimensions(self):
        if self.width % 2 or self.height % 2:
            raise ValueError("dimensions_must_be_even")
        if not math.isclose(self.width / self.height, 16 / 9, abs_tol=0.025):
            raise ValueError("only_landscape_16_9_supported")
        return self


class Storyboard(StrictModel):
    schema_version: Literal[1, 2] = 1
    theme: Literal["midnight", "paper"] = "midnight"
    output: OutputProfile = Field(default_factory=OutputProfile)
    subtitle_mode: Literal["none", "sidecar", "burn"] = "none"
    segments: list[Segment] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def valid_storyboard(self):
        if sum(s.duration for s in self.segments) > 600:
            raise ValueError("storyboard_max_duration_600_seconds")
        if self.schema_version == 1 and self.subtitle_mode != "none":
            raise ValueError("v2_required")
        for segment in self.segments:
            if self.schema_version == 1 and (
                segment.narration
                or segment.template not in LEGACY_TEMPLATES
                or getattr(segment, "math_steps", None)
            ):
                raise ValueError("v2_required")
            narration = segment.narration
            if not narration:
                continue
            valid_targets = target_ids(segment)
            entries = (
                narration.cues if isinstance(narration, TimedNarration) else narration.utterances
            )
            if segment.template in {"equation", "example"}:
                steps = {target for target in valid_targets if target.startswith("step-")}
                revealed = {entry.target for entry in entries if entry.action == "reveal"}
                if not steps <= revealed:
                    raise ValueError("every_overlaid_step_requires_reveal_cue")
            previous = 0
            for entry in entries:
                if entry.target not in valid_targets:
                    raise ValueError("cue_unknown_target")
                if isinstance(entry, Cue):
                    if entry.start < previous or entry.end > segment.duration:
                        raise ValueError("cue_out_of_order_or_bounds")
                    previous = entry.end
        return self


def canonical(value: BaseModel | dict) -> str:
    import json

    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
