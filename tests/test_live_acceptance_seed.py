"""The acceptance seed must not fetch a source or reuse an installation."""

from __future__ import annotations

import os
import runpy
import stat
from pathlib import Path

import pytest

from internship_pipeline.run_limits import RunLimitError, reserve
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.storage import Store

SEED_PATH = Path(__file__).parents[1] / "deploy/live-acceptance-seed.py"
PREPARE = runpy.run_path(str(SEED_PATH))["prepare"]


def test_seed_uses_production_ingestion_and_admission_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Synthetic seed must not make a public ATS request")

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", forbidden)
    operator_db = tmp_path / "operator.sqlite3"
    monkeypatch.setenv("PIPELINE_DATABASE_PATH", str(operator_db))
    root = tmp_path / "fresh"
    report = PREPARE(root, 1_000_000)
    assert not operator_db.exists()
    store = Store(root / "state.sqlite3")
    assert len(store.list_jobs()) == 2
    assert report["public_source_verified"] is False
    assert report["source_paused"] is True
    assert SearchRuns(store).view(report["run_id"])["run"]["collected"] == 2
    ids = list(report["job_ids"].values())
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM search_run_jobs").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM run_reservations").fetchone()[0] == 0
        for job_id in (ids[0], ids[1], ids[0], ids[1]):
            reserve(db, job_id, "synthetic-test", 10)
        with pytest.raises(RunLimitError, match="run_call_limit"):
            reserve(db, ids[0], "synthetic-test", 10)


def test_seed_refuses_existing_data_symlink_and_invalid_budget(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    sentinel = root / "operator-data"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="new or empty"):
        PREPARE(root, 1_000_000)
    assert sentinel.read_text() == "preserve"
    assert list(root.iterdir()) == [sentinel]
    link = tmp_path / "symlink"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="new or empty"):
        PREPARE(link, 1_000_000)
    missing = tmp_path / "invalid-budget"
    with pytest.raises(ValueError):
        PREPARE(missing, -1)
    assert not missing.exists()


def test_seed_hardens_owned_empty_root_and_keeps_all_created_files_private(tmp_path: Path) -> None:
    root = tmp_path / "empty-world-writable"
    root.mkdir()
    root.chmod(0o777)
    previous_umask = os.umask(0o022)
    try:
        PREPARE(root, 1_000_000)
        resulting_umask = os.umask(0o022)
        assert resulting_umask == 0o022
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for path in root.rglob("*"):
        assert path.stat().st_uid == os.getuid()
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
