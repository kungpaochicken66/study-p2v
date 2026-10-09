import time

from fastapi.testclient import TestClient

from study_p2v.api import create_app
from study_p2v.config import Settings
from study_p2v.engine import Engine
from study_p2v.errors import RenderError
from study_p2v.media import sha256

KEY_A, KEY_B = "test-a-" * 5, "test-b-" * 5
AUTH_A, AUTH_B = {"Authorization": f"Bearer {KEY_A}"}, {"Authorization": f"Bearer {KEY_B}"}
SPEC = {"segments": [{"template": "title", "title": "test"}]}


class FakeRenderer:
    def __init__(self, settings, storage, store):
        self.storage = storage
        self.settings = settings

    def prepare(self):
        pass

    def render(self, job, cancel):
        if '"title":"block"' in job["request"]:
            while not cancel():
                time.sleep(0.01)
            raise RenderError("cancelled")
        p = self.storage.namespace_dir(job["namespace"]) / (job["id"] + ".fake")
        p.write_bytes(b"fake-media-for-control-plane-tests")
        receipt = self.storage.publish(
            job["namespace"], job["id"], p, {"sha256": sha256(p), "size_bytes": p.stat().st_size}
        )
        p.unlink()
        return receipt, {"fake": True}


def client_for(tmp_path, **kwargs):
    s = Settings(data_dir=tmp_path, api_keys={KEY_A: "a", KEY_B: "b"}, **kwargs)
    return TestClient(create_app(s, Engine(s, FakeRenderer)))


def wait_done(client, job_id):
    for _ in range(100):
        data = client.get(f"/v1/jobs/{job_id}", headers=AUTH_A).json()
        if data["state"] in {"succeeded", "failed", "cancelled"}:
            return data
        time.sleep(0.02)
    raise AssertionError("job did not reach terminal state")


def test_auth_isolation_idempotency_and_verified_download(tmp_path):
    with client_for(tmp_path) as client:
        assert client.post("/v1/jobs", json=SPEC).status_code == 401
        h = dict(AUTH_A, **{"Idempotency-Key": "same"})
        first = client.post("/v1/jobs", json=SPEC, headers=h)
        assert first.status_code == 202, first.text
        job_id = first.json()["id"]
        assert client.post("/v1/jobs", json=SPEC, headers=h).json()["id"] == job_id
        different = {"segments": [{"template": "title", "title": "different"}]}
        assert client.post("/v1/jobs", json=different, headers=h).status_code == 409
        assert wait_done(client, job_id)["state"] == "succeeded"
        assert client.get(f"/v1/jobs/{job_id}", headers=AUTH_B).status_code == 404
        assert client.get(f"/v1/jobs/{job_id}/artifact", headers=AUTH_B).status_code == 404
        assert client.post(f"/v1/jobs/{job_id}/cancel", headers=AUTH_B).status_code == 404
        assert client.get(f"/v1/jobs/{job_id}/artifact", headers=AUTH_A).content.startswith(
            b"fake-media"
        )
        artifact = tmp_path / "namespaces/a/artifacts" / job_id / "video.mp4"
        artifact.write_bytes(b"tampered")
        assert client.get(f"/v1/jobs/{job_id}/artifact", headers=AUTH_A).status_code == 409


def test_cancel_has_no_download_and_retry_has_new_identity(tmp_path):
    with client_for(tmp_path) as client:
        response = client.post(
            "/v1/jobs", json={"segments": [{"template": "title", "title": "block"}]}, headers=AUTH_A
        )
        job_id = response.json()["id"]
        client.post(f"/v1/jobs/{job_id}/cancel", headers=AUTH_A)
        assert wait_done(client, job_id)["state"] == "cancelled"
        assert client.get(f"/v1/jobs/{job_id}/artifact", headers=AUTH_A).status_code == 409
        retry = client.post(f"/v1/jobs/{job_id}/retry", headers=AUTH_A)
        assert retry.status_code == 202 and retry.json()["id"] != job_id
        client.post(f"/v1/jobs/{retry.json()['id']}/cancel", headers=AUTH_A)


def test_invalid_input_does_not_echo_private_text_and_body_limit(tmp_path):
    with client_for(tmp_path, max_request_bytes=256) as client:
        result = client.post("/v1/jobs", json={"private": "sensitive-user-content"}, headers=AUTH_A)
        assert result.status_code == 422 and "sensitive-user-content" not in result.text
        assert client.post("/v1/jobs", content=b"x" * 257, headers=AUTH_A).status_code == 413
        assert client.get("/v1/templates", headers=AUTH_A).status_code == 200
        assert client.get("/health/ready").status_code == 200
