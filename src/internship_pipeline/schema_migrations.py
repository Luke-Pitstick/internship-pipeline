"""Ordered SQLite schema upgrades, committed atomically with their version."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

Migration = Callable[[sqlite3.Connection], None]


class SchemaError(ValueError):
    """The database cannot be safely opened by this application version."""


def _scoring_limits(db: sqlite3.Connection) -> None:
    # Some releases created this table before schema versions were recorded.
    # Keep any saved limits, and reject an existing table with the wrong shape.
    db.execute(
        "CREATE TABLE IF NOT EXISTS scoring_limits ("
        "id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)"
    )
    db.execute("SELECT id,revision,data FROM scoring_limits LIMIT 0")


STATE_MIGRATIONS: tuple[Migration, ...] = (_scoring_limits,)
IDENTITY_MIGRATIONS: tuple[Migration, ...] = ()


def schema_version(db: sqlite3.Connection, migrations: tuple[Migration, ...]) -> int:
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if not 0 <= version <= len(migrations):
        raise SchemaError(
            f"Database schema version {version} is unsupported by this image "
            f"(maximum {len(migrations)}); use a release that supports this schema."
        )
    return version


def migrate(
    db: sqlite3.Connection, migrations: tuple[Migration, ...], *, baseline: str | None = None
) -> None:
    """Apply pending upgrades under one write lock; failure or process death rolls back.

    Migration functions must use execute/executemany, never executescript, commit,
    external I/O, or a second connection. SQLite DDL, data changes and user_version
    then share the same transaction.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        version = schema_version(db, migrations)
        if (
            baseline is not None
            and not db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
        ):
            if version:
                raise SchemaError("Versioned database is missing its application tables.")
            # Execute the frozen baseline inside this transaction too. executescript
            # would implicitly commit and break atomic creation/migration.
            statement = ""
            for line in baseline.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ""
            if statement.strip():
                raise SchemaError("Database baseline contains an incomplete SQL statement.")
        for next_version, upgrade in enumerate(migrations[version:], start=version + 1):
            upgrade(db)
            db.execute(f"PRAGMA user_version={next_version}")
        db.commit()
    except BaseException:
        db.rollback()
        raise
