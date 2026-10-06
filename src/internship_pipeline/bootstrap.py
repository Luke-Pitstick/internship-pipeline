"""One application process tree; activate configured collection after owner setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from internship_pipeline.app import runtime_settings
from internship_pipeline.config import (
    ConfigurationError,
    load_companies,
    load_searches,
)
from internship_pipeline.identity import Identity
from internship_pipeline.models import Settings
from internship_pipeline.storage import Store
from internship_pipeline.supervisor import supervise


def configured_roles(settings: Settings) -> list[str]:
    """Absent inputs disable only their dependent worker roles."""
    roles = []
    try:
        load_companies(settings.companies_path)
        load_searches(settings.searches_path)
        roles.extend(["collector", "discovery"])
    except ConfigurationError:
        pass
    from internship_pipeline.assessments import current_revisions

    with Store(settings.database_path).connection() as db:
        profile, revision = current_revisions(db)
        if profile:
            roles.append("master-resumes")
        if profile and revision:
            model = db.execute(
                "SELECT deleted FROM model_revisions WHERE revision=?", (revision,)
            ).fetchone()
            test = db.execute(
                "SELECT status FROM model_attempts WHERE revision=? ORDER BY id DESC LIMIT 1",
                (revision,),
            ).fetchone()
            if model and not model[0] and test and test[0] == "success":
                roles.append("matcher")
    return roles


def main() -> int:
    os.umask(0o077)
    root = Path(os.getenv("PIPELINE_DATA_DIR", "/var/data"))
    root.mkdir(parents=True, exist_ok=True)
    config = Path(os.getenv("PIPELINE_CONFIG", str(root / "config/settings.yaml")))
    settings = runtime_settings(root, config)
    Store(settings.database_path)
    identity = Identity(root / "identity.sqlite3")
    if token := identity.setup_token():
        print(f"Owner setup token: {token}", flush=True)
    roles = configured_roles(settings) if identity.claimed() else []
    print(
        f"Starting application; active workers: {', '.join(roles) or 'none (setup mode)'}",
        flush=True,
    )
    status_path = root / "supervisor.json"
    os.environ["PIPELINE_SUPERVISOR_STATUS"] = str(status_path)
    commands = {
        "web": [
            sys.executable,
            "-m",
            "uvicorn",
            "internship_pipeline.app:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            os.getenv("PORT", "8080"),
            "--no-proxy-headers",
            "--no-access-log",
        ]
    }

    def current_commands() -> dict[str, list[str]]:
        result = dict(commands)
        active = configured_roles(settings) if identity.claimed() else []
        for role in active:
            command = [sys.executable, "-m", "internship_pipeline.cli"]
            if config.is_file():
                command.extend(["--config", str(config)])
            command.extend(["worker", role])
            result[role] = command
        return result

    # Share the exact infrastructure paths with CLI children even on a fresh volume.
    os.environ["PIPELINE_DATABASE_PATH"] = str(settings.database_path)
    os.environ["PIPELINE_ARTIFACT_DIR"] = str(settings.artifact_dir)
    os.environ["PIPELINE_COMPANIES_PATH"] = str(settings.companies_path)
    return supervise(commands, status_path=status_path, command_provider=current_commands)


if __name__ == "__main__":
    raise SystemExit(main())
