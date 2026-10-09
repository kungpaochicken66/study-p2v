import pytest
from pydantic import ValidationError

from study_p2v.config import Settings
from study_p2v.errors import RenderError
from study_p2v.models import Storyboard
from study_p2v.storage import checked


def storyboard(**kwargs):
    return Storyboard.model_validate(
        {"segments": [{"template": "title", "title": "Example"}], **kwargs}
    )


def test_structured_contract_does_not_accept_code_paths_or_namespaces():
    for extra in [{"namespace": "other"}, {"python": "import os"}, {"output_path": "/etc/passwd"}]:
        with pytest.raises(ValidationError):
            storyboard(**extra)
    for template in ["python", "html", "https://host/file"]:
        with pytest.raises(ValidationError):
            storyboard(segments=[{"template": template, "title": "title"}])


def test_bounded_media_spec_and_no_nonfinite_values():
    for output in [
        {"width": 641, "height": 360},
        {"width": 3840, "height": 2160},
        {"width": 720, "height": 1280},
    ]:
        with pytest.raises(ValidationError):
            storyboard(output=output)
    with pytest.raises(ValidationError):
        storyboard(
            segments=[
                {
                    "template": "bars",
                    "title": "bad",
                    "points": [{"label": "x", "value": float("nan")}],
                }
            ]
        )
    with pytest.raises(ValidationError):
        storyboard(segments=[{"template": "title", "title": "t", "duration": 60}] * 11)


def test_storage_names_and_keys_are_not_paths(tmp_path):
    for name in ["../other", "/absolute", "a/b", "", ".", "a\\b"]:
        with pytest.raises(RenderError):
            checked(name)
    with pytest.raises(RenderError):
        Settings(data_dir=tmp_path, api_keys={"a" * 32: "../other"})
