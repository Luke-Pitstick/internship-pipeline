"""Resumable setup checkpoints around the authoritative settings and workers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Literal

from pydantic import Field

from internship_pipeline.email_integrations import EmailIntegrations
from internship_pipeline.generation_policy import read_policy
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Record
from internship_pipeline.profile_settings import ProfileSettings
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.sheets_integration import SheetsIntegration
from internship_pipeline.storage import Store

Step = Literal["models", "profile", "filters", "search", "integrations", "review", "results"]
Choice = Literal["skip", "connect"]
STEPS = ("models", "profile", "filters", "search", "integrations", "review", "results")


class Checkpoint(Record):
    step: Step
    defer_models: bool = False
    email: Choice | None = None
    sheets: Choice | None = None


class Start(Record):
    preview: str = Field(min_length=64, max_length=64)
    search_id: str = Field(min_length=1, max_length=100)


class Onboarding:
    def __init__(
        self,
        store: Store,
        models: ModelConnectionStore,
        email: EmailIntegrations,
        sheets: SheetsIntegration,
    ):
        self.store, self.models, self.email, self.sheets = store, models, email, sheets
        self.profiles, self.searches = ProfileSettings(store), SearchRuns(store)
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS onboarding_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO onboarding_state VALUES(1,?)",
                (
                    json.dumps(
                        {
                            "step": "models",
                            "reviewed": [],
                            "defer_models": False,
                            "email": None,
                            "sheets": None,
                            "run_id": None,
                            "complete": False,
                        }
                    ),
                ),
            )

    @staticmethod
    def _state(db: sqlite3.Connection) -> dict[str, Any]:
        state: dict[str, Any] = json.loads(
            db.execute("SELECT data FROM onboarding_state WHERE id=1").fetchone()[0]
        )
        return state

    @staticmethod
    def _write(db: sqlite3.Connection, state: dict[str, Any]) -> None:
        db.execute("UPDATE onboarding_state SET data=? WHERE id=1", (json.dumps(state),))

    def view(self) -> dict[str, Any]:
        with self.store.connection() as db:
            state = self._state(db)
            has_jobs = bool(db.execute("SELECT EXISTS(SELECT 1 FROM jobs)").fetchone()[0])
            generation_revision, generation = read_policy(db)
            email_test = db.execute(
                "SELECT status FROM email_deliveries WHERE revision="
                "(SELECT revision FROM email_config WHERE id=1) AND title=? "
                "ORDER BY created DESC LIMIT 1",
                ("Internship Pipeline test",),
            ).fetchone()
            email_latest = db.execute(
                "SELECT status FROM email_deliveries WHERE revision="
                "(SELECT revision FROM email_config WHERE id=1) ORDER BY created DESC LIMIT 1"
            ).fetchone()
        profile = self.profiles.read()
        models = self.models.summary()
        searches = self.searches.settings()["searches"]
        email, sheets = self.email.summary(), self.sheets.summary()
        model_status = {
            kind: "ready"
            if item["ready"]
            else "failed"
            if item["configured"]
            and item["last_test"]
            and item["last_test"]["status"] not in {"success", "pending"}
            else "incomplete"
            for kind, item in models.items()
        }
        email_status = "incomplete"
        if email["config"] and email_test:
            email_status = (
                "ready"
                if email_test[0] == "accepted"
                else ("failed" if email_test[0] in {"failed", "uncertain"} else "incomplete")
            )
        sheets_status = "ready" if sheets["tested"] else "incomplete"
        if email_latest and email_latest[0] in {"failed", "uncertain"}:
            email_status = "failed"
        if sheets["last_test"] == "failed":
            sheets_status = "failed"
        if (
            sheets["runs"]
            and sheets["runs"][0]["revision"] == sheets["revision"]
            and sheets["runs"][0]["state"] in {"failed", "conflict", "uncertain"}
        ):
            sheets_status = "failed"
        preview = {
            "profile_revision": profile.revision,
            "confirmed_facts": len(profile.candidate().facts),
            "profile": profile.profile.model_dump(mode="json"),
            "preferences": profile.preferences.model_dump(mode="json"),
            "models": {
                kind: {
                    "revision": item["revision"],
                    "status": model_status[kind],
                    "model": item["config"]["model"] if item["config"] else None,
                }
                for kind, item in models.items()
            },
            "searches": [
                {
                    key: value
                    for key, value in search.items()
                    if key not in {"last_success", "next_run"}
                }
                for search in searches
            ],
            "generation": {"revision": generation_revision, **generation.model_dump()},
            "email": {
                "choice": state["email"],
                "revision": email["revision"],
                "status": email_status,
                "enabled": bool(email["config"] and email["config"]["enabled"]),
            },
            "sheets": {
                "choice": state["sheets"],
                "revision": sheets["revision"],
                "status": sheets_status,
                "enabled": bool(sheets["config"] and sheets["config"]["enabled"]),
            },
            "defer_models": state["defer_models"],
        }
        token = hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()
        blockers = []
        for step in STEPS[:5]:
            if step not in state["reviewed"]:
                blockers.append({"step": step, "message": "Review this setup step before running."})
        if not profile.revision:
            blockers.append(
                {
                    "step": "profile",
                    "message": "Save your reviewed profile, including unknown fields.",
                }
            )
        if not any(not search["paused"] for search in searches):
            blockers.append({"step": "search", "message": "Save and resume at least one search."})
        if not state["defer_models"] and any(status != "ready" for status in model_status.values()):
            blockers.append(
                {"step": "models", "message": "Test both models or explicitly defer model work."}
            )
        for name, status in (("email", email_status), ("sheets", sheets_status)):
            if state[name] is None or (state[name] == "connect" and status != "ready"):
                blockers.append(
                    {"step": "integrations", "message": f"Choose skip or finish testing {name}."}
                )
        run = self.searches.view(state["run_id"])["run"] if state["run_id"] else None
        return {
            **state,
            "preview": preview,
            "preview_token": token,
            "blockers": blockers,
            "run": run,
            "has_jobs": has_jobs,
        }

    def checkpoint(self, body: Checkpoint) -> dict[str, Any]:
        with self.store.transaction() as db:
            state = self._state(db)
            if body.step == "models":
                state["defer_models"] = body.defer_models
            if body.step == "integrations":
                if body.email is None or body.sheets is None:
                    raise ValueError("Choose connect or skip for both integrations.")
                state["email"], state["sheets"] = body.email, body.sheets
            if body.step not in state["reviewed"] and body.step in STEPS[:5]:
                state["reviewed"].append(body.step)
            state["step"] = STEPS[min(STEPS.index(body.step) + 1, len(STEPS) - 1)]
            self._write(db, state)
        return self.view()

    def visit(self, step: Step) -> dict[str, Any]:
        with self.store.transaction() as db:
            state = self._state(db)
            state["step"] = step
            self._write(db, state)
        return self.view()

    def start(self, body: Start) -> dict[str, Any]:
        with self.store.transaction() as db:
            current = self.view()
            if current["blockers"]:
                raise ValueError(current["blockers"][0]["message"])
            if current["preview_token"] != body.preview:
                raise ValueError(
                    "Settings changed. Review the current configuration before running."
                )
            state = self._state(db)
            # A replay never starts another run; an owner must explicitly return to review.
            if state["run_id"] and state["step"] == "results":
                return self.view()
            run_id = self.searches._start(db, body.search_id, False, time.time())
            state["run_id"], state["step"] = run_id, "results"
            state["complete"] = False
            self._write(db, state)
        return self.view()

    def finish(self) -> dict[str, Any]:
        with self.store.transaction() as db:
            view = self.view()
            if not view["run"] or not view["run"]["collected"]:
                raise ValueError("Wait for an observed job or correct the search and run it again.")
            state = self._state(db)
            state["complete"] = True
            self._write(db, state)
        return self.view()
