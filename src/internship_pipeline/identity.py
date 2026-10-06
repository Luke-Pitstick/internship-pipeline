"""Single-owner identity, opaque sessions, and bounded login attempts in SQLite."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pwdlib import PasswordHash

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
    id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owner_setup (id INTEGER PRIMARY KEY CHECK(id=1), token_hash TEXT);
CREATE TABLE IF NOT EXISTS owner_sessions (
    token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, authenticated INTEGER NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS owner_attempts (
    key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL
);
"""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class IdentityError(ValueError):
    """A deliberately nonsensitive account error."""


class Throttled(IdentityError):
    pass


class Identity:
    def __init__(self, path: Path):
        self.path = path
        self.passwords = PasswordHash.recommended()
        self.dummy_hash = self.passwords.hash(secrets.token_urlsafe(32))
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
        path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def claimed(self) -> bool:
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM owner").fetchone() is not None

    def setup_token(self, *, rotate: bool = False) -> str | None:
        """Only return newly issued tokens; persisted storage contains their digest."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM owner").fetchone():
                return None
            if not rotate and connection.execute("SELECT 1 FROM owner_setup").fetchone():
                return None
            token = secrets.token_urlsafe(32)
            connection.execute("INSERT OR REPLACE INTO owner_setup VALUES(1,?)", (digest(token),))
            return token

    def attempt(self, address: str) -> None:
        """Reserve attempts before hashing; limits survive restarts and concurrent requests."""
        now = time.time()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM owner_attempts WHERE started<?", (now - 300,))
            for key, limit in (("global", 100), (digest(address), 10)):
                row = connection.execute(
                    "SELECT count FROM owner_attempts WHERE key=?", (key,)
                ).fetchone()
                if row and row[0] >= limit:
                    raise Throttled("Too many attempts. Try again in five minutes.")
            for key in ("global", digest(address)):
                connection.execute(
                    "INSERT INTO owner_attempts VALUES(?,?,1) "
                    "ON CONFLICT(key) DO UPDATE SET count=count+1",
                    (key, now),
                )

    @staticmethod
    def validate(username: str, password: str) -> str:
        username = username.strip().casefold()
        if not 1 <= len(username) <= 80 or not 12 <= len(password) <= 256:
            raise IdentityError("Use a username and a password between 12 and 256 characters.")
        return username

    def claim(self, token: str, username: str, password: str) -> tuple[str, str, int]:
        username = self.validate(username, password)
        password_hash = self.passwords.hash(password)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT token_hash FROM owner_setup WHERE id=1").fetchone()
            if (
                connection.execute("SELECT 1 FROM owner").fetchone()
                or not row
                or not hmac.compare_digest(row[0], digest(token))
            ):
                raise IdentityError("Setup is unavailable or the setup token is incorrect.")
            connection.execute("INSERT INTO owner VALUES(1,?,?)", (username, password_hash))
            connection.execute("DELETE FROM owner_setup")
            connection.execute("DELETE FROM owner_sessions")
            return self._new_session(connection, True)

    def login(
        self, username: str, password: str, previous: str = ""
    ) -> tuple[str, str, int] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT username,password_hash FROM owner WHERE id=1"
            ).fetchone()
            valid = self.passwords.verify(password, row[1] if row else self.dummy_hash)
            if (
                row
                and valid
                and hmac.compare_digest(username.strip().casefold().encode(), row[0].encode())
            ):
                return self._new_session(connection, True, previous)
            return None

    def session(self, token: str) -> dict[str, Any] | None:
        if not token or len(token) > 100:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT csrf,authenticated,expires FROM owner_sessions "
                "WHERE token_hash=? AND expires>?",
                (digest(token), time.time()),
            ).fetchone()
            return dict(row) if row else None

    def new_session(self, authenticated: bool, previous: str = "") -> tuple[str, str, int]:
        with self.connection() as connection:
            return self._new_session(connection, authenticated, previous)

    @staticmethod
    def _new_session(
        connection: sqlite3.Connection, authenticated: bool, previous: str = ""
    ) -> tuple[str, str, int]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        ttl = 12 * 3600 if authenticated else 20 * 60
        connection.execute(
            "DELETE FROM owner_sessions WHERE expires<? OR token_hash=?",
            (time.time(), digest(previous)),
        )
        connection.execute(
            "INSERT INTO owner_sessions VALUES(?,?,?,?)",
            (digest(token), csrf, int(authenticated), time.time() + ttl),
        )
        return token, csrf, ttl

    def logout(self, token: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM owner_sessions WHERE token_hash=?", (digest(token),))

    def recover(self, username: str, password: str) -> None:
        username = self.validate(username, password)
        password_hash = self.passwords.hash(password)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM owner").fetchone():
                raise IdentityError("No owner exists. Use setup-token to claim this instance.")
            connection.execute(
                "UPDATE owner SET username=?,password_hash=? WHERE id=1", (username, password_hash)
            )
            connection.execute("DELETE FROM owner_sessions")
            connection.execute("DELETE FROM owner_attempts")
