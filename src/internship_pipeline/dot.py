"""Atomic local handoff to a separately configured Codex thread heartbeat."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from internship_pipeline.models import utcnow


def write_notification(
    directory: Path,
    key: str,
    title: str,
    body: str,
    attachment: Path | None = None,
) -> bool:
    """Accept a stable event into an outbox; this does not claim the user saw it."""
    directory.mkdir(parents=True, exist_ok=True)
    event_id = hashlib.sha256(key.encode()).hexdigest()
    destination = directory / f"{event_id}.json"
    if destination.exists():
        return True
    if attachment is not None and (not attachment.is_file() or not attachment.stat().st_size):
        return False
    payload = {
        "id": event_id,
        "created_at": utcnow().isoformat(),
        "title": title,
        "body": body,
        "attachment": str(attachment) if attachment is not None else None,
        "status": "awaiting_dot_relay",
    }
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as output:
            temporary = output.name
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return True
