"""One resolved clock drives animation, audio placement, and subtitle export."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import RenderError
from .models import ClipNarration, Cue, SegmentBase, TimedNarration


@dataclass(frozen=True)
class AudioPart:
    path: Path
    sha256: str
    start: float
    duration: float


@dataclass
class Timing:
    duration: float
    frames: int
    cues: list[Cue] = field(default_factory=list)
    audio: list[AudioPart] = field(default_factory=list)

    def visual_events(self, fps: int) -> list[dict]:
        # Subtitle words and audio identity must not invalidate an unchanged visual timeline.
        return [
            {
                "frame": round(c.start * fps),
                "end_frame": round(c.end * fps),
                "target": c.target,
                "action": c.action,
            }
            for c in self.cues
        ]


def resolve_timing(
    segment: SegmentBase,
    fps: int,
    asset: Callable[[str], tuple[Path, str, float]],
) -> Timing:
    frames = round(segment.duration * fps)
    result = Timing(duration=frames / fps, frames=frames)
    narration = segment.narration
    if segment.audio_asset_id:
        path, digest, duration = asset(segment.audio_asset_id)
        # Preserve the legacy tolerance; V2 narration has the stricter clock below.
        if duration > segment.duration + 0.1:
            raise RenderError("audio_longer_than_segment")
        result.audio.append(AudioPart(path, digest, 0, min(duration, result.duration)))
    elif isinstance(narration, TimedNarration):
        path, digest, duration = asset(narration.audio_asset_id)
        if duration > result.duration + 1 / 48000:
            raise RenderError("audio_longer_than_segment")
        if any(c.end > duration + 1 / 48000 for c in narration.cues):
            raise RenderError("cue_outside_audio")
        result.audio.append(AudioPart(path, digest, 0, duration))
        result.cues = narration.cues
    elif isinstance(narration, ClipNarration):
        cursor = 0.0
        for utterance in narration.utterances:
            path, digest, duration = asset(utterance.audio_asset_id)
            end = cursor + duration
            if end > result.duration + 1 / 48000:
                raise RenderError("audio_longer_than_segment")
            result.cues.append(
                Cue(
                    start=cursor,
                    end=min(end, 60),
                    target=utterance.target,
                    action=utterance.action,
                    text=utterance.text,
                )
            )
            result.audio.append(AudioPart(path, digest, cursor, duration))
            cursor = end + utterance.gap_after
        if cursor > result.duration + 1 / 48000:
            raise RenderError("audio_longer_than_segment")
    previous_end = 0
    for cue in result.cues:
        start, end = round(cue.start * fps), round(cue.end * fps)
        if start < previous_end or end <= start or end > frames:
            raise RenderError("cue_shorter_than_frame_or_out_of_bounds")
        previous_end = end
    return result


def subtitle_entries(timings: list[Timing]) -> list[dict]:
    offset, entries = 0.0, []
    for timing in timings:
        entries.extend(
            {"start": offset + cue.start, "end": offset + cue.end, "text": cue.text}
            for cue in timing.cues
        )
        offset += timing.duration
    return entries


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02},{milliseconds:03}"


def srt(entries: list[dict]) -> str:
    # Escape markup-like input: SRT viewers should display literal text, not interpret tags.
    import html

    return "\n".join(
        f"{i}\n{_timestamp(c['start'])} --> {_timestamp(c['end'])}\n"
        f"{html.escape(c['text']).replace(chr(13), '').replace(chr(10), ' ')}\n"
        for i, c in enumerate(entries, 1)
    )
