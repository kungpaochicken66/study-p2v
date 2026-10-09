from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

from .config import Settings
from .errors import RenderError
from .models import OutputProfile
from .process import CancelCheck, run


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def probe(
    path: Path, settings: Settings, cancel: CancelCheck = lambda: False, timeout: float = 15
) -> dict:
    data = run(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov,wav,mp3,flac,ogg,aac,matroska,webm",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,pix_fmt,"
            "sample_rate,channels,profile,level,time_base,nb_frames,duration,start_time,extradata_hash",
            "-show_data_hash",
            "sha256",
            "-of",
            "json",
            str(path),
        ],
        cwd=path.parent,
        timeout=timeout,
        cancel=cancel,
        capture=True,
        error_code="media_probe_failed",
    )
    try:
        info = json.loads(data)
        duration = float(info["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return {"duration": duration, "streams": info.get("streams", [])}
    except (ValueError, KeyError, TypeError):
        raise RenderError("invalid_media_metadata") from None


def validate_video(
    path: Path,
    settings: Settings,
    profile: OutputProfile,
    duration: float,
    cancel: CancelCheck = lambda: False,
    timeout: float = 15,
) -> dict:
    if not path.is_file() or path.stat().st_size < 100:
        raise RenderError("artifact_missing")
    if path.stat().st_size > settings.max_output_bytes:
        raise RenderError("artifact_too_large")
    info = probe(path, settings, cancel, timeout)
    videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise RenderError("invalid_stream_count")
    v, a = videos[0], audios[0]
    try:
        fps = float(Fraction(v["avg_frame_rate"]))
    except (ValueError, ZeroDivisionError, KeyError):
        raise RenderError("invalid_frame_rate") from None
    if (
        v.get("codec_name") != "h264"
        or v.get("pix_fmt") != "yuv420p"
        or v.get("width") != profile.width
        or v.get("height") != profile.height
        or abs(fps - profile.fps) > 0.01
        or a.get("codec_name") != "aac"
        or a.get("sample_rate") != "48000"
        or a.get("channels") != 2
    ):
        raise RenderError("media_profile_mismatch")
    try:
        if int(v["nb_frames"]) != round(duration * profile.fps):
            raise RenderError("media_frame_count_mismatch")
        audio_duration = float(a["duration"])
        if not math.isfinite(audio_duration) or abs(audio_duration - duration) > 0.05:
            raise RenderError("audio_duration_mismatch")
    except (KeyError, ValueError, TypeError):
        raise RenderError("invalid_media_metadata") from None
    if abs(info["duration"] - duration) > max(0.1, 1 / profile.fps + 0.03):
        raise RenderError("media_duration_mismatch")
    return {
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "duration": info["duration"],
        "width": profile.width,
        "height": profile.height,
        "fps": profile.fps,
        "video_codec": "h264",
        "audio_codec": "aac",
    }


def validate_visual(path, settings, profile, frames, cancel=lambda: False, timeout=15):
    """A visual cache entry has exactly one silent, frame-counted H.264 stream."""
    info = probe(path, settings, cancel, timeout)
    if len(info["streams"]) != 1:
        raise RenderError("invalid_visual_streams")
    v = info["streams"][0]
    try:
        fps = float(Fraction(v["avg_frame_rate"]))
        count = int(v["nb_frames"])
    except (KeyError, ValueError, ZeroDivisionError):
        raise RenderError("invalid_visual_metadata") from None
    if (
        v.get("codec_name") != "h264"
        or v.get("pix_fmt") != "yuv420p"
        or v.get("width") != profile.width
        or v.get("height") != profile.height
        or abs(fps - profile.fps) > 0.01
        or count != frames
    ):
        raise RenderError("visual_profile_mismatch")
    if path.stat().st_size > settings.max_output_bytes:
        raise RenderError("artifact_too_large")
    signature = {
        k: v.get(k)
        for k in (
            "codec_name",
            "profile",
            "level",
            "pix_fmt",
            "width",
            "height",
            "time_base",
            "extradata_hash",
        )
    }
    return {
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "duration": frames / profile.fps,
        "frames": frames,
        "signature": signature,
    }


def prepare_visual(source, output, frames, profile, settings, cancel, timeout):
    import shutil
    import time

    deadline = time.monotonic() + timeout

    def budget():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RenderError("deadline_exceeded")
        return remaining

    try:
        metadata = validate_visual(source, settings, profile, frames, cancel, min(budget(), 15))
        shutil.copyfile(source, output)
        return metadata, 0
    except RenderError as exc:
        if exc.code in {"cancelled", "deadline_exceeded", "artifact_too_large"}:
            raise
    duration = frames / profile.fps
    run(
        [
            settings.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-an",
            "-vf",
            f"scale={profile.width}:{profile.height},setsar=1,fps={profile.fps},"
            f"format=yuv420p,tpad=stop_mode=clone:stop_duration={duration}",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-threads",
            str(settings.ffmpeg_threads),
            "-filter_threads",
            "1",
            str(output),
        ],
        cwd=output.parent,
        timeout=budget(),
        cancel=cancel,
        error_code="normalize_failed",
    )
    return validate_visual(output, settings, profile, frames, cancel, min(budget(), 15)), 1


def concat_visuals(segments, metadata, output, settings, cancel, timeout):
    import shutil

    if not metadata or any(m["signature"] != metadata[0]["signature"] for m in metadata):
        raise RenderError("incompatible_visual_streams")
    lines = []
    for i, (source, meta) in enumerate(zip(segments, metadata, strict=True)):
        target = output.parent / f"visual-{i:03}.mp4"
        shutil.copyfile(source, target)
        lines.append(f"file '{target.name}'\nduration {meta['duration']:.9f}\n")
    listing = output.parent / "visuals.txt"
    listing.write_text("".join(lines))
    run(
        [
            settings.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
        cwd=output.parent,
        timeout=timeout,
        cancel=cancel,
        error_code="concat_failed",
    )


def assemble_audio(parts, duration, output, settings, cancel, timeout):
    """Decode each unique input once; place PCM by sample offset, then encode AAC only at mux."""
    import time
    import wave

    end = time.monotonic() + timeout
    decoded = {}
    longest = {}
    for part in parts:
        longest[part.sha256] = max(longest.get(part.sha256, 0), part.duration)

    def budget():
        if cancel():
            raise RenderError("cancelled")
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RenderError("deadline_exceeded")
        return remaining

    def silence(writer, count):
        while count > 0:
            budget()
            n = min(count, 48000)
            writer.writeframesraw(b"\0" * (n * 4))
            count -= n

    with wave.open(str(output), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48000)
        cursor = 0
        for part in parts:
            start = round(part.start * 48000)
            # Quantize absolute boundaries, not each length independently: 44.1kHz clips
            # otherwise accumulate a one-sample rounding overlap at 48kHz.
            count = round((part.start + part.duration) * 48000) - start
            if start < cursor:
                raise RenderError("audio_overlap")
            silence(target, start - cursor)
            key = part.sha256
            if key not in decoded:
                path = output.parent / f"audio-{len(decoded):03}.pcm"
                run(
                    [
                        settings.ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-y",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-format_whitelist",
                        "mov,wav,mp3,flac,ogg,aac,matroska,webm",
                        "-i",
                        str(part.path),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-t",
                        str(longest[key]),
                        "-ac",
                        "2",
                        "-ar",
                        "48000",
                        "-c:a",
                        "pcm_s16le",
                        "-f",
                        "s16le",
                        str(path),
                    ],
                    cwd=output.parent,
                    timeout=budget(),
                    cancel=cancel,
                    error_code="audio_decode_failed",
                )
                decoded[key] = path
            remaining = count * 4
            with decoded[key].open("rb") as source:
                while remaining:
                    budget()
                    block = source.read(min(192000, remaining))
                    if not block:
                        silence(target, remaining // 4)
                        break
                    target.writeframesraw(block)
                    remaining -= len(block)
            cursor = start + count
        total = round(duration * 48000)
        if cursor > total:
            raise RenderError("audio_longer_than_segment")
        silence(target, total - cursor)
    return len(decoded)


def write_ass(entries, output, profile, font):
    import unicodedata

    if any(char in font for char in ",\r\n"):
        raise RenderError("invalid_subtitle_font")

    def lines(text, size):
        # Conservative glyph widths reserve a bottom strip of two lines.
        limit = int(profile.width * 0.88 / (size * 0.6))
        result, line, width = [], "", 0
        for char in text.replace("\r", "").replace("\n", " "):
            n = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
            if width + n > limit:
                result.append(line)
                line, width = "", 0
            line += char
            width += n
        if line:
            result.append(line)
        return result

    def stamp(seconds):
        ticks = round(seconds * 100)
        h, ticks = divmod(ticks, 360000)
        m, ticks = divmod(ticks, 6000)
        s, ticks = divmod(ticks, 100)
        return f"{h}:{m:02}:{s:02}.{ticks:02}"

    size = profile.height * 0.036
    while size > profile.height * 0.025 and any(len(lines(c["text"], size)) > 2 for c in entries):
        size -= 1
    if any(len(lines(c["text"], size)) > 2 for c in entries):
        raise RenderError("subtitle_overflow")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {profile.width}
PlayResY: {profile.height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size:.2f},&H00FFFFFF,&H00FFFFFF,&H00201810,&H00201810,0,0,0,0,100,100,0,0,3,1,0,2,{int(profile.width * 0.06)},{int(profile.width * 0.06)},{int(profile.height * 0.025)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for cue in entries:
        # Neutralize ASS control syntax in user text; never interpolate it into filter expressions.
        # Backslashes from input are literal full-width glyphs; only our own line breaks survive.
        text = r"\N".join(
            line.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            for line in lines(cue["text"], size)
        )
        rows.append(
            f"Dialogue: 0,{stamp(cue['start'])},{stamp(cue['end'])},Default,,0,0,0,,{text}\n"
        )
    output.write_text(header + "".join(rows))


def mux(visual, audio, output, duration, settings, cancel, timeout, burn=False):
    args = [
        settings.ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(visual),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if burn:
        args += [
            "-vf",
            "ass=captions.ass",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-threads",
            str(settings.ffmpeg_threads),
            "-filter_threads",
            "1",
            "-pix_fmt",
            "yuv420p",
        ]
    else:
        args += ["-c:v", "copy"]
    args += [
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        str(duration),
        "-movflags",
        "+faststart",
        str(output),
    ]
    run(args, cwd=output.parent, timeout=timeout, cancel=cancel, error_code="mux_failed")
