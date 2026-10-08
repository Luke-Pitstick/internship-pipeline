"""Local stopped-instance backups, verified fresh restores and diagnostic summaries."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException

from internship_pipeline.identity import SCHEMA as IDENTITY_SCHEMA
from internship_pipeline.models import Settings
from internship_pipeline.storage import SCHEMA as STATE_SCHEMA
from internship_pipeline.storage import Store


class OperationError(ValueError):
    pass


@contextmanager
def installation_lock(root: Path, *, offline: bool = False) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".operation.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if offline else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperationError(
                "Stop the application and all workers before backup or recovery."
            ) from None
        yield
    finally:
        os.close(descriptor)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def _files(root: Path) -> list[Path]:
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise OperationError("Symbolic links are unsupported in an installation backup.")
        if path.is_file():
            paths.append(path)
        elif not path.is_dir():
            raise OperationError("Backup contains a nonregular file.")
    return paths


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise OperationError("Symbolic links cannot be backed up.")
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in _files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(path, target)
        target.chmod(0o600)


def _verify_database(db: sqlite3.Connection, name: str) -> None:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise OperationError("Database integrity check failed.")
    # Validate against the same base schemas that initialize each distinct database.
    # Optional feature tables may be absent on a fresh installation.
    with sqlite3.connect(":memory:") as expected:
        expected.executescript(STATE_SCHEMA if name == "state.sqlite3" else IDENTITY_SCHEMA)
        for row in expected.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            table = row[0]
            columns = {column[1] for column in expected.execute(f"PRAGMA table_info({table})")}
            actual = {column[1] for column in db.execute(f"PRAGMA table_info({table})")}
            if not columns <= actual:
                raise OperationError("Database does not contain the required application schema.")


def _snapshot(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise OperationError("Both application databases are required for backup.")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as live:
        _verify_database(live, destination.name)
        with sqlite3.connect(destination) as target:
            live.backup(target)
            _verify_database(target, destination.name)
            target.execute("PRAGMA journal_mode=DELETE")
    destination.chmod(0o600)


def _credentials(root: Path) -> None:
    try:
        cipher = Fernet((root / "model-credentials.key").read_bytes())
        with sqlite3.connect(
            (root / "state.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        ) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, column in [
                ("model_credentials", "encrypted"),
                ("email_config", "encrypted"),
                ("sheets_config", "encrypted"),
            ]:
                if table not in tables:
                    continue
                columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if column in columns:
                    for row in db.execute(
                        f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
                    ):
                        cipher.decrypt(row[0])
    except (ValueError, InvalidToken, OSError):
        raise OperationError("Credential key does not decrypt the backed-up connections.") from None


def _publish(stage: Path, destination: Path) -> None:
    # Reserve a new path atomically; never replace a pre-existing directory.
    destination.mkdir(mode=0o700)
    try:
        os.rename(stage, destination)
    except OSError:
        # Remove only our still-empty reservation. Never remove another writer's files.
        try:
            destination.rmdir()
        except OSError:
            pass
        raise
    descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_installation(root: Path, settings: Settings, destination: Path) -> dict[str, Any]:
    root = root.resolve()
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise OperationError("Choose a new backup directory outside the installation.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with installation_lock(root, offline=True):
        stage = Path(tempfile.mkdtemp(prefix=".pipeline-backup-", dir=destination.parent))
        try:
            _snapshot(settings.database_path, stage / "state.sqlite3")
            _snapshot(root / "identity.sqlite3", stage / "identity.sqlite3")
            key = root / "model-credentials.key"
            if key.is_symlink() or not key.is_file():
                raise OperationError("The exact credential encryption key is required.")
            shutil.copyfile(key, stage / "model-credentials.key")
            _copy_tree(settings.artifact_dir, stage / "artifacts")
            _copy_tree(root / "uploads", stage / "uploads")
            _copy_tree(root / "config", stage / "config")
            for source, name in [
                (settings.companies_path, "companies.yaml"),
                (settings.searches_path, "searches.yaml"),
            ]:
                if source and source.is_file():
                    if source.is_symlink():
                        raise OperationError("Configuration cannot be a symbolic link.")
                    (stage / "config").mkdir(exist_ok=True)
                    shutil.copyfile(source, stage / "config" / name)
            # Effective settings, not a second copy of deployment-relative path assumptions.
            payload = settings.model_dump(mode="json")
            (stage / "effective-settings.json").write_text(json.dumps(payload))
            _credentials(stage)
            entries = {}
            for path in _files(stage):
                path.chmod(0o600)
                entries[str(path.relative_to(stage))] = {
                    "size": path.stat().st_size,
                    "sha256": _hash(path),
                }
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            manifest = {"format": 1, "created_at": time.time(), "files": entries}
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
            (stage / "manifest.json").chmod(0o600)
            with (stage / "manifest.json").open("rb") as stream:
                os.fsync(stream.fileno())
            # Publishing a fully written directory cannot overwrite an existing installation.
            _publish(stage, destination)
            return {"files": len(entries), "created_at": manifest["created_at"]}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def verify_backup(source: Path) -> dict[str, Any]:
    if source.is_symlink():
        raise OperationError("Backup must be a regular private directory.")
    try:
        manifest: dict[str, Any] = json.loads((source / "manifest.json").read_text())
        if manifest["format"] != 1 or not isinstance(manifest["files"], dict):
            raise ValueError
        actual = {str(p.relative_to(source)) for p in _files(source)} - {"manifest.json"}
        if actual != set(manifest["files"]):
            raise ValueError
        for name, metadata in manifest["files"].items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError
            file = source / path
            if file.stat().st_size != metadata["size"] or _hash(file) != metadata["sha256"]:
                raise ValueError
        if (
            not {
                "state.sqlite3",
                "identity.sqlite3",
                "model-credentials.key",
                "effective-settings.json",
            }
            <= actual
        ):
            raise ValueError
        for name in ["state.sqlite3", "identity.sqlite3"]:
            with sqlite3.connect((source / name).resolve().as_uri() + "?mode=ro", uri=True) as db:
                _verify_database(db, name)
        _credentials(source)
        return manifest
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        raise OperationError(
            "Backup verification failed; preserve the source and inspect local storage."
        ) from None


def restore_installation(source: Path, destination: Path) -> dict[str, Any]:
    if (
        destination.exists()
        or destination.is_symlink()
        or destination.resolve().is_relative_to(source.resolve())
    ):
        raise OperationError(
            "Restore requires a new directory; existing installations are never overwritten."
        )
    manifest = verify_backup(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pipeline-restore-", dir=destination.parent))
    try:
        for name in manifest["files"]:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source / name, target)
            target.chmod(0o600)
            if _hash(target) != manifest["files"][name]["sha256"]:
                raise OperationError(
                    "Restored file verification failed; the source may have changed."
                )
        _credentials(stage)
        settings = json.loads((stage / "effective-settings.json").read_text())
        settings.update(
            database_path=str(destination.absolute() / "state.sqlite3"),
            artifact_dir=str(destination.absolute() / "artifacts"),
            companies_path=str(destination.absolute() / "config/companies.yaml"),
            searches_path=str(destination.absolute() / "config/searches.yaml")
            if settings.get("searches_path")
            else None,
        )
        (stage / "config").mkdir(exist_ok=True, mode=0o700)
        (stage / "config/settings.yaml").write_text(yaml.safe_dump(settings))
        (stage / "config/settings.yaml").chmod(0o600)
        # Unknown in-flight external side effects require owner review. Confirmed delivery
        # ledgers and completed queue entries survive exactly; nothing is blindly replayed.
        with sqlite3.connect(stage / "state.sqlite3") as db:
            db.execute(
                "UPDATE tasks SET "
                "status='failed',lease_until=NULL,error='restore_interrupted_work_"
                "requires_review' WHERE status='running'"
            )
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "email_deliveries" in tables:
                db.execute(
                    "UPDATE email_deliveries SET status='uncertain',"
                    "error='Restore interrupted delivery; inspect before retry' WHERE id IN "
                    "(SELECT json_extract(payload,'$.id') FROM tasks "
                    "WHERE kind='email_delivery' "
                    "AND error='restore_interrupted_work_requires_review')"
                )
            if "sheets_runs" in tables:
                db.execute(
                    "UPDATE sheets_runs SET state='failed',"
                    "error='Restore interrupted sync; generate a fresh preview' WHERE id IN "
                    "(SELECT json_extract(payload,'$.id') FROM tasks "
                    "WHERE kind='sheets_sync' "
                    "AND error='restore_interrupted_work_requires_review')"
                )
            db.execute("UPDATE targets SET lease_until=0")
        with sqlite3.connect(stage / "identity.sqlite3") as db:
            db.execute("DELETE FROM owner_sessions")
        _publish(stage, destination)
        return {"files": len(manifest["files"]), "restored_at": time.time()}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


class Diagnostics:
    def __init__(self, store: Store, supervisor_status: Path | None = None):
        self.store, self.supervisor_status = store, supervisor_status

    def view(self) -> dict[str, Any]:
        now = time.time()
        with self.store.connection() as db:
            sources = [
                {
                    "id": r["id"],
                    "provider": r["provider"],
                    "last_attempt": r["last_attempt"],
                    "last_success": r["last_success"],
                    "age_seconds": now - r["last_success"] if r["last_success"] else None,
                    "healthy": not bool(r["error"]),
                    "error": "source_request_failed" if r["error"] else None,
                    "next_due": r["next_due"],
                }
                for r in db.execute("SELECT * FROM targets")
            ]
            counts = [
                dict(r)
                for r in db.execute(
                    "SELECT kind,status,COUNT(*) AS count FROM tasks GROUP BY kind,status"
                )
            ]
            activity = [
                dict(r)
                for r in db.execute(
                    "SELECT kind,COUNT(*) AS running,MIN(updated) AS oldest_update,"
                    "MIN(lease_until) AS lease_until FROM tasks WHERE status='running' "
                    "GROUP BY kind"
                )
            ]
            # Raw provider/task messages may contain paths, tokens or posting text.
            failed = [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "attempts": r["attempts"],
                    "updated": r["updated"],
                    "error": "work_failed_check_settings",
                    "retryable": r["kind"] not in {"email_delivery", "sheets_sync"},
                }
                for r in db.execute(
                    "SELECT * FROM tasks WHERE status='failed' ORDER BY updated DESC LIMIT 50"
                )
            ]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            model = []
            for table, _stamp in [
                ("assessment_attempts", "started"),
                ("model_attempts", "started_at"),
                ("tailored_attempts", "started_at"),
            ]:
                if table in tables:
                    for r in db.execute(
                        f"SELECT status,COUNT(*) AS count FROM {table} GROUP BY status"
                    ):
                        model.append(
                            {
                                "operation": table,
                                "status": r["status"]
                                if r["status"]
                                in {
                                    "success",
                                    "pending",
                                    "timeout",
                                    "provider_unavailable",
                                    "rate_limited",
                                    "invalid_output",
                                    "interrupted_unknown_usage",
                                    "unauthorized",
                                }
                                else "needs_attention",
                                "count": r["count"],
                            }
                        )
        workers = {"healthy": False, "roles": [], "at": None}
        if self.supervisor_status:
            try:
                value = json.loads(self.supervisor_status.read_text())
                workers = {
                    "healthy": bool(value.get("healthy")) and now - value.get("at", 0) < 10,
                    "roles": [
                        r
                        for r in value.get("roles", [])
                        if isinstance(r, str)
                        and r
                        in {
                            "matcher",
                            "collector",
                            "discovery",
                            "search-runs",
                            "master-resumes",
                            "tailored-resumes",
                            "email-delivery",
                            "sheets-sync",
                        }
                    ],
                    "at": value.get("at"),
                }
            except (OSError, ValueError, TypeError):
                pass
        return {
            "at": now,
            "sources": sources,
            "queue": counts,
            "activity": activity,
            "failed": failed,
            "models": model,
            "workers": workers,
            "logs": [
                {
                    "at": x["updated"],
                    "event": "work_failed",
                    "kind": x["kind"],
                    "message": x["error"],
                }
                for x in failed
            ],
        }

    def retry(self, task_id: int) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE id=? AND status='failed'", (task_id,)
            ).fetchone()
            if not row:
                raise OperationError("Select a failed task.")
            if row["kind"] in {"email_delivery", "sheets_sync"}:
                raise OperationError("Review external delivery in its integration before retrying.")
            db.execute(
                "UPDATE tasks SET "
                "status='pending',attempts=0,lease_until=NULL,available_at=?,error=NULL WHERE id=?",
                (time.time(), task_id),
            )
        return self.view()


def diagnostics_router(service: Diagnostics, owner: Any) -> APIRouter:
    router = APIRouter(prefix="/api/diagnostics", dependencies=[Depends(owner)])

    @router.get("")
    def view() -> dict[str, Any]:
        return service.view()

    @router.post("/{task_id}/retry")
    def retry(task_id: int) -> dict[str, Any]:
        try:
            return service.retry(task_id)
        except OperationError as exc:
            raise HTTPException(409, str(exc)) from None

    return router
