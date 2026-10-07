"""Synthetic container-only recovery fixture; no providers or personal configuration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import resource
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from internship_pipeline.app import runtime_settings
from internship_pipeline.email_integrations import EmailInput, EmailIntegrations
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import FetchResult, SourceJob
from internship_pipeline.operations import installation_lock
from internship_pipeline.providers.connections import ENDPOINTS, ConnectionInput
from internship_pipeline.search_runs import SearchRuns, SourceSave
from internship_pipeline.sheets_integration import SheetsIntegration
from internship_pipeline.sources import ats
from internship_pipeline.storage import Store, enqueue


def seed(root: Path) -> None:
    settings = runtime_settings(root, root / "config/settings.yaml")
    store = Store(settings.database_path)
    connections = ModelConnectionStore(store.path, root / "model-credentials.key")
    connections.save("general", ConnectionInput(
        model="synthetic-unprobed", endpoint=ENDPOINTS["general"],
        api_key="synthetic-container-secret", expected_revision=0,
    ))
    email = EmailIntegrations(store, connections)
    email.save(EmailInput(
        expected_revision=0, host="smtp.example.test", username="synthetic",
        password="synthetic-smtp-secret", sender="source@example.test",
        recipient="owner@example.test", enabled=False,
    ))
    # A disabled destination exercises key retention without parsing a real private key.
    SheetsIntegration(store, connections)
    with store.transaction() as db:
        db.execute("INSERT INTO sheets_config VALUES(1,1,?,?,NULL,0)", (
            json.dumps({"enabled": False}),
            connections.cipher.encrypt(b"synthetic-sheets-secret"),
        ))
        for identifier, status in (("confirmed", "accepted"), ("interrupted", "sending")):
            db.execute("INSERT INTO email_deliveries VALUES(?,1,1,?,'Synthetic','Fixture',?,NULL)",
                       (identifier, status, 1 if status == "accepted" else None))
            enqueue(db, "email_delivery", "email:" + identifier, {"id": identifier}, 1)
            db.execute("UPDATE tasks SET status=?,lease_until=? WHERE key=?", (
                "done" if status == "accepted" else "running", 99999999999,
                "email:" + identifier,
            ))
        db.execute("INSERT INTO sheets_runs VALUES('confirmed',1,1,'done',NULL,'synthetic','{}')")
        db.execute("INSERT INTO sheets_journal VALUES('confirmed','synthetic',2,'{}',1)")
        enqueue(db, "sheets_sync", "sheets:confirmed", {"id": "confirmed"}, 1)
        db.execute("UPDATE tasks SET status='done' WHERE key='sheets:confirmed'")
    runs = SearchRuns(store)
    search = runs.save(SourceSave(name="Synthetic interruption", board="synthetic",
                                  expected_revision=0))["searches"][0]
    runs.start(search["id"])
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    tex = settings.artifact_dir / "synthetic.tex"
    tex.write_text(r"\documentclass{article}\begin{document}Synthetic resume.\end{document}")
    started = time.monotonic()
    result = subprocess.run([
        "pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
        "-output-directory", str(settings.artifact_dir), str(tex),
    ], capture_output=True, timeout=30, check=False)
    assert result.returncode == 0 and tex.with_suffix(".pdf").read_bytes().startswith(b"%PDF-")
    (root / "uploads").mkdir(exist_ok=True)
    (root / "uploads/synthetic.txt").write_text("Synthetic retained source")
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [root / "model-credentials.key", tex, tex.with_suffix(".pdf"),
                     root / "uploads/synthetic.txt"]
    }
    (root / "uploads/fixture-hashes.json").write_text(json.dumps(hashes))
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    print(json.dumps({"render_seconds": round(time.monotonic() - started, 3),
                      "render_peak_rss_kib": usage.ru_maxrss,
                      "render_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3)}), flush=True)


async def collection(root: Path, interrupted: bool) -> None:
    settings = runtime_settings(root, root / "config/settings.yaml")
    store = Store(settings.database_path)

    async def fetch(*args: object) -> FetchResult:
        if not interrupted:
            raise AssertionError("Recovered worker must use its persisted fetch checkpoint")
        return FetchResult(jobs=[SourceJob(
            source="greenhouse", source_id="1", board_id="browser-greenhouse-synthetic",
            company="Synthetic", title="Internship", description="Python",
            apply_url="https://example.test/1",
        )])

    if interrupted:
        def pause(*args: object, **kwargs: object) -> None:
            print("CHECKPOINT_PERSISTED", flush=True)
            time.sleep(120)
            raise AssertionError("Interruption deadline exceeded")
        store.ingest = pause  # type: ignore[method-assign,assignment]
    else:
        with store.transaction() as db:
            db.execute("UPDATE tasks SET lease_until=0 WHERE kind='collection_run'")
    with patch.object(ats, "fetch_company", fetch), installation_lock(root):
        assert await SearchRuns(store).process_next(settings)
    assert len(store.list_jobs()) == 1
    with store.connection() as db:
        snapshot = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
                    for table in ("jobs", "observations")}
    (root / "uploads/job-checkpoint.json").write_text(json.dumps(snapshot))


def verify(root: Path, expected_uid: int = 10001) -> None:
    settings = runtime_settings(root, root / "config/settings.yaml")
    store = Store(settings.database_path)
    connections = ModelConnectionStore(store.path, root / "model-credentials.key")
    for name, digest in json.loads((root / "uploads/fixture-hashes.json").read_text()).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    with store.connection() as db:
        expected = json.loads((root / "uploads/job-checkpoint.json").read_text())
        for table, rows in expected.items():
            assert [dict(row) for row in db.execute(f"SELECT * FROM {table}")] == rows
        for table, secret in (("model_credentials", b"synthetic-container-secret"),
                              ("email_config", b"synthetic-smtp-secret"),
                              ("sheets_config", b"synthetic-sheets-secret")):
            assert connections.cipher.decrypt(db.execute(
                f"SELECT encrypted FROM {table}"
            ).fetchone()[0]) == secret
        assert db.execute("SELECT status FROM tasks WHERE key='email:confirmed'").fetchone()[0] \
            == "done"
        assert db.execute("SELECT status FROM email_deliveries WHERE id='confirmed'") \
            .fetchone()[0] == "accepted"
        assert db.execute("SELECT status FROM email_deliveries WHERE id='interrupted'") \
            .fetchone()[0] == "uncertain"
        assert db.execute("SELECT status,error FROM tasks WHERE key='email:interrupted'") \
            .fetchone()[:] == ("failed", "restore_interrupted_work_requires_review")
        assert db.execute("SELECT state FROM sheets_runs WHERE id='confirmed'").fetchone()[0] \
            == "done"
        assert db.execute("SELECT COUNT(*) FROM sheets_journal").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM email_attempts").fetchone()[0] == 0
    assert len(store.list_jobs()) == 1
    assert all(p.stat().st_uid == expected_uid and p.stat().st_mode & 0o077 == 0
               for p in root.rglob("*") if p.is_file())


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "interrupt", "resume", "verify"])
    parser.add_argument("--root", type=Path, default=Path("/var/data"))
    args = parser.parse_args()
    if args.action == "seed":
        with installation_lock(args.root, offline=True):
            seed(args.root)
    elif args.action == "verify":
        verify(args.root)
    else:
        asyncio.run(collection(args.root, args.action == "interrupt"))


if __name__ == "__main__":
    main()
