"""Immutable model configuration revisions, encrypted current secrets and attempt ledger."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from internship_pipeline.providers.connections import (
    ENDPOINTS,
    GENERAL_ENDPOINTS,
    ConnectionInput,
    Kind,
    ProbeResult,
)


class ConnectionError(ValueError):
    """Safe, application-authored error suitable for the owner UI."""


class ModelConnectionStore:
    def __init__(self, db_path: Path, key_path: Path):
        self.db_path = db_path
        self.key_path = key_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS model_revisions (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL, created_at REAL NOT NULL,
                    config TEXT, deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS model_credentials (
                    kind TEXT PRIMARY KEY, encrypted BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revision INTEGER NOT NULL, kind TEXT NOT NULL,
                    started_at REAL NOT NULL, completed_at REAL,
                    status TEXT NOT NULL, effective_model TEXT,
                    input_tokens INTEGER, output_tokens INTEGER,
                    request_bytes INTEGER NOT NULL,
                    output_token_limit INTEGER,
                    purpose TEXT NOT NULL DEFAULT 'connection_test'
                );
            """)
            existing = db.execute("SELECT 1 FROM model_credentials LIMIT 1").fetchone()
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            for table in ("email_config", "sheets_config"):
                if table in tables and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    existing = True
        if not key_path.exists():
            if existing:
                raise ConnectionError("Restore model-credentials.key from your private backup.")
            key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(Fernet.generate_key())
                    stream.flush()
                    os.fsync(stream.fileno())
        if key_path.is_symlink() or key_path.stat().st_mode & 0o077:
            raise ConnectionError("Model credential key must be a private file (mode 0600).")
        try:
            self.cipher = Fernet(key_path.read_bytes())
        except ValueError:
            raise ConnectionError("Restore a valid model-credentials.key from backup.") from None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _latest(self, db: sqlite3.Connection, kind: Kind) -> sqlite3.Row | None:
        row: sqlite3.Row | None = db.execute(
            "SELECT * FROM model_revisions WHERE kind=? ORDER BY revision DESC LIMIT 1", (kind,)
        ).fetchone()
        return row

    def summary(self) -> dict[str, dict[str, Any]]:
        with self.connection() as db:
            result: dict[str, dict[str, Any]] = {}
            for kind in ("jev", "general"):
                row = self._latest(db, kind)
                revision = row["revision"] if row else 0
                configured = bool(row and not row["deleted"])
                attempt = db.execute(
                    "SELECT * FROM model_attempts WHERE revision=? ORDER BY id DESC LIMIT 1",
                    (revision,),
                ).fetchone()
                ready = bool(configured and attempt and attempt["status"] == "success")
                result[kind] = {
                    "configured": configured,
                    "revision": revision,
                    "tested_revision": revision if ready else None,
                    "ready": ready,
                    "config": json.loads(row["config"]) if configured and row else None,
                    "last_test": dict(attempt) if attempt else None,
                }
            return result

    def save(self, kind: Kind, body: ConnectionInput) -> dict[str, Any]:
        supported = (
            body.endpoint in GENERAL_ENDPOINTS.values()
            if kind == "general"
            else (body.endpoint == ENDPOINTS["jev"])
        )
        if not supported:
            raise ConnectionError("Only the documented official provider endpoint is supported.")
        key = body.api_key.get_secret_value() if body.api_key is not None else None
        if key is not None and (not key.isascii() or any(c.isspace() for c in key)):
            raise ConnectionError("API keys must contain printable ASCII without whitespace.")
        if key is not None and any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ConnectionError("API keys must contain printable ASCII without whitespace.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, kind)
            if (row["revision"] if row else 0) != body.expected_revision:
                raise ConnectionError("This connection changed. Reload settings before saving.")
            secret = db.execute("SELECT encrypted FROM model_credentials WHERE kind=?", (kind,))
            changing_provider = bool(
                row
                and not row["deleted"]
                and json.loads(row["config"])["endpoint"] != body.endpoint
            )
            if changing_provider and key is None:
                raise ConnectionError("Enter an API key for the newly selected provider.")
            if key is None and not secret.fetchone():
                raise ConnectionError("Enter an API key to create this connection.")
            config = body.model_dump(exclude={"api_key", "expected_revision"})
            db.execute(
                "INSERT INTO model_revisions(kind,created_at,config) VALUES(?,?,?)",
                (kind, time.time(), json.dumps(config)),
            )
            if key is not None:
                db.execute(
                    "INSERT OR REPLACE INTO model_credentials VALUES(?,?)",
                    (kind, self.cipher.encrypt(key.encode())),
                )
        return self.summary()[kind]

    def remove(self, kind: Kind, expected_revision: int) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, kind)
            if (row["revision"] if row else 0) != expected_revision:
                raise ConnectionError("This connection changed. Reload settings before removing.")
            db.execute(
                "INSERT INTO model_revisions(kind,created_at,deleted) VALUES(?,?,1)",
                (kind, time.time()),
            )
            db.execute("DELETE FROM model_credentials WHERE kind=?", (kind,))
        return self.summary()[kind]

    def ready_connection(self, kind: Kind, expected_revision: int) -> tuple[ConnectionInput, str]:
        """Resolve one tested immutable revision and its current credential atomically."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, kind)
            test = db.execute(
                "SELECT status FROM model_attempts WHERE revision=? ORDER BY id DESC LIMIT 1",
                (expected_revision,),
            ).fetchone()
            if (
                not row
                or row["deleted"]
                or row["revision"] != expected_revision
                or not test
                or test[0] != "success"
            ):
                raise ConnectionError(
                    "Save and successfully test the current model connection first."
                )
            encrypted = db.execute(
                "SELECT encrypted FROM model_credentials WHERE kind=?", (kind,)
            ).fetchone()
            try:
                key = self.cipher.decrypt(encrypted[0]).decode()
            except (InvalidToken, TypeError, UnicodeError):
                raise ConnectionError(
                    "Credential unavailable. Restore the key or replace API key."
                ) from None
            return ConnectionInput(
                **json.loads(row["config"]), expected_revision=expected_revision
            ), key

    def reserve_test(self, kind: Kind, expected_revision: int) -> tuple[int, ConnectionInput, str]:
        from internship_pipeline.providers.connections import probe_body

        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, kind)
            if not row or row["deleted"]:
                raise ConnectionError("Save this connection before testing it.")
            if row["revision"] != expected_revision:
                raise ConnectionError("This connection changed. Reload settings before testing.")
            now = time.time()
            recent = db.execute(
                "SELECT COUNT(*) FROM model_attempts WHERE kind=? AND started_at>?",
                (kind, now - 3600),
            ).fetchone()[0]
            active = db.execute(
                "SELECT 1 FROM model_attempts WHERE kind=? AND status='pending' AND started_at>?",
                (kind, now - 65),
            ).fetchone()
            if recent >= 5 or active:
                raise ConnectionError("Test limit reached: one at a time, at most five per hour.")
            encrypted = db.execute(
                "SELECT encrypted FROM model_credentials WHERE kind=?",
                (kind,),
            ).fetchone()
            try:
                key = self.cipher.decrypt(encrypted[0]).decode()
            except (InvalidToken, TypeError, UnicodeError):
                raise ConnectionError(
                    "Credential unavailable. Restore the key or replace API key."
                ) from None
            config = ConnectionInput(**json.loads(row["config"]), expected_revision=row["revision"])
            request_size = len(
                json.dumps(
                    probe_body(kind, config),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            cursor = db.execute(
                "INSERT INTO model_attempts(revision,kind,started_at,status,request_bytes,"
                "output_token_limit) VALUES(?,?,?,'pending',?,?)",
                (
                    row["revision"],
                    kind,
                    now,
                    request_size,
                    config.max_output_tokens if kind == "general" else None,
                ),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid, config, key

    def complete_test(self, attempt: int, result: ProbeResult) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE model_attempts SET completed_at=?,status=?,effective_model=?,"
                "input_tokens=?,output_tokens=? WHERE id=? AND status='pending'",
                (
                    time.time(),
                    result.status,
                    result.effective_model,
                    result.input_tokens,
                    result.output_tokens,
                    attempt,
                ),
            )
