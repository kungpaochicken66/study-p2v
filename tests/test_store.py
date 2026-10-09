from concurrent.futures import ThreadPoolExecutor

import pytest

from study_p2v.errors import Conflict, QueueFull
from study_p2v.models import Storyboard
from study_p2v.store import Store


def spec(title="Hello"):
    return Storyboard(segments=[{"template": "title", "title": title}])


def test_idempotency_is_atomic_and_namespace_scoped(tmp_path):
    store = Store(tmp_path / "jobs.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: store.submit("one", spec(), "same", 10), range(12)))
    assert len({r[0]["id"] for r in rows}) == 1
    assert sum(created for _, created in rows) == 1
    with pytest.raises(Conflict):
        store.submit("one", spec("different"), "same", 10)
    other, _ = store.submit("two", spec(), "same", 10)
    assert other["id"] != rows[0][0]["id"]
    assert store.get("one", other["id"]) is None


def test_persisted_queue_fairness_and_capacity(tmp_path):
    store = Store(tmp_path / "jobs.db")
    a, _ = store.submit("a", spec(), None, 3)
    a2, _ = store.submit("a", spec(), None, 3)
    b, _ = store.submit("b", spec(), None, 3)
    with pytest.raises(QueueFull):
        store.submit("c", spec(), None, 3)
    assert store.claim(1)["id"] == a["id"]
    assert store.claim(1)["id"] == b["id"]  # a2 cannot monopolize all workers.
    assert store.claim(1) is None
    reopened = Store(tmp_path / "jobs.db")
    assert reopened.recover() == 2
    assert reopened.get("a", a["id"])["error_code"] == "interrupted"
    assert reopened.claim(1)["id"] == a2["id"]


def test_cancel_wins_against_success_commit(tmp_path):
    store = Store(tmp_path / "jobs.db")
    a, _ = store.submit("a", spec(), None, 10)
    store.claim(1)
    store.cancel("a", a["id"])
    assert not store.finish(a["id"], result={"url": "pretend-success"})
    row = store.get("a", a["id"])
    assert row["state"] == "cancelled" and row["result"] is None
    assert not store.finish(a["id"], result={"url": "late-result"})
    b, _ = store.submit("a", spec(), None, 10)
    store.cancel("a", b["id"])
    assert store.claim(1) is None
