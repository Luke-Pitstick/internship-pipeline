from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from internship_pipeline.models import Job, SourceJob, utcnow
from internship_pipeline.storage import SCHEMA

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "render_dashboard.py"
spec = importlib.util.spec_from_file_location("render_dashboard", MODULE_PATH)
assert spec is not None and spec.loader is not None
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def snapshot() -> dict:
    return {
        "observed_at": time.time(),
        "readiness": dict.fromkeys(
            ["activated", "settings", "companies", "profile", "master_pdf", "codex_auth"], True
        ),
        "roles": dict.fromkeys(["collector", "matcher", "resumes", "delivery", "discovery"], True),
        "database": "readable",
        "renderer": "healthy",
        "counts": {"jobs": 1},
        "queues": [],
        "sources": [],
        "source_summary": {"enabled": 1, "failing": 0, "overdue": 0},
        "recent_jobs": [],
        "oldest_work_age_seconds": None,
        "relevance": {"status": "ready", "screened": 1, "limit": 1000, "accepted": 1},
    }


@pytest.mark.parametrize(
    ("change", "state"),
    [
        ({}, "monitoring"),
        ({"readiness": {"activated": False}}, "waiting"),
        ({"readiness": {"codex_auth": False}}, "blocked"),
        ({"roles": {"collector": False}}, "inactive"),
        ({"database": "unreadable"}, "inactive"),
        ({"source_summary": {"enabled": 0}}, "idle"),
        ({"renderer": "unavailable"}, "degraded"),
        ({"source_summary": {"overdue": 1}}, "degraded"),
        ({"source_summary": {"failing": 1}}, "degraded"),
        ({"queues": [{"kind": "resume", "status": "failed", "count": 1}]}, "degraded"),
    ],
)
def test_states_distinguish_provisioning_processes_and_work(change: dict, state: str) -> None:
    data = snapshot()
    for key, value in change.items():
        if isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    assert dashboard.operational_state(data)[0] == state


def test_cache_retains_explicitly_offline_last_known_data(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = snapshot()
    calls = []

    def fetch(_):
        calls.append(True)
        if len(calls) > 1:
            raise RuntimeError("raw server error with private content")
        return cached

    monkeypatch.setattr(dashboard, "fetch_snapshot", fetch)
    cache = dashboard.SnapshotCache(dashboard.DEFAULT_ADDRESS)
    assert cache.get()["state"] == "monitoring"
    assert cache.get(refresh=True)["state"] == "monitoring"
    assert len(calls) == 1
    cache.last_attempt -= 30
    offline = cache.get()
    assert offline["connection"] == "offline"
    assert offline["snapshot"] == cached
    assert offline["state"] == "offline"
    assert "private content" not in json.dumps(offline)


def test_old_snapshots_are_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    data = snapshot()
    data["observed_at"] -= 100
    monkeypatch.setattr(dashboard, "fetch_snapshot", lambda _: data)
    assert dashboard.SnapshotCache(dashboard.DEFAULT_ADDRESS).get()["state"] == "stale"


def run_remote(root: Path, *, fail_matcher: bool = False) -> dict:
    script = dashboard.REMOTE_SCRIPT.replace(
        'ROOT = Path("/var/data")', f"ROOT = Path({str(root)!r})"
    )
    script = script.replace('PROC = Path("/proc")', f"PROC = Path({str(root / 'proc')!r})")
    script = script.replace(
        'RENDERER_URL = "http://internship-resume-matcher:3000/api/v1/health"',
        'RENDERER_URL = "http://127.0.0.1:1/api/v1/health"',
    )
    if fail_matcher:
        script = script.replace(
            "match = _deterministic_match(job, profile)",
            "raise RuntimeError('PRIVATE_SENTINEL matcher error')",
        )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=5
    )
    return json.loads(result.stdout)


def test_remote_snapshot_omits_private_payloads_and_preserves_source_times(tmp_path: Path) -> None:
    secret = "PRIVATE_SENTINEL_NEVER_RETURN"
    for path in [
        "activated",
        "config/settings.yaml",
        "config/companies.yaml",
        "private/profile.yaml",
        "private/master-resume.pdf",
        "codex/auth.json",
    ]:
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(secret)
    proc = tmp_path / "proc" / "123"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(
        b"python\0-m\0internship_pipeline.cli\0worker\0collector\0" + secret.encode()
    )
    now = time.time()
    (tmp_path / "private/profile.yaml").write_text(
        json.dumps(
            {
                "name": secret,
                "email": secret,
                "facts": [{"id": secret, "text": secret, "skills": ["Python"]}],
            }
        )
    )
    job = synthetic_job("job", "Software intern", description="Python skills. " + secret)
    db = tmp_path / "pipeline.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO targets(id,kind,config,provider,last_success,last_attempt,"
            "next_due,failures,error) VALUES('company:synthetic','company',?,"
            "'greenhouse',?,?,?,2,?)",
            (secret, now - 20, now - 10, now + 300, secret),
        )
        connection.execute(
            "INSERT INTO jobs(id,data,canonical_url,company_key,content_hash,status,"
            "first_seen,last_seen) VALUES('job',?,'https://example.test/job',"
            "'synthetic','hash','open',?,?)",
            (job.model_dump_json(), now - 15, now - 5),
        )
        connection.execute(
            "INSERT INTO tasks(kind,key,payload,status,available_at,created,updated,"
            "error) VALUES('match','match:job',?,'failed',?,?,?,?)",
            (secret, now, now, now, secret),
        )
    before = db.read_bytes()
    result = run_remote(tmp_path)
    assert db.read_bytes() == before
    assert secret not in json.dumps(result)
    assert result["database"] == "readable"
    assert result["readiness"]["codex_auth"] is True
    assert result["roles"]["collector"] is True
    assert result["roles"]["matcher"] is False
    assert result["queues"] == [{"kind": "match", "status": "failed", "count": 1}]
    assert result["sources"][0]["last_success"] == now - 20
    assert result["sources"][0]["failures"] == 2
    assert result["recent_jobs"][0]["event"] == "backlog"
    assert result["recent_jobs"][0]["published_at"] == "2026-10-01T00:00:00+00:00"
    assert result["recent_jobs"][0]["first_seen"] == now - 15
    assert result["recent_jobs"][0]["fit"] == "possible"
    assert result["relevance"]["accepted"] == 1


def synthetic_job(job_id: str, title: str, *, description: str = "Requires Python.") -> Job:
    return Job(
        id=job_id,
        content_hash=job_id,
        posting=SourceJob(
            source="synthetic",
            source_id=job_id,
            board_id="board",
            company="Synthetic Corp",
            title=title,
            apply_url="https://example.test/jobs/" + job_id,
            description=description,
            published_at="2026-10-01T00:00:00Z",
        ),
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        last_verified_at=utcnow(),
        event="backlog",
    )


def create_jobs(root: Path) -> None:
    profile = root / "private/profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps({"facts": [{"id": "python", "text": "Python project", "skills": ["Python"]}]})
    )
    jobs = [
        synthetic_job("intern", "Software Engineering Intern"),
        synthetic_job("fulltime", "Software Engineer"),
        synthetic_job("unrelated", "Finance Intern"),
        synthetic_job("unsupported", "Software Intern", description="Requires Rust."),
    ]
    with sqlite3.connect(root / "pipeline.sqlite3") as connection:
        connection.executescript(SCHEMA)
        for job in jobs:
            connection.execute(
                "INSERT INTO jobs(id,data,canonical_url,company_key,content_hash,status,"
                "first_seen,last_seen) VALUES(?,?,?,?,?,'open',?,?)",
                (
                    job.id,
                    job.model_dump_json(),
                    job.posting.apply_url,
                    "synthetic",
                    job.content_hash,
                    time.time(),
                    time.time(),
                ),
            )


def test_relevant_view_excludes_fulltime_unrelated_and_unsupported_jobs(tmp_path: Path) -> None:
    create_jobs(tmp_path)
    data = run_remote(tmp_path)
    assert data["counts"]["jobs"] == 4
    assert data["relevance"] == {"status": "ready", "screened": 4, "limit": 1000, "accepted": 1}
    assert [job["title"] for job in data["recent_jobs"]] == ["Software Engineering Intern"]


@pytest.mark.parametrize("failure", ["missing_profile", "invalid_profile", "matcher"])
def test_relevant_view_fails_closed_without_returning_raw_jobs(
    tmp_path: Path, failure: str
) -> None:
    create_jobs(tmp_path)
    if failure == "missing_profile":
        (tmp_path / "private/profile.yaml").unlink()
    elif failure == "invalid_profile":
        (tmp_path / "private/profile.yaml").write_text("PRIVATE_SENTINEL invalid profile")
    data = run_remote(tmp_path, fail_matcher=failure == "matcher")
    assert data["database"] == "readable"
    assert data["counts"]["jobs"] == 4
    assert data["recent_jobs"] == []
    assert data["relevance"]["status"] == (
        "profile_missing" if failure == "missing_profile" else "unavailable"
    )
    assert "PRIVATE_SENTINEL" not in json.dumps(data)


def test_remote_missing_database_does_not_create_it(tmp_path: Path) -> None:
    result = run_remote(tmp_path)
    assert result["database"] == "missing"
    assert not (tmp_path / "pipeline.sqlite3").exists()
    assert dashboard.operational_state(result)[0] == "waiting"


def test_remote_bad_database_is_reported_without_raw_contents(tmp_path: Path) -> None:
    (tmp_path / "pipeline.sqlite3").write_text("PRIVATE_SENTINEL invalid sqlite")
    result = run_remote(tmp_path)
    assert result["database"] == "unreadable"
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def test_ssh_address_rejects_remote_command_injection() -> None:
    with pytest.raises(ValueError):
        dashboard.fetch_snapshot("srv@ssh.oregon.render.com; cat /var/data/codex/auth.json")


def test_html_uses_text_nodes_for_untrusted_values() -> None:
    assert "innerHTML" not in dashboard.HTML
    assert "textContent=value" in dashboard.HTML
    assert "setInterval(()=>refresh(),30000)" in dashboard.HTML
