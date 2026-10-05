from pathlib import Path

from internship_pipeline.queue import Queue
from internship_pipeline.storage import Store, enqueue


def queue_with_task(path: Path, max_attempts: int = 5) -> Queue:
    store = Store(path)
    with store.transaction() as connection:
        enqueue(connection, "resume", "one", {"job_id": "one"}, 100)
    return Queue(store, lease_seconds=30, max_attempts=max_attempts)


def test_expired_work_is_reclaimed_and_old_worker_cannot_finish(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite")
    first = queue.claim(["resume"], now=100)
    assert first is not None
    assert queue.claim(["resume"], now=101) is None
    restarted = Queue(Store(queue.store.path), lease_seconds=30)
    second = restarted.claim(["resume"], now=131)
    assert second is not None
    assert second.id == first.id and second.token != first.token
    assert not queue.complete(first)
    assert restarted.complete(second)


def test_retries_are_durable_bounded_and_explicitly_reset(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite", max_attempts=2)
    first = queue.claim(["resume"], now=100)
    assert first is not None
    queue.fail(first, "Timeout", now=100)
    assert queue.claim(["resume"], now=101) is None
    second = queue.claim(["resume"], now=105)
    assert second is not None
    queue.fail(second, "Timeout", now=105)
    assert queue.claim(["resume"], now=1000) is None
    assert queue.store.health()["tasks"] == {"failed": 1}
    assert queue.retry_failed() == 1


def test_idempotency_keys_do_not_create_duplicate_work(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite")
    with queue.store.transaction() as connection:
        enqueue(connection, "resume", "one", {"job_id": "one"}, 100)
    assert queue.store.health()["tasks"] == {"pending": 1}


def test_provider_reservations_survive_restart(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    assert store.reserve_provider("ashby", 100, spacing=2)
    assert not Store(store.path).reserve_provider("ashby", 101, spacing=2)
    store.cooldown_provider("ashby", 150)
    assert not store.reserve_provider("ashby", 149)
    assert store.reserve_provider("ashby", 150)


def test_strong_resume_priority_yields_to_aged_work(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    with store.transaction() as connection:
        enqueue(connection, "resume", "older", {"match": {"fit": "possible"}}, 100)
        enqueue(connection, "resume", "strong", {"match": {"fit": "strong"}}, 200)
    queue = Queue(store)
    assert queue.claim(["resume"], now=250).key == "strong"
    with store.transaction() as connection:
        enqueue(connection, "resume", "another-strong", {"match": {"fit": "strong"}}, 450)
    assert queue.claim(["resume"], now=500).key == "older"
