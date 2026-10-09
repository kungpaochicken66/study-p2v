import time

import pytest

from study_p2v.config import Settings
from study_p2v.engine import Engine
from study_p2v.errors import RenderError
from study_p2v.models import Storyboard


class MissingArtifactRenderer:
    def __init__(self, *args):
        pass

    def prepare(self):
        pass

    def render(self, job, cancel):
        return {"sha256": "0" * 64, "size_bytes": 42, "preview_url": "temporary"}, {}


def test_engine_requires_destination_and_exclusive_ownership(tmp_path):
    settings = Settings(data_dir=tmp_path, workers=1)
    first = Engine(settings, MissingArtifactRenderer)
    second = Engine(settings, MissingArtifactRenderer)
    first.start()
    try:
        with pytest.raises(RenderError, match="another_engine_owns_data_dir"):
            second.start()
        row, _ = first.store.submit(
            "a",
            Storyboard.model_validate({"segments": [{"template": "title", "title": "test"}]}),
            None,
            100,
        )
        first.wakeup.set()
        for _ in range(100):
            result = first.store.get("a", row["id"])
            if result["state"] == "failed":
                break
            time.sleep(0.02)
        assert result["state"] == "failed"
        assert result["result"] is None
    finally:
        first.close()
    second.start()
    second.close()
