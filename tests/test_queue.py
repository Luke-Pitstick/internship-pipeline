from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from internship_pipeline.queue import Queue
from internship_pipeline.storage import Store, enqueue


def queue_with_task(path: Path, max_attempts: int = 5) -> Queue:
    store = Store(path)
    with store.transaction() as connection:
        enqueue(connection, "tailored_resume", "one", {"job_id": "one"}, 100)
    return Queue(store, lease_seconds=30, max_attempts=max_attempts)


def test_expired_work_is_reclaimed_and_old_worker_cannot_finish(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite")
    first = queue.claim(["tailored_resume"], now=100)
    assert first is not None
    assert queue.claim(["tailored_resume"], now=101) is None
    restarted = Queue(Store(queue.store.path), lease_seconds=30)
    second = restarted.claim(["tailored_resume"], now=131)
    assert second is not None
    assert second.id == first.id and second.token != first.token
    assert not queue.complete(first)
    assert restarted.complete(second)


def test_retries_are_durable_bounded_and_explicitly_reset(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite", max_attempts=2)
    first = queue.claim(["tailored_resume"], now=100)
    assert first is not None
    queue.fail(first, "Timeout", now=100)
    assert queue.claim(["tailored_resume"], now=101) is None
    second = queue.claim(["tailored_resume"], now=105)
    assert second is not None
    queue.fail(second, "Timeout", now=105)
    assert queue.claim(["tailored_resume"], now=1000) is None
    assert queue.store.health()["tasks"] == {"failed": 1}
    assert queue.retry_failed() == 1


def test_idempotency_keys_do_not_create_duplicate_work(tmp_path: Path) -> None:
    queue = queue_with_task(tmp_path / "db.sqlite")
    with queue.store.transaction() as connection:
        enqueue(connection, "tailored_resume", "one", {"job_id": "one"}, 100)
    assert queue.store.health()["tasks"] == {"pending": 1}


def test_provider_reservations_survive_restart(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    assert store.reserve_provider("ashby", 100, spacing=2)
    assert not Store(store.path).reserve_provider("ashby", 101, spacing=2)
    store.cooldown_provider("ashby", 150)
    assert not store.reserve_provider("ashby", 149)
    assert store.reserve_provider("ashby", 150)


def test_foreign_worker_cannot_exhaust_master_retry_policy(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    with store.transaction() as db:
        enqueue(db, "master_resume", "master", {}, 100)
        enqueue(db, "email_delivery", "email", {}, 100)
    master = Queue(store, lease_seconds=10, max_attempts=5)
    email = Queue(store, lease_seconds=10, max_attempts=3)
    for now in [100, 111, 122]:
        assert master.claim(["master_resume"], now=now) is not None
        assert email.claim(["email_delivery"], now=now) is not None
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert (
            list(pool.map(lambda _: email.claim(["email_delivery"], now=133), range(4)))
            == [None] * 4
        )
    with store.connection() as db:
        states = {r["kind"]: r["status"] for r in db.execute("SELECT * FROM tasks")}
    assert states == {"master_resume": "running", "email_delivery": "failed"}
    restarted = Queue(Store(store.path), lease_seconds=10, max_attempts=5)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: restarted.claim(["master_resume"], now=133), range(4)))
    assert sum(task is not None for task in claims) == 1
    assert next(task for task in claims if task is not None).attempts == 4
    assert restarted.claim(["master_resume"], now=144).attempts == 5
    assert restarted.claim(["master_resume"], now=155) is None
