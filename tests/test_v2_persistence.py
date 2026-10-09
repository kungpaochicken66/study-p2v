import hashlib
import json

from study_p2v.models import Storyboard, canonical
from study_p2v.store import Store


def test_old_persisted_v1_idempotency_key_survives_new_optional_fields(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    old_payload = {
        "schema_version": 1,
        "theme": "midnight",
        "output": {"width": 1280, "height": 720, "fps": 24},
        "segments": [
            {
                "template": "title",
                "title": "Legacy job",
                "duration": 4.0,
                "audio_asset_id": None,
                "subtitle": "Structured ideas, rendered clearly",
            }
        ],
    }
    current = Storyboard.model_validate(old_payload)
    row, _ = store.submit("demo", current, "persisted-key", 10)
    payload = canonical(old_payload)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with store.connect() as connection:
        connection.execute(
            "UPDATE jobs SET request=?,request_hash=? WHERE id=?", (payload, digest, row["id"])
        )
    same, created = store.submit("demo", current, "persisted-key", 10)
    assert not created and same["id"] == row["id"]
    assert json.loads(same["request"]) == old_payload
