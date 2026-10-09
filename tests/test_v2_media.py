"""Real pixels, decoded audio, cache effects, and persisted artifacts (opt-in)."""

import copy
import io
import json
import os
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from study_p2v.api import create_app
from study_p2v.config import Settings
from study_p2v.media import sha256
from study_p2v.process import run

pytestmark = pytest.mark.skipif(os.getenv("P2V_REAL_TESTS") != "1", reason="opt-in real media")
KEY = "v2-local-test-token-" * 3
HEADERS = {"Authorization": f"Bearer {KEY}"}


def tone(seconds, frequency=440, pulse=False):
    rate = 48000
    t = np.arange(round(rate * seconds)) / rate
    values = np.sin(2 * np.pi * frequency * t) * 0.3
    if pulse:
        values[(t < 0.2) | (t >= 0.4)] = 0
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes((values * 32767).astype("<i2").tobytes())
    return output.getvalue()


@pytest.fixture
def real_client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        font=os.getenv("P2V_FONT", "DejaVu Sans"),
        workers=2,
        per_namespace=2,
        api_keys={KEY: "demo", "other-token-" * 4: "other"},
    )
    with TestClient(create_app(settings)) as client:
        yield client, settings


def upload(client, body):
    response = client.post("/v1/assets", content=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def wait(client, job_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}", headers=HEADERS)
        job = response.json()
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    pytest.fail("real render deadline")


def render(client, spec):
    response = client.post("/v1/jobs", json=spec, headers=HEADERS)
    assert response.status_code == 202, response.text
    job = wait(client, response.json()["id"])
    assert job["state"] == "succeeded", job.get("error_code")
    return job


def narrated_spec(asset):
    return {
        "schema_version": 2,
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [
            {
                "template": "bullets",
                "title": "Audio and visuals in sync",
                "items": ["Ask a question", "Show evidence \u2014 verified"],
                "duration": 4,
                "narration": {
                    "mode": "timed",
                    "audio_asset_id": asset,
                    "cues": [
                        {"start": 0, "end": 0.8, "target": "item-1", "text": "Ask a question"},
                        {
                            "start": 1,
                            "end": 2,
                            "target": "item-2",
                            "text": "Show evidence \u2014 verified",
                        },
                        {
                            "start": 2,
                            "end": 3,
                            "target": "item-1",
                            "action": "highlight",
                            "text": "Emphasize again",
                        },
                        {
                            "start": 3,
                            "end": 4,
                            "target": "item-2",
                            "action": "exit",
                            "text": "Finish this item",
                        },
                    ],
                },
            },
            {
                "template": "definition",
                "title": "Verify results",
                "term": "Independent readback",
                "body": "Read the saved file and verify its contents",
                "duration": 2,
            },
        ],
    }


def test_audio_only_change_partial_edit_cache_corruption_and_subtitles(real_client):
    client, settings = real_client
    asset_a, asset_b = upload(client, tone(4)), upload(client, tone(4, 660))
    spec = narrated_spec(asset_a)
    denied = client.post(
        "/v1/jobs", json=spec, headers={"Authorization": "Bearer " + "other-token-" * 4}
    )
    assert denied.status_code == 404
    first = render(client, spec)
    assert first["metrics"]["rendered_segments"] == 2
    assert first["metrics"]["video_reencodes"] == 0
    assert first["metrics"]["audio_encodes"] == 1
    repeat = render(client, spec)
    assert repeat["metrics"]["composition_cache_hits"] == 1
    assert repeat["metrics"]["rendered_segments"] == 0
    assert repeat["metrics"]["audio_encodes"] == 0
    assert repeat["result"]["sha256"] == first["result"]["sha256"]
    changed = copy.deepcopy(spec)
    changed["segments"][0]["narration"]["audio_asset_id"] = asset_b
    audio_only = render(client, changed)
    assert audio_only["metrics"]["rendered_segments"] == 0
    assert audio_only["metrics"]["visual_cache_hits"] == 2
    assert audio_only["metrics"]["video_reencodes"] == 0
    assert audio_only["result"]["sha256"] != first["result"]["sha256"]
    changed["segments"][1]["body"] = "Edit only the second segment"
    partial = render(client, changed)
    assert partial["metrics"]["rendered_segments"] == 1
    assert partial["metrics"]["visual_cache_hits"] == 1
    changed["segments"][0]["narration"]["cues"][1]["start"] = 1.2
    retimed = render(client, changed)
    assert retimed["metrics"]["rendered_segments"] == 1
    assert retimed["metrics"]["visual_cache_hits"] == 1

    sidecar_spec = dict(spec, subtitle_mode="sidecar")
    sidecar = render(client, sidecar_spec)
    assert sidecar["metrics"]["composition_cache_hits"] == 1
    response = client.get(f"/v1/jobs/{sidecar['id']}/subtitles", headers=HEADERS)
    assert response.status_code == 200
    assert "00:00:01,000 --> 00:00:02,000" in response.text
    assert "Show evidence \u2014 verified" in response.text
    assert (
        client.get(
            f"/v1/jobs/{sidecar['id']}/subtitles",
            headers={"Authorization": "Bearer " + "other-token-" * 4},
        ).status_code
        == 404
    )
    burned = render(client, dict(spec, subtitle_mode="burn"))
    assert burned["metrics"]["rendered_segments"] == 0
    assert burned["metrics"]["visual_cache_hits"] == 2
    assert burned["metrics"]["video_reencodes"] == 1
    assert burned["result"]["sha256"] != first["result"]["sha256"]

    # Force a new composition, with corrupt visual entries: each must be rebuilt, never reused.
    for manifest in (settings.data_dir / "namespaces/demo/cache").glob("*/manifest.json"):
        data = json.loads(manifest.read_text())
        if data.get("layer") == "visual":
            manifest.with_name("video.mp4").write_bytes(b"corrupt")
    third_asset = upload(client, tone(4, 880))
    changed = narrated_spec(third_asset)
    rebuilt = render(client, changed)
    assert rebuilt["metrics"]["rendered_segments"] == 2
    assert rebuilt["metrics"]["visual_cache_hits"] == 0
    for manifest in (settings.data_dir / "namespaces/demo/cache").glob("*/manifest.json"):
        data = json.loads(manifest.read_text())
        if data.get("layer") == "composition":
            assert sha256(manifest.with_name("video.mp4")) == data["sha256"]

    attachment = settings.data_dir / "namespaces/demo/artifacts" / sidecar["id"] / "subtitles.srt"
    attachment.write_text("tampered")
    assert client.get(f"/v1/jobs/{sidecar['id']}/subtitles", headers=HEADERS).status_code == 409
    assert client.get(f"/v1/jobs/{sidecar['id']}/artifact", headers=HEADERS).status_code == 409


def test_24_segments_have_no_accumulated_audio_drift_and_reveal_on_frame(real_client):
    client, settings = real_client
    asset = upload(client, tone(1, pulse=True))
    segment = {
        "template": "title",
        "title": "Timeline acceptance",
        "subtitle": "The pulse matches this line",
        "duration": 1.07,
        "narration": {
            "mode": "timed",
            "audio_asset_id": asset,
            "cues": [
                {"start": 0.2, "end": 0.7, "target": "subtitle", "text": "Synchronized pulse"}
            ],
        },
    }
    spec = {
        "schema_version": 2,
        "subtitle_mode": "sidecar",
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [segment] * 24,
    }
    job = render(client, spec)
    assert job["metrics"]["rendered_segments"] == 1
    assert job["metrics"]["visual_cache_hits"] == 23
    assert job["metrics"]["audio_decodes"] == 1
    assert job["metrics"]["audio_encodes"] == 1
    video = settings.data_dir / "namespaces/demo/artifacts" / job["id"] / "video.mp4"
    decoded = settings.data_dir / "decoded.f32"
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            str(decoded),
        ],
        cwd=settings.data_dir,
        timeout=30,
    )
    audio = np.fromfile(decoded, dtype="<f4")
    # Independent energy detection in the encoded/decoded final stream, not timing metadata.
    windows = np.sqrt(np.mean(audio[: len(audio) // 480 * 480].reshape(-1, 480) ** 2, axis=1))
    starts = np.flatnonzero((windows > 0.08) & np.r_[True, windows[:-1] <= 0.08]) / 100
    expected = np.arange(24) * (16 / 15) + 0.2
    assert len(starts) == 24
    assert np.max(np.abs(starts - expected)) < 0.03
    assert abs(job["result"]["duration"] - 25.6) < 0.05
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
            r"select=eq(n\,2)+eq(n\,3)",
            "-vsync",
            "0",
            "-frames:v",
            "2",
            str(settings.data_dir / "reveal-%02d.png"),
        ],
        cwd=settings.data_dir,
        timeout=30,
    )
    before = np.asarray(Image.open(settings.data_dir / "reveal-01.png").convert("RGB"))[
        215:265, 80:560
    ]
    after = np.asarray(Image.open(settings.data_dir / "reveal-02.png").convert("RGB"))[
        215:265, 80:560
    ]
    assert np.count_nonzero(before.max(axis=2) > 100) == 0
    assert np.count_nonzero(after.max(axis=2) > 100) > 50
    captions = client.get(f"/v1/jobs/{job['id']}/subtitles", headers=HEADERS).text
    assert "00:00:24,733 --> 00:00:25,233" in captions


def test_concurrent_identical_jobs_render_once(real_client):
    client, _ = real_client
    spec = {
        "schema_version": 2,
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [
            {
                "template": "cycle",
                "title": "Concurrent reuse",
                "steps": ["Observe", "Act"],
                "duration": 1,
            }
        ],
    }
    ids = [client.post("/v1/jobs", json=spec, headers=HEADERS).json()["id"] for _ in range(2)]
    jobs = [wait(client, id_) for id_ in ids]
    assert all(j["state"] == "succeeded" for j in jobs), [j["error_code"] for j in jobs]
    assert sum(j["metrics"]["rendered_segments"] for j in jobs) == 1
    assert sum(j["metrics"]["composition_cache_hits"] for j in jobs) == 1


def test_sentence_clips_use_probed_durations_and_keep_gaps(real_client):
    client, settings = real_client
    a = upload(client, tone(0.6, pulse=True))
    b = upload(client, tone(0.8, 660, pulse=True))
    spec = {
        "schema_version": 2,
        "subtitle_mode": "sidecar",
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [
            {
                "template": "checklist",
                "title": "Sentence audio clips",
                "items": ["First sentence", "Second sentence"],
                "duration": 2,
                "narration": {
                    "mode": "clips",
                    "utterances": [
                        {
                            "audio_asset_id": a,
                            "target": "item-1",
                            "text": "First sentence",
                            "gap_after": 0.2,
                        },
                        {"audio_asset_id": b, "target": "item-2", "text": "Second sentence"},
                    ],
                },
            }
        ],
    }
    job = render(client, spec)
    assert job["result"]["timeline"][0]["events"][1]["frame"] == 12
    video = settings.data_dir / "namespaces/demo/artifacts" / job["id"] / "video.mp4"
    decoded = settings.data_dir / "clips.f32"
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            str(decoded),
        ],
        cwd=settings.data_dir,
        timeout=30,
    )
    audio = np.fromfile(decoded, dtype="<f4")
    windows = np.sqrt(np.mean(audio[: len(audio) // 480 * 480].reshape(-1, 480) ** 2, axis=1))
    starts = np.flatnonzero((windows > 0.08) & np.r_[True, windows[:-1] <= 0.08]) / 100
    assert starts == pytest.approx([0.2, 1.0], abs=0.02)
    text = client.get(f"/v1/jobs/{job['id']}/subtitles", headers=HEADERS).text
    assert "00:00:00,800 --> 00:00:01,600" in text


def test_dense_text_fails_explicitly_without_publishing(real_client):
    client, settings = real_client
    # Six maximum-length runs of wide Latin letters exercise wrapping and overflow.
    spec = {
        "schema_version": 2,
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [
            {"template": "bullets", "title": "Text layout limit", "items": ["W" * 140] * 6}
        ],
    }
    response = client.post("/v1/jobs", json=spec, headers=HEADERS)
    job = wait(client, response.json()["id"])
    assert job["state"] == "failed" and job["error_code"] == "text_overflow"
    assert client.get(f"/v1/jobs/{job['id']}/artifact", headers=HEADERS).status_code == 409
    assert not (settings.data_dir / "namespaces/demo/artifacts" / job["id"]).exists()
    assert not list((settings.data_dir / "namespaces/demo/scratch").glob("*"))


def test_32_short_44100hz_clips_do_not_create_rounding_overlaps(real_client):
    client, settings = real_client
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        samples = (np.sin(np.arange(5400) * 2 * np.pi * 440 / 44100) * 6000).astype("<i2")
        wav.writeframes(samples.tobytes())
    asset = upload(client, output.getvalue())
    utterance = {"audio_asset_id": asset, "target": "title", "text": "Short audio"}
    spec = {
        "schema_version": 2,
        "subtitle_mode": "sidecar",
        "output": {"width": 640, "height": 360, "fps": 30},
        "segments": [
            {
                "template": "title",
                "title": "Sample rounding acceptance",
                "subtitle": "Thirty-two consecutive clips",
                "duration": 4,
                "narration": {"mode": "clips", "utterances": [utterance] * 32},
            }
        ],
    }
    job = render(client, spec)
    assert job["metrics"]["audio_decodes"] == 1
    assert len(job["result"]["timeline"][0]["events"]) == 32
    assert abs(job["result"]["duration"] - 4) < 0.05
    video = settings.data_dir / "namespaces/demo/artifacts" / job["id"] / "video.mp4"
    decoded = settings.data_dir / "short-clips.f32"
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            str(decoded),
        ],
        cwd=settings.data_dir,
        timeout=30,
    )
    audio = np.fromfile(decoded, dtype="<f4")
    # Every sentence remains audible, including the last; the remainder is silence.
    for i in range(32):
        start = round((i * 5400 / 44100 + 0.03) * 48000)
        assert np.sqrt(np.mean(audio[start : start + 960] ** 2)) > 0.05
    assert np.sqrt(np.mean(audio[round(3.97 * 48000) : round(3.99 * 48000)] ** 2)) < 0.005


def test_math_cannot_shrink_arbitrarily_below_readable_size(real_client):
    client, _ = real_client
    expr = {"kind": "row", "parts": [{"kind": "symbol", "value": "1234567890" * 4}] * 16}
    spec = {
        "schema_version": 2,
        "output": {"width": 640, "height": 360, "fps": 15},
        "segments": [{"template": "equation", "title": "Math layout limit", "math_steps": [expr]}],
    }
    response = client.post("/v1/jobs", json=spec, headers=HEADERS)
    job = wait(client, response.json()["id"])
    assert job["state"] == "failed" and job["error_code"] == "math_overflow"
    assert client.get(f"/v1/jobs/{job['id']}/artifact", headers=HEADERS).status_code == 409
