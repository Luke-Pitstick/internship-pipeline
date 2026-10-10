"""Command line entry points for local operation and independent workers."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import yaml

from internship_pipeline.collection import collect_due, register_targets
from internship_pipeline.config import (
    ConfigurationError,
    load_companies,
    load_searches,
    load_settings,
)
from internship_pipeline.models import Company, Settings
from internship_pipeline.profile_settings import ProfileSettings
from internship_pipeline.queue import Queue
from internship_pipeline.storage import Store

if TYPE_CHECKING:
    from internship_pipeline.pipeline import Pipeline


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Find internships and prepare application alerts")
    cli.add_argument(
        "--config", type=Path, help="Settings YAML; relative paths use the working directory"
    )
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("recover-owner", "setup-token", "setup-link"):
        account = commands.add_parser(name, help="Local operator account recovery")
        account.add_argument(
            "--data-dir", type=Path, default=Path(os.getenv("PIPELINE_DATA_DIR", "/var/data"))
        )
        if name == "setup-link":
            account.add_argument(
                "--origin", default=os.getenv("PIPELINE_ORIGIN", "http://localhost:8080")
            )
    scan = commands.add_parser("scan", help="Run one collection pass and available downstream work")
    scan.add_argument(
        "--once", action="store_true", help="Explicitly select the default one-shot mode"
    )
    scan.add_argument("--collect-only", action="store_true")
    scan.add_argument(
        "--force", action="store_true", help="Ignore due times, but preserve rate limits"
    )
    worker = commands.add_parser("worker", help="Run an independent continuous process")
    worker.add_argument(
        "role",
        choices=[
            "collector",
            "matcher",
            "discovery",
            "master-resumes",
            "search-runs",
            "tailored-resumes",
            "email-delivery",
            "sheets-sync",
        ],
    )
    worker.add_argument(
        "--once", action="store_true", help="Process at most one available work item"
    )
    commands.add_parser("serve", help="Supervise all continuous workers in one service")
    commands.add_parser("status", help="Show sanitized task and provider health")
    jobs = commands.add_parser("jobs", help="List observed jobs")
    jobs.add_argument("--backlog", action="store_true")
    retry = commands.add_parser("retry", help="Explicitly retry failed work")
    retry.add_argument("task_id", nargs="?", type=int)
    commands.add_parser(
        "review-backlog", help="Queue initial matches without claiming they are new"
    )
    applied = commands.add_parser(
        "mark-applied", help="Record an application you actually submitted"
    )
    applied.add_argument("job_id")
    add = commands.add_parser(
        "add-company", help="Validate and persist a company in the YAML registry"
    )
    add.add_argument("id")
    add.add_argument("name")
    add.add_argument("careers_url")
    add.add_argument("--priority", action="store_true")
    discovery = commands.add_parser("discover", help="Find candidate boards; review before adding")
    discovery.add_argument("query", nargs="?")
    discovery.add_argument("--limit", type=int, default=200)
    discovery.add_argument(
        "--seed", action="store_true", help="Persist candidates for daily validation"
    )
    commands.add_parser("refresh-discovery", help="Validate pending candidate boards now")
    backup = commands.add_parser("backup", help="Back up a stopped complete installation")
    backup.add_argument("destination", type=Path)
    backup.add_argument(
        "--data-dir", type=Path, default=Path(os.getenv("PIPELINE_DATA_DIR", "/var/data"))
    )
    restore = commands.add_parser("restore", help="Restore into a new installation directory")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    return cli


def _pipeline(settings: Settings, store: Store) -> Pipeline:
    from internship_pipeline.pipeline import Pipeline

    profile = ProfileSettings(store).read().candidate()
    return Pipeline(settings, profile, store, settings_revision=profile.settings_revision)


def run_worker(settings: Settings, store: Store, role: str, once: bool) -> int:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signum, _frame: stop.set())
    if role == "collector":
        companies = load_companies(settings.companies_path)
        queries = load_searches(settings.searches_path)
        register_targets(store, companies, queries)
    last_reconcile = 0.0
    while not stop.is_set():
        if role == "matcher" and time.monotonic() - last_reconcile > 30:
            from internship_pipeline.assessments import Assessments
            from internship_pipeline.model_connections import ModelConnectionStore

            root = Path(os.getenv("PIPELINE_DATA_DIR", str(settings.database_path.parent)))
            Assessments(
                store, ModelConnectionStore(store.path, root / "model-credentials.key")
            ).reconcile()
            last_reconcile = time.monotonic()
        # Freeze one immutable snapshot for the whole task; the next task reads fresh state.
        if role == "search-runs":
            from internship_pipeline.search_runs import SearchRuns

            worked = asyncio.run(SearchRuns(store).process_next(settings))
        elif role == "tailored-resumes":
            from internship_pipeline.resumes.tailored import TailoredResumes

            service = TailoredResumes(store, settings)
            if time.monotonic() - last_reconcile > 30:
                from internship_pipeline.generation_policy import GenerationPolicies

                GenerationPolicies(service).reconcile()
                last_reconcile = time.monotonic()
            worked = service.process_next()
        elif role == "email-delivery":
            from internship_pipeline.email_integrations import EmailIntegrations
            from internship_pipeline.model_connections import ModelConnectionStore
            from internship_pipeline.resumes.tailored import TailoredResumes

            root = Path(os.getenv("PIPELINE_DATA_DIR", str(settings.database_path.parent)))
            drafts = TailoredResumes(store, settings)

            def pdf(job_id: str, drafts: TailoredResumes = drafts) -> bytes | None:
                value = drafts.latest(job_id)
                return drafts.pdf(value["key"]) if value.get("download_url") else None

            email = EmailIntegrations(
                store,
                ModelConnectionStore(store.path, root / "model-credentials.key"),
                pdf_provider=pdf,
            )
            email.schedule()
            worked = email.process_next()
        elif role == "sheets-sync":
            from internship_pipeline.model_connections import ModelConnectionStore
            from internship_pipeline.sheets_integration import SheetsIntegration

            root = Path(os.getenv("PIPELINE_DATA_DIR", str(settings.database_path.parent)))
            sheets = SheetsIntegration(
                store, ModelConnectionStore(store.path, root / "model-credentials.key")
            )
            sheets.schedule()
            worked = sheets.process_next()
        elif role == "master-resumes":
            from internship_pipeline.resumes.master import MasterResumes

            worked = MasterResumes(store, settings).process_next()
        elif role == "discovery":
            from internship_pipeline.maintenance import refresh_discovery

            asyncio.run(refresh_discovery(store, settings))
            worked = False
        elif role == "collector":
            profile = ProfileSettings(store).read().candidate()
            asyncio.run(collect_due(store, profile, settings))
            worked = False
        else:
            pipeline = _pipeline(settings, store)
            worked = pipeline.process_next(["match"])
        if once:
            break
        if not worked:
            stop.wait(2 if role != "collector" else 5)
    return 0


def _main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in {"backup", "restore"}:
            from internship_pipeline.app import runtime_settings
            from internship_pipeline.operations import backup_installation, restore_installation

            if args.command == "backup":
                config = args.config or args.data_dir / "config/settings.yaml"
                result = backup_installation(
                    args.data_dir, runtime_settings(args.data_dir, config), args.destination
                )
            else:
                result = restore_installation(args.source, args.destination)
            print(json.dumps(result))
            return 0
        if args.command in {"recover-owner", "setup-token", "setup-link"}:
            from internship_pipeline.identity import Identity

            if args.command == "setup-link":
                origin = urlsplit(args.origin)
                if (
                    origin.scheme not in {"https", "http"}
                    or not origin.hostname
                    or origin.username
                    or origin.password
                    or origin.path
                    or origin.query
                    or origin.fragment
                    or (
                        origin.scheme == "http"
                        and origin.hostname not in {"localhost", "127.0.0.1", "::1"}
                    )
                ):
                    raise ValueError("Use an HTTPS origin or a loopback HTTP origin")
                identity = Identity(args.data_dir / "identity.sqlite3")
                token = identity.setup_token(rotate=True)
                print(args.origin + (f"/#setup={token}" if token else "/"))
                return 0
            identity = Identity(args.data_dir / "identity.sqlite3")
            if args.command == "setup-token":
                token = identity.setup_token(rotate=True)
                if token is None:
                    print("Instance already claimed; use recover-owner.")
                    return 2
                print(f"Owner setup token: {token}")
            else:
                username = input("Owner username: ")
                password = getpass.getpass("New password (12–256 characters): ")
                if password != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords differ")
                identity.recover(username, password)
                print("Owner recovered. All previous sessions have been revoked.")
            return 0
        settings = load_settings(args.config)
        store = Store(settings.database_path)
        if args.command == "serve":
            from internship_pipeline.supervisor import run_workers

            return run_workers(args.config)
        if args.command == "status":
            print(json.dumps(store.health(), indent=2))
        elif args.command == "jobs":
            for job in store.list_jobs(args.backlog):
                print(
                    json.dumps(
                        {
                            "id": job.id,
                            "company": job.posting.company,
                            "title": job.posting.title,
                            "status": job.status,
                            "event": job.event,
                            "apply_url": job.posting.apply_url,
                        }
                    )
                )
        elif args.command == "retry":
            count = Queue(store).retry_failed(args.task_id)
            print(f"Queued {count} failed tasks for retry")
        elif args.command == "mark-applied":
            store.mark_applied(args.job_id)
            print(f"Recorded user-submitted application: {args.job_id}")
        elif args.command == "review-backlog":
            profile = ProfileSettings(store).read().candidate()
            print(f"Queued {store.review_backlog(profile.revision)} backlog jobs for review")
        elif args.command == "add-company":
            from internship_pipeline.discovery import validate_company

            company = Company(
                id=args.id, name=args.name, careers_url=args.careers_url, priority=args.priority
            )
            validation = asyncio.run(validate_company(company, settings.request_timeout_seconds))
            if not validation.verified:
                raise ConfigurationError("Board could not be verified; it was not added")
            companies = (
                load_companies(settings.companies_path) if settings.companies_path.exists() else []
            )
            if any(item.id == company.id for item in companies):
                raise ConfigurationError(
                    "Company ID already exists; edit its existing configuration"
                )
            companies.append(company)
            settings.companies_path.parent.mkdir(parents=True, exist_ok=True)
            settings.companies_path.write_text(
                yaml.safe_dump(
                    [item.model_dump(mode="json") for item in companies], sort_keys=False
                )
            )
            register_targets(store, companies, load_searches(settings.searches_path))
            print(f"Added verified company: {company.id}")
        elif args.command == "discover":
            from internship_pipeline.discovery import discover_companies

            companies = discover_companies(args.query, args.limit)
            if args.seed:
                print(f"Stored {store.add_candidates(companies)} candidates for validation")
            else:
                print(yaml.safe_dump([company.model_dump(mode="json") for company in companies]))
        elif args.command == "refresh-discovery":
            from internship_pipeline.maintenance import refresh_discovery

            count = asyncio.run(refresh_discovery(store, settings, force=True))
            print(f"Enabled {count} verified boards; their first scan establishes a backlog")
        elif args.command == "scan":
            pipeline = _pipeline(settings, store)
            register_targets(
                store,
                load_companies(settings.companies_path),
                load_searches(settings.searches_path),
            )
            new = asyncio.run(collect_due(store, pipeline.profile, settings, args.force))
            processed = 0 if args.collect_only else pipeline.drain()
            print(
                json.dumps(
                    {
                        "new_observations": new,
                        "work_items_processed": processed,
                        "health": store.health(),
                    },
                    indent=2,
                )
            )
        elif args.command == "worker":
            from internship_pipeline.operations import installation_lock

            root = Path(os.getenv("PIPELINE_DATA_DIR", str(settings.database_path.parent)))
            with installation_lock(root):
                return run_worker(settings, store, args.role, args.once)
        return 0
    except (ConfigurationError, KeyError, ValueError, OSError, sqlite3.Error) as exc:
        from internship_pipeline.operations import OperationError

        if isinstance(exc, OperationError):
            print(f"Operation failed: {exc}", file=sys.stderr)
        elif isinstance(exc, ConfigurationError):
            print(f"Configuration error: {exc}", file=sys.stderr)
        else:
            print(f"Operation failed: {type(exc).__name__}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    from internship_pipeline.operations import OperationError, installation_lock

    args = parser().parse_args(argv)
    if args.command in {"backup", "restore"}:
        return _main(argv)
    try:
        if args.command in {"recover-owner", "setup-token", "setup-link"}:
            root = args.data_dir
        else:
            settings = load_settings(args.config)
            root = Path(os.getenv("PIPELINE_DATA_DIR", str(settings.database_path.parent)))
        with installation_lock(root, offline=args.command in {"recover-owner", "setup-token"}):
            return _main(argv)
    except (OperationError, ConfigurationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
