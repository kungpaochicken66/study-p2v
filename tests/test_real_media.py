"""Opt-in actual Manim/FFmpeg API acceptance. No network or external business services."""

import io
import os
import time
import wave

import pytest
from fastapi.testclient import TestClient

from study_p2v.api import create_app
from study_p2v.config import Settings
from study_p2v.errors import RenderError
from study_p2v.media import probe, sha256

pytestmark = pytest.mark.skipif(os.getenv("P2V_REAL_TESTS") != "1", reason="opt-in real media")


def wav_bytes(seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * int(8000 * seconds))
    return output.getvalue()


def test_actual_audio_api_render_cache_and_rejection(tmp_path):
    key = "local-acceptance-token-" * 2
    other = "other-acceptance-token-" * 2
    settings = Settings(
        data_dir=tmp_path,
        font=os.environ.get("P2V_FONT", "DejaVu Sans"),
        api_keys={key: "a", other: "b"},
    )
    headers = {"Authorization": f"Bearer {key}"}
    with TestClient(create_app(settings)) as client:
        asset = client.post("/v1/assets", content=wav_bytes(1), headers=headers)
        assert asset.status_code == 201, asset.text
        spec = {
            "output": {"width": 640, "height": 360, "fps": 15},
            "segments": [
                {
                    "template": "title",
                    "title": "Narration acceptance",
                    "duration": 2,
                    "audio_asset_id": asset.json()["id"],
                }
            ],
        }
        assert (
            client.post(
                "/v1/jobs", json=spec, headers={"Authorization": f"Bearer {other}"}
            ).status_code
            == 404
        )

        def render(request):
            response = client.post("/v1/jobs", json=request, headers=headers)
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job = client.get(f"/v1/jobs/{job_id}", headers=headers).json()
                if job["state"] in {"succeeded", "failed", "cancelled"}:
                    return job
                time.sleep(0.1)
            pytest.fail("real render deadline")

        first = render(spec)
        assert first["state"] == "succeeded", first
        assert first["metrics"]["rendered_segments"] == 1
        result = client.get(f"/v1/jobs/{first['id']}/artifact", headers=headers)
        assert result.status_code == 200
        downloaded = tmp_path / "download.mp4"
        downloaded.write_bytes(result.content)
        assert sha256(downloaded) == first["result"]["sha256"]
        info = probe(downloaded, settings)
        assert abs(info["duration"] - 2) < 0.3
        assert {s["codec_name"] for s in info["streams"]} == {"h264", "aac"}
        second = render(spec)
        assert second["state"] == "succeeded"
        assert second["metrics"]["cache_hits"] == 1
        assert second["result"]["sha256"] == first["result"]["sha256"]
        long_asset = client.post("/v1/assets", content=wav_bytes(3), headers=headers)
        spec["segments"][0]["audio_asset_id"] = long_asset.json()["id"]
        failed = render(spec)
        assert failed["state"] == "failed" and failed["error_code"] == "audio_longer_than_segment"
        assert client.get(f"/v1/jobs/{failed['id']}/artifact", headers=headers).status_code == 409
        assert (
            client.post("/v1/assets", content=b"invalid audio", headers=headers).status_code == 422
        )


def test_playlist_demuxer_is_rejected(tmp_path):
    # Even a local-file playlist is outside the accepted media container contract.
    wav = tmp_path / "audio.wav"
    wav.write_bytes(wav_bytes(1))
    playlist = tmp_path / "input"
    playlist.write_text("ffconcat version 1.0\nfile 'audio.wav'\n")
    with pytest.raises(RenderError, match="media_probe_failed"):
        probe(playlist, Settings(data_dir=tmp_path))
