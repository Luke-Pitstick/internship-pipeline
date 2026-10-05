"""Command line entry points for local operation and independent workers."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from internship_pipeline.collection import collect_due, register_targets
from internship_pipeline.config import (
    ConfigurationError,
    load_companies,
    load_profile,
    load_searches,
    load_settings,
)
from internship_pipeline.models import Company, Settings
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
        "role", choices=["collector", "matcher", "resumes", "delivery", "discovery"]
    )
    worker.add_argument(
        "--once", action="store_true", help="Process at most one available work item"
    )
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
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("destination", type=Path)
    demo = commands.add_parser(
        "demo", help="Run a synthetic offline example; sends no external messages"
    )
    demo.add_argument("--directory", type=Path, default=Path("data/demo"))
    return cli


def _pipeline(settings: Settings, store: Store) -> Pipeline:
    from internship_pipeline.pipeline import Pipeline

    profile = load_profile(settings.profile_path)
    return Pipeline(settings, profile, store)


def _require_destination(settings: Settings) -> None:
    if not settings.notification_urls and settings.recording_notifications_path is None:
        raise ConfigurationError(
            "Configure notification_urls or an explicit recording_notifications_path first"
        )


def run_worker(settings: Settings, store: Store, role: str, once: bool) -> int:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signum, _frame: stop.set())
    _require_destination(settings)
    pipeline = _pipeline(settings, store)
    if role == "collector":
        companies = load_companies(settings.companies_path)
        queries = load_searches(settings.searches_path)
        register_targets(store, companies, queries)
    kinds = {"matcher": ["match"], "resumes": ["resume"], "delivery": ["delivery"]}
    while not stop.is_set():
        if role == "discovery":
            from internship_pipeline.maintenance import refresh_discovery

            asyncio.run(refresh_discovery(store, settings))
            worked = False
        elif role == "collector":
            asyncio.run(collect_due(store, pipeline.profile, settings))
            worked = False
        else:
            worked = pipeline.process_next(kinds[role])
        if once:
            break
        if not worked:
            stop.wait(2 if role != "collector" else 5)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            from internship_pipeline.demo import run_demo

            print(json.dumps(run_demo(args.directory), indent=2))
            return 0
        settings = load_settings(args.config)
        store = Store(settings.database_path)
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
        elif args.command == "backup":
            store.backup(args.destination)
            print(f"Database backup saved: {args.destination}")
        elif args.command == "mark-applied":
            store.mark_applied(args.job_id)
            print(f"Recorded user-submitted application: {args.job_id}")
        elif args.command == "review-backlog":
            profile = load_profile(settings.profile_path)
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
            _require_destination(settings)
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
            return run_worker(settings, store, args.role, args.once)
        return 0
    except (ConfigurationError, KeyError, ValueError) as exc:
        if isinstance(exc, ConfigurationError):
            print(f"Configuration error: {exc}", file=sys.stderr)
        else:
            print(f"Operation failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
