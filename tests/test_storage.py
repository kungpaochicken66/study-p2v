import json

import pytest

from study_p2v.errors import RenderError
from study_p2v.media import sha256
from study_p2v.storage import DiskStorage


def test_publication_reads_back_exact_destination_and_rejects_corruption(tmp_path):
    storage = DiskStorage(tmp_path / "data")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"some opaque media bytes")
    meta = {"sha256": sha256(source), "size_bytes": source.stat().st_size}
    receipt = storage.publish("one", "job", source, meta)
    target = storage.verify("one", "job", receipt)
    assert target != source and target.read_bytes() == source.read_bytes()
    with pytest.raises(RenderError):
        storage.verify("two", "job", receipt)
    target.write_bytes(b"corrupt")
    with pytest.raises(RenderError, match="artifact_verification_failed"):
        storage.verify("one", "job", receipt)


def test_wrong_destination_receipt_never_succeeds(tmp_path):
    storage = DiskStorage(tmp_path)
    with pytest.raises(RenderError):
        storage.verify("a", "job", {"namespace": "b", "job_id": "job", "url": "preview"})


def test_cache_is_integrity_checked_and_namespace_isolated(tmp_path):
    storage = DiskStorage(tmp_path / "data")
    source = tmp_path / "source"
    source.write_bytes(b"cached bytes")
    meta = {"sha256": sha256(source), "size_bytes": source.stat().st_size}
    with storage.cache_lock("a", "key", lambda: False, 1) as folder:
        storage.cache_put(folder, source, "key", meta)
        assert storage.cache_get(folder, "key").read_bytes() == b"cached bytes"
        assert storage.cache_get(folder, "different") is None
        (folder / "video.mp4").write_bytes(b"changed")
        assert storage.cache_get(folder, "key") is None
    with storage.cache_lock("b", "key", lambda: False, 1) as folder:
        assert storage.cache_get(folder, "key") is None


def test_bad_manifest_cannot_become_a_preview_fallback(tmp_path):
    storage = DiskStorage(tmp_path)
    folder = storage.artifact_dir("a", "job")
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"url": "https://temporary.invalid"}))
    with pytest.raises(RenderError):
        storage.verify("a", "job", {"url": "https://temporary.invalid"})
