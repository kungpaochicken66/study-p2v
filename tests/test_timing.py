from pathlib import Path

import pytest
from pydantic import ValidationError

from study_p2v.errors import RenderError
from study_p2v.models import Storyboard
from study_p2v.timing import resolve_timing, srt, subtitle_entries


def segment(narration, duration=4):
    return Storyboard.model_validate(
        {
            "schema_version": 2,
            "segments": [
                {
                    "template": "bullets",
                    "title": "Timeline",
                    "items": ["First", "Second"],
                    "duration": duration,
                    "narration": narration,
                }
            ],
        }
    ).segments[0]


def test_clip_durations_and_gaps_drive_one_clock():
    s = segment(
        {
            "mode": "clips",
            "utterances": [
                {"audio_asset_id": "a", "target": "item-1", "text": "First", "gap_after": 0.2},
                {"audio_asset_id": "b", "target": "item-2", "text": "Second"},
            ],
        }
    )
    durations = {"a": 1.13, "b": 0.73}
    timing = resolve_timing(s, 24, lambda key: (Path(key), key, durations[key]))
    assert timing.cues[1].start == pytest.approx(1.33)
    assert timing.audio[1].start == timing.cues[1].start
    assert timing.visual_events(24)[1]["frame"] == 32
    captions = subtitle_entries([timing, timing])
    assert captions[2]["start"] == 4
    assert "00:00:05,330 --> 00:00:06,060" in srt(captions)


def test_audio_changes_do_not_change_visual_events():
    data = {
        "mode": "timed",
        "audio_asset_id": "a",
        "cues": [{"start": 0, "end": 2, "target": "item-1", "text": "First"}],
    }
    first = resolve_timing(segment(data), 30, lambda key: (Path(key), "hash1", 3))
    data["audio_asset_id"] = "b"
    data["cues"][0]["text"] = "Update the spoken content"
    second = resolve_timing(segment(data), 30, lambda key: (Path(key), "hash2", 3))
    assert first.visual_events(30) == second.visual_events(30)


def test_cue_outside_audio_and_too_short_for_frame_rejected():
    data = {
        "mode": "timed",
        "audio_asset_id": "a",
        "cues": [{"start": 0, "end": 2, "target": "item-1", "text": "First"}],
    }
    with pytest.raises(RenderError, match="cue_outside_audio"):
        resolve_timing(segment(data), 15, lambda key: (Path(key), key, 1))
    data["cues"][0]["end"] = 0.001
    with pytest.raises(RenderError, match="cue_shorter_than_frame"):
        resolve_timing(segment(data), 15, lambda key: (Path(key), key, 3))


def test_clips_cannot_overrun_or_trim_audio():
    data = {
        "mode": "clips",
        "utterances": [{"audio_asset_id": "a", "target": "item-1", "text": "First"}],
    }
    with pytest.raises(RenderError, match="audio_longer_than_segment"):
        resolve_timing(segment(data), 15, lambda key: (Path(key), key, 4.01))


def test_every_exclusive_step_needs_an_explicit_reveal():
    with pytest.raises(ValidationError, match="every_overlaid_step"):
        Storyboard.model_validate(
            {
                "schema_version": 2,
                "segments": [
                    {
                        "template": "equation",
                        "title": "Derivation",
                        "steps": ["a", "b"],
                        "narration": {
                            "mode": "timed",
                            "audio_asset_id": "a",
                            "cues": [{"start": 0, "end": 2, "target": "step-1", "text": "First"}],
                        },
                    }
                ],
            }
        )
