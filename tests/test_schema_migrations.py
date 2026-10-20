"""Real SQLite upgrades retain data, serialize writers, and survive interruption."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from internship_pipeline.operations import OperationError, _verify_database
from internship_pipeline.schema_migrations import STATE_MIGRATIONS, SchemaError, migrate
from internship_pipeline.storage import SCHEMA, Store


@pytest.mark.parametrize("existing_limits", [False, True])
def test_unversioned_database_upgrades_once_and_preserves_existing_rows(tmp_path, existing_limits):
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO events(kind,at) VALUES('retained',123)")
        if existing_limits:
            STATE_MIGRATIONS[0](db)
            db.execute("INSERT INTO scoring_limits VALUES(1,7,'{\"daily_calls\":123}')")
    for _ in range(2):
        store = Store(path)
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
            assert db.execute("SELECT kind,at FROM events").fetchone()[:] == ("retained", 123)
            rows = [tuple(row) for row in db.execute("SELECT * FROM scoring_limits")]
            assert rows == ([(1, 7, '{"daily_calls":123}')] if existing_limits else [])
            _verify_database(db, "state.sqlite3")


def test_failed_upgrade_rolls_back_ddl_data_and_version_then_retries(tmp_path):
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE retained(value TEXT)")
        db.execute("INSERT INTO retained VALUES('original')")

    def first(db):
        db.execute("CREATE TABLE added(id INTEGER)")
        db.execute("UPDATE retained SET value='upgraded'")

    def second(db):
        db.execute("ALTER TABLE retained ADD COLUMN detail TEXT")
        raise RuntimeError("synthetic interruption")

    with sqlite3.connect(path) as db:
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            migrate(db, (first, second))
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT * FROM retained").fetchone() == ("original",)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='added'").fetchall()
        migrate(db, (first, lambda db: db.execute("ALTER TABLE retained ADD COLUMN detail TEXT")))
        migrate(db, (first, lambda db: db.execute("ALTER TABLE retained ADD COLUMN detail TEXT")))
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT * FROM retained").fetchone() == ("upgraded", None)


def test_killed_migration_rolls_back_and_can_be_retried(tmp_path):
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE retained(value TEXT)")
        db.execute("INSERT INTO retained VALUES('original')")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, signal, sqlite3, sys
from internship_pipeline.schema_migrations import migrate
def interrupted(db):
    db.execute("CREATE TABLE added(id INTEGER)")
    db.execute("UPDATE retained SET value='uncommitted'")
    os.kill(os.getpid(), signal.SIGKILL)
with sqlite3.connect(sys.argv[1]) as db:
    migrate(db, (interrupted,))
""",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == -9, result.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT * FROM retained").fetchone() == ("original",)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='added'").fetchall()
        migrate(db, (lambda db: db.execute("CREATE TABLE added(id INTEGER)"),))
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_concurrent_openers_apply_upgrade_once(tmp_path):
    path = tmp_path / "state.sqlite3"

    def open_database(_):
        with sqlite3.connect(path, timeout=10) as db:
            # Deliberately not IF NOT EXISTS: replay must fail this test.
            migrate(db, (lambda db: db.execute("CREATE TABLE added(id INTEGER)"),))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(open_database, range(8)))
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_reopening_does_not_recreate_baseline_tables_removed_by_a_migration(tmp_path):
    def upgrade(db):
        db.execute("ALTER TABLE original RENAME TO renamed")
        db.execute("ALTER TABLE renamed ADD COLUMN detail TEXT")

    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        for _ in range(2):
            migrate(db, (upgrade,), baseline="CREATE TABLE original(id INTEGER);\n")
        assert db.execute("SELECT id,detail FROM renamed").fetchall() == []
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='original'").fetchall()


def test_newer_schema_is_refused_without_modifying_database(tmp_path):
    path = tmp_path / "state.sqlite3"
    Store(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    before = path.read_bytes()
    with pytest.raises(SchemaError, match="schema version 999"):
        Store(path)
    assert path.read_bytes() == before


def test_versioned_database_missing_migrated_table_is_not_treated_as_old_data(tmp_path):
    path = tmp_path / "state.sqlite3"
    Store(path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE scoring_limits")
        with pytest.raises(OperationError, match="version 1.*scoring_limits"):
            _verify_database(db, "state.sqlite3")
