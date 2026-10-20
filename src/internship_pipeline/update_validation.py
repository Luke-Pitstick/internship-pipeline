"""Validate an update copy and serve readiness without admitting application work."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from internship_pipeline.operations import (
    OperationError,
    _credentials,
    _verify_database,
    installation_lock,
    verify_backup,
)


def validate(root: Path) -> None:
    """Verify restored records and retained files against the complete source snapshot."""
    manifest = verify_backup(root.parent / "backup")
    for name in ("state.sqlite3", "identity.sqlite3"):
        with sqlite3.connect((root / name).resolve().as_uri() + "?mode=ro", uri=True) as db:
            _verify_database(db, name)
    _credentials(root)
    for name, expected in manifest["files"].items():
        # Restore deliberately rewrites configuration and reconciles work/sessions in SQLite.
        if name in {"state.sqlite3", "identity.sqlite3", "config/settings.yaml"}:
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise OperationError("Restored update copy is missing a retained file.")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected["sha256"]:
                raise OperationError("Restored update file differs from the source snapshot.")
    # Parse the rewritten settings without initializing any application component or worker.
    from internship_pipeline.config import load_settings

    settings = load_settings(root / "config/settings.yaml")
    if (
        settings.database_path != root / "state.sqlite3"
        or settings.artifact_dir != root / "artifacts"
    ):
        raise OperationError("Restored update configuration points outside the candidate data.")


async def check_application(root: Path) -> None:
    """Initialize the real app and check readiness in-process, without its lifespan.

    This is invoked only by the network-disabled preflight container. Feature
    stores may initialize lazy tables on the candidate copy; no supervisor,
    collection, inference, delivery worker, or interactive route is started.
    """
    import httpx

    from internship_pipeline.app import create_app
    from internship_pipeline.config import load_settings
    from internship_pipeline.profile_settings import ProfileSettings
    from internship_pipeline.storage import Store

    settings = load_settings(root / "config/settings.yaml")
    origin = os.environ.get("PIPELINE_ORIGIN", "http://localhost:8080")
    app = create_app(root, origin=origin, settings=settings)
    ProfileSettings(Store(settings.database_path)).read()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        response = await client.get("/readyz")
    if response.status_code != 200 or response.json() not in (
        {"ready": True, "mode": "owner"},
        {"ready": True, "mode": "setup"},
    ):
        raise OperationError("Updated application is not ready against the candidate data.")


class Readiness(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/readyz":
            self.send_error(503, "Update validation in progress")
            return
        body = json.dumps({"ready": True, "mode": "update-validation"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify offline and exit")
    args = parser.parse_args()
    root = Path(os.environ["PIPELINE_DATA_DIR"])
    if root != Path("/var/data/restored"):
        raise OperationError("Update validation requires the restored candidate root.")
    with installation_lock(root, offline=True):
        validate(root)
    if args.check:
        # Explicitly upgrade only the isolated candidate, before application preflight.
        from internship_pipeline.identity import Identity
        from internship_pipeline.storage import Store

        with installation_lock(root, offline=True):
            Store(root / "state.sqlite3")
            Identity(root / "identity.sqlite3")
        asyncio.run(check_application(root))
        with installation_lock(root, offline=True):
            validate(root)
    else:
        with (
            installation_lock(root, offline=True),
            HTTPServer(("0.0.0.0", 8080), Readiness) as server,
        ):
            server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
