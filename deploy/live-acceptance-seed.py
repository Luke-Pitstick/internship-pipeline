#!/usr/bin/env python3
"""Seed a fresh, isolated two-job acceptance instance without provider I/O.

This deliberately stages a synthetic saved-fetch checkpoint. The production
SearchRuns worker consumes it, so jobs retain normal ingestion/run identities
and later paid model work is subject to the real per-run admission limits.
It is preparation evidence, never evidence of a public ATS request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from internship_pipeline.models import FetchResult, Settings, SourceJob
from internship_pipeline.operations import installation_lock
from internship_pipeline.search_runs import Pause, SearchRuns, SourceSave
from internship_pipeline.storage import Store


def prepare(root: Path, max_tokens: int) -> dict[str, Any]:
    # Validate before creating anything. Never reuse an operator installation.
    source = SourceSave(
        expected_revision=0,
        name="Synthetic live integration acceptance",
        source="greenhouse",
        board="synthetic-acceptance",
        daily_at=None,
        max_jobs=2,
        max_calls=4,
        max_tokens=max_tokens,
    )
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ValueError("Destination must be a new or empty isolated directory.")
    if root.exists() and root.stat().st_uid != os.getuid():
        raise ValueError("Destination must be owned by the acceptance operator.")
    root.mkdir(mode=0o700, parents=False, exist_ok=True)
    root.chmod(0o700)
    previous_umask = os.umask(0o077)
    try:
        return _seed(root, source)
    finally:
        os.umask(previous_umask)


def _seed(root: Path, source: SourceSave) -> dict[str, Any]:
    marker = root / ".synthetic-live-acceptance"
    with marker.open("x") as handle:
        handle.write("Synthetic source checkpoint; no public collection or provider calls.\n")
    with installation_lock(root, offline=True):
        # Explicit paths also prevent ambient operator environment overrides from
        # redirecting this seed into a different installation.
        settings = Settings(
            database_path=root / "state.sqlite3",
            artifact_dir=root / "artifacts",
            companies_path=root / "config/companies.yaml",
        )
        store = Store(settings.database_path)
        runs = SearchRuns(store)
        saved = runs.save(source)["searches"][0]
        run_id = runs.start(saved["id"], review_backlog=True)["run"]["id"]
        result = FetchResult(
            jobs=[
                SourceJob(
                    source="greenhouse",
                    board_id="synthetic-acceptance",
                    source_id=f"synthetic-{number}",
                    company="Synthetic Acceptance Labs",
                    title=title,
                    description=description,
                    apply_url=f"https://example.test/acceptance/{number}",
                    locations=["Remote"],
                )
                for number, title, description in (
                    (
                        1,
                        "Synthetic Python API Internship",
                        "Internship for a Computer Science student graduating in May 2027. "
                        "Use Python and SQL to build survey APIs. Remote work. "
                        "No citizenship or work authorization requirement is stated.",
                    ),
                    (
                        2,
                        "Synthetic Dashboard Internship",
                        "Internship for a Computer Science student graduating in May 2027. "
                        "Build accessible dashboards using React and TypeScript. Remote work. "
                        "No citizenship or work authorization requirement is stated.",
                    ),
                )
            ]
        )
        # Seed only the durable fetch boundary; production ingestion/checkpointing
        # below creates job IDs and search_run_jobs without a replacement client.
        with store.transaction() as db:
            db.execute(
                "UPDATE search_runs SET stage='fetched',result=?,collected_at=? WHERE id=?",
                (result.model_dump_json(), time.time(), run_id),
            )
        if not asyncio.run(runs.process_next(settings)):
            raise RuntimeError("Synthetic checkpoint was not consumed.")
        runs.pause(saved["id"], Pause(expected_revision=1, paused=True))
        jobs = store.list_jobs()
        if len(jobs) != 2:
            raise RuntimeError("Expected exactly two isolated synthetic jobs.")
        report = {
            "scope": "synthetic-seed-only-no-provider-I/O",
            "search_id": saved["id"],
            "run_id": run_id,
            "job_ids": {job.posting.source_id: job.id for job in jobs},
            "budgets": {"max_jobs": 2, "max_calls": 4, "max_tokens": source.max_tokens},
            "source_paused": True,
            "public_source_verified": False,
        }
        (root / "synthetic-acceptance-seed.json").write_text(json.dumps(report, indent=2) + "\n")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, required=True,
                        help="Owner-approved local reservation limit, not a billing cap")
    args = parser.parse_args()
    try:
        report = prepare(args.data_dir, args.max_tokens)
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f"Preparation refused: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
