"""A durable single-host work queue with expiring ownership leases."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from internship_pipeline.models import utcnow
from internship_pipeline.storage import Store


@dataclass(frozen=True)
class Task:
    id: int
    kind: str
    key: str
    payload: dict[str, Any]
    attempts: int
    token: str


class Queue:
    def __init__(self, store: Store, lease_seconds: int = 300, max_attempts: int = 5):
        self.store = store
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def claim(
        self,
        kinds: list[str],
        now: float | None = None,
        *,
        guard: Callable[[sqlite3.Connection, sqlite3.Row], bool] | None = None,
    ) -> Task | None:
        now = utcnow().timestamp() if now is None else now
        if not kinds:
            return None
        placeholders = ",".join("?" for _ in kinds)
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status='failed',error='LeaseExpired',updated=? "
                "WHERE status='running' AND lease_until<=? AND attempts>=?",
                (now, now, self.max_attempts),
            )
            while True:
                row = connection.execute(
                    f"SELECT * FROM tasks WHERE kind IN ({placeholders}) AND attempts<? AND "
                    "((status='pending' AND available_at<=?) OR "
                    "(status='running' AND lease_until<=?)) ORDER BY "
                    "CASE WHEN created<=? THEN 0 "
                    "ELSE 2 END,available_at,id LIMIT 1",
                    (*kinds, self.max_attempts, now, now, now - 300),
                ).fetchone()
                if row is None:
                    return None
                if guard is None or guard(connection, row):
                    break
                connection.execute(
                    "UPDATE tasks SET status='cancelled',error='Automation disabled or job "
                    "no longer qualifies',lease_until=NULL,updated=? WHERE id=?",
                    (now, row["id"]),
                )
            token = uuid.uuid4().hex
            connection.execute(
                "UPDATE tasks SET status='running',attempts=attempts+1,token=?,"
                "lease_until=?,updated=? "
                "WHERE id=?",
                (token, now + self.lease_seconds, now, row["id"]),
            )
            return Task(
                row["id"],
                row["kind"],
                row["key"],
                json.loads(row["payload"]),
                row["attempts"] + 1,
                token,
            )

    def renew(self, task: Task) -> bool:
        now = utcnow().timestamp()
        with self.store.transaction() as connection:
            result = connection.execute(
                "UPDATE tasks SET lease_until=?,updated=? WHERE id=? AND token=? "
                "AND status='running'",
                (now + self.lease_seconds, now, task.id, task.token),
            )
            return result.rowcount == 1

    def defer(self, task: Task, seconds: float = 5) -> None:
        """Wait for a dependency without consuming a transport retry attempt."""
        now = utcnow().timestamp()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status='pending',attempts=attempts-1,available_at=?,"
                "lease_until=NULL,updated=? WHERE id=? AND token=? AND status='running'",
                (now + seconds, now, task.id, task.token),
            )

    @contextmanager
    def heartbeat(self, task: Task) -> Iterator[None]:
        stop = threading.Event()

        def maintain() -> None:
            while not stop.wait(max(1, self.lease_seconds / 3)):
                if not self.renew(task):
                    return

        thread = threading.Thread(target=maintain, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=2)

    def complete(self, task: Task) -> bool:
        with self.store.transaction() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='done',lease_until=NULL,updated=?,error=NULL "
                "WHERE id=? AND token=? AND status='running'",
                (utcnow().timestamp(), task.id, task.token),
            )
            return cursor.rowcount == 1

    def fail(self, task: Task, error: str, now: float | None = None) -> None:
        now = utcnow().timestamp() if now is None else now
        status = "failed" if task.attempts >= self.max_attempts else "pending"
        delay = min(3600, 5 * 2 ** (task.attempts - 1))
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status=?,available_at=?,lease_until=NULL,error=?,updated=? "
                "WHERE id=? AND token=? AND status='running'",
                (status, now + delay, error, now, task.id, task.token),
            )

    def retry_failed(self, task_id: int | None = None) -> int:
        with self.store.transaction() as connection:
            sql = "UPDATE tasks SET status='pending',attempts=0,available_at=?,error=NULL "
            sql += "WHERE status='failed'"
            params: list[Any] = [utcnow().timestamp()]
            if task_id is not None:
                sql += " AND id=?"
                params.append(task_id)
            return connection.execute(sql, params).rowcount

    def needs_attention(self, task: Task, reason: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status='failed',error=?,lease_until=NULL,updated=? "
                "WHERE id=? AND token=? AND status='running'",
                (reason, utcnow().timestamp(), task.id, task.token),
            )
