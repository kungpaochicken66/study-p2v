import pytest
from pydantic import ValidationError

from study_p2v.models import Storyboard


def spec(segment, **kwargs):
    return {"schema_version": 2, "segments": [segment], **kwargs}


def test_v2_timed_narration_is_structured_and_v1_is_preserved():
    segment = {
        "template": "bullets",
        "title": "Synchronized",
        "items": ["First", "Second"],
        "duration": 4,
        "narration": {
            "mode": "timed",
            "audio_asset_id": "sound",
            "cues": [
                {"start": 0, "end": 1, "target": "item-1", "text": "First"},
                {"start": 2, "end": 3, "target": "item-2", "text": "Second"},
            ],
        },
    }
    parsed = Storyboard.model_validate(spec(segment, subtitle_mode="sidecar"))
    assert parsed.segments[0].narration.cues[1].start == 2
    with pytest.raises(ValidationError):
        Storyboard.model_validate({"segments": [segment]})
    assert (
        Storyboard.model_validate(
            {"segments": [{"template": "title", "title": "Legacy version"}]}
        ).schema_version
        == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        {"target": "item-9"},
        {"start": 3, "end": 5},
        {"start": 1, "end": 1},
        {"start": float("nan")},
        {"action": "exec"},
    ],
)
def test_timeline_rejects_invalid_targets_times_and_actions(change):
    cue = {"start": 0, "end": 2, "target": "item-1", "text": "Narration"} | change
    segment = {
        "template": "bullets",
        "title": "Title",
        "items": ["Content"],
        "narration": {"mode": "timed", "audio_asset_id": "sound", "cues": [cue]},
    }
    with pytest.raises(ValidationError):
        Storyboard.model_validate(spec(segment))


def test_overlapping_cues_and_ambiguous_audio_rejected():
    segment = {
        "template": "title",
        "title": "Test",
        "narration": {
            "mode": "timed",
            "audio_asset_id": "sound",
            "cues": [
                {"start": 0, "end": 2, "target": "title", "text": "Start"},
                {"start": 1, "end": 3, "target": "subtitle", "text": "Overlap"},
            ],
        },
    }
    with pytest.raises(ValidationError):
        Storyboard.model_validate(spec(segment))
    segment["narration"]["cues"].pop()
    segment["audio_asset_id"] = "other"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(spec(segment))


@pytest.mark.parametrize(
    "segment",
    [
        {"template": "definition", "term": "Cache", "body": "Reuse output for identical input"},
        {"template": "example", "prompt": "Add the numbers", "steps": ["1+1", "2"]},
        {"template": "cycle", "steps": ["Observe", "Act", "Review"]},
        {"template": "checklist", "items": ["Check input", "Verify results"]},
        {"template": "priority", "items": ["Fix correctness first", "Then check performance"]},
        {
            "template": "equation",
            "math_steps": [
                {
                    "kind": "fraction",
                    "parts": [{"kind": "symbol", "value": "1"}, {"kind": "symbol", "value": "2"}],
                }
            ],
        },
    ],
)
def test_new_templates_are_v2_only(segment):
    segment = dict(segment, title="Demo")
    assert Storyboard.model_validate(spec(segment))
    with pytest.raises(ValidationError):
        Storyboard.model_validate({"segments": [segment]})


@pytest.mark.parametrize(
    "expr",
    [
        {"kind": "symbol", "value": r"\input{/etc/passwd}"},
        {"kind": "fraction", "parts": [{"kind": "symbol", "value": "1"}]},
        {"kind": "matrix", "rows": [[{"kind": "symbol", "value": "1"}], []]},
    ],
)
def test_math_rejects_code_and_malformed_structure(expr):
    with pytest.raises(ValidationError):
        Storyboard.model_validate(
            spec({"template": "equation", "title": "Equation", "math_steps": [expr]})
        )
