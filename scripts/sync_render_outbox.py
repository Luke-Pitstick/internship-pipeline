#!/usr/bin/env python3
"""Pull Render events for the local Dot relay, without modifying Render or relay state.

Usage: python3 scripts/sync_render_outbox.py --ssh-address USER@ssh.REGION.render.com
The Render dashboard supplies the SSH address. SSH uses the user's normal keys and
known_hosts; first connections record the server key and changed keys are rejected.
Only complete JSON events and PDFs under /var/data/artifacts are transferred. Each
page has at most 100 events and 32 MiB of PDF content; PDFs are capped at 10 MiB.
Attachments are committed before their event, and conflicting IDs fail closed.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_EVENTS = 100
MAX_EVENT_BYTES = 64 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_WIRE_BYTES = 48 * 1024 * 1024
EVENT_ID = re.compile(r"[a-f0-9]{64}")
SSH_ADDRESS = re.compile(r"[a-zA-Z0-9_-]+@ssh\.[a-z0-9-]+\.render\.com")

# This program is fixed trusted code, sent on stdin. Remote event text is never code.
REMOTE_SCRIPT = r'''
import base64, json, os, re, stat, sys
from pathlib import Path

MAX_EVENTS = 100
MAX_EVENT_BYTES = 65536
MAX_PDF_BYTES = 10485760
MAX_PAGE_BYTES = 33554432
root = Path("/var/data/dot-outbox")
artifacts = Path("/var/data/artifacts")
if artifacts.is_symlink():
    raise ValueError("Artifact directory cannot be a symlink")
artifacts = artifacts.resolve(strict=True)
cursor = sys.argv[1]
if cursor and not re.fullmatch(r"[a-f0-9]{64}", cursor):
    raise ValueError("Invalid page cursor")

def read_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise ValueError("Invalid file type or size")
        content = source.read(maximum + 1)
        if not 0 < len(content) <= maximum:
            raise ValueError("Invalid file size")
        return content

if root.is_symlink():
    raise ValueError("Outbox cannot be a symlink")
names = sorted(path.name for path in root.glob("*.json"))
if len(names) > 100000:
    raise ValueError("Too many outbox files")
events, total, next_cursor, done = [], 0, cursor, True
for name in names:
    event_id = name[:-5]
    if not re.fullmatch(r"[a-f0-9]{64}", event_id):
        raise ValueError("Invalid event filename")
    if event_id <= cursor:
        continue
    if len(events) >= MAX_EVENTS:
        done = False
        break
    payload = json.loads(read_regular(root / name, MAX_EVENT_BYTES))
    if not isinstance(payload, dict) or payload.get("id") != event_id:
        raise ValueError("Event ID does not match filename")
    attachment = payload.get("attachment")
    pdf = None
    if attachment is not None:
        if not isinstance(attachment, str) or not attachment.startswith("/"):
            raise ValueError("Attachment must have an absolute path")
        path = Path(attachment).resolve(strict=True)
        if not path.is_relative_to(artifacts) or path.suffix.lower() != ".pdf":
            raise ValueError("Attachment is outside the artifact directory")
        pdf = read_regular(path, MAX_PDF_BYTES)
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("Attachment is not a PDF")
        if events and total + len(pdf) > MAX_PAGE_BYTES:
            done = False
            break
        total += len(pdf)
    events.append({"payload": payload,
                   "pdf": base64.b64encode(pdf).decode("ascii") if pdf else None})
    next_cursor = event_id
print(json.dumps({"events": events, "next_cursor": next_cursor, "done": done}))
'''


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "id", "created_at", "title", "body", "attachment", "status"
    }:
        raise ValueError("Invalid event fields")
    if not isinstance(payload["id"], str) or not EVENT_ID.fullmatch(payload["id"]):
        raise ValueError("Invalid event ID")
    for field in ("created_at", "title", "body"):
        if not isinstance(payload[field], str):
            raise ValueError(f"Invalid event {field}")
    if len(payload["created_at"]) > 128:
        raise ValueError("Invalid event timestamp")
    datetime.fromisoformat(payload["created_at"])
    if payload["status"] != "awaiting_dot_relay":
        raise ValueError("Invalid event status")
    if len(json.dumps(payload).encode()) > MAX_EVENT_BYTES:
        raise ValueError("Event exceeds size limit")
    return payload


def decode_page(raw: bytes, cursor: str) -> tuple[list[tuple[dict[str, Any], bytes | None]],
                                                  str, bool]:
    if len(raw) > MAX_WIRE_BYTES:
        raise ValueError("Remote response exceeds size limit")
    page = json.loads(raw)
    if not isinstance(page, dict) or set(page) != {"events", "next_cursor", "done"}:
        raise ValueError("Invalid remote page")
    if not isinstance(page["events"], list) or len(page["events"]) > MAX_EVENTS:
        raise ValueError("Invalid event count")
    if type(page["done"]) is not bool:
        raise ValueError("Invalid page completion flag")
    decoded, total, last = [], 0, cursor
    for entry in page["events"]:
        if not isinstance(entry, dict) or set(entry) != {"payload", "pdf"}:
            raise ValueError("Invalid remote event")
        payload = validate_payload(entry["payload"]).copy()
        if payload["id"] <= last:
            raise ValueError("Events must have unique IDs in increasing order")
        last = payload["id"]
        pdf = None
        attachment = payload["attachment"]
        if attachment is not None:
            if not isinstance(attachment, str) or not attachment.startswith("/"):
                raise ValueError("Invalid remote attachment path")
            path = Path(attachment)
            if not path.is_relative_to("/var/data/artifacts") or ".." in path.parts:
                raise ValueError("Remote attachment is outside the artifact directory")
            if path.suffix.lower() != ".pdf" or not isinstance(entry["pdf"], str):
                raise ValueError("Invalid remote PDF")
            if len(entry["pdf"]) > (MAX_PDF_BYTES + 2) // 3 * 4:
                raise ValueError("PDF exceeds size limit")
            try:
                pdf = base64.b64decode(entry["pdf"], validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError("Invalid PDF encoding") from error
            if not pdf.startswith(b"%PDF-") or len(pdf) > MAX_PDF_BYTES:
                raise ValueError("Invalid PDF content or size")
            total += len(pdf)
            payload["attachment"] = f"artifacts/render/{payload['id']}.pdf"
        elif entry["pdf"] is not None:
            raise ValueError("Unexpected PDF without attachment")
        decoded.append((payload, pdf))
    if total > MAX_PAGE_BYTES:
        raise ValueError("Page exceeds PDF size limit")
    if page["next_cursor"] != last or (not page["done"] and not decoded):
        raise ValueError("Remote cursor did not advance")
    return decoded, last, page["done"]


def check_path(repo: Path, relative: str) -> Path:
    path = repo
    for component in Path(relative).parts:
        path /= component
        if path.is_symlink():
            raise ValueError(f"Local sync path is a symlink: {relative}")
    return path


def check_existing(path: Path, content: bytes, *, event: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"Local destination is a symlink: {path.name}")
    if not path.exists():
        return
    if not path.is_file() or path.stat().st_size > (MAX_EVENT_BYTES if event else MAX_PDF_BYTES):
        raise ValueError(f"Invalid existing file: {path.name}")
    existing = path.read_bytes()
    matches = json.loads(existing) == json.loads(content) if event else existing == content
    if not matches:
        raise ValueError(f"Conflicting existing event or PDF: {path.name}")


def publish(path: Path, content: bytes, *, event: bool = False) -> bool:
    check_existing(path, content, event=event)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            check_existing(path, content, event=event)
            return False
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_page(repo: Path, entries: list[tuple[dict[str, Any], bytes | None]]) -> int:
    """Validate all existing destinations before publishing any complete events."""
    staged = []
    for payload, pdf in entries:
        event = check_path(repo, f"data/dot-outbox/{payload['id']}.json")
        content = json.dumps(payload, sort_keys=True).encode()
        check_existing(event, content, event=True)
        attachment = check_path(repo, payload["attachment"]) if pdf is not None else None
        if attachment is not None and pdf is not None:
            check_existing(attachment, pdf)
        staged.append((event, content, attachment, pdf))
    count = 0
    for event, content, attachment, pdf in staged:
        if attachment is not None and pdf is not None:
            publish(attachment, pdf)
        count += publish(event, content, event=True)
    return count


def fetch_page(address: str, cursor: str) -> bytes:
    if not SSH_ADDRESS.fullmatch(address):
        raise ValueError("Expected USER@ssh.REGION.render.com SSH address")
    if cursor and not EVENT_ID.fullmatch(cursor):
        raise ValueError("Invalid page cursor")
    # SSH joins remote arguments into a shell command; every token here is fixed
    # except the strictly hex cursor, so event content cannot enter that command.
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "StrictHostKeyChecking=accept-new", "--", address,
               "python3", "-", cursor or "''"]
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, input=REMOTE_SCRIPT.encode(), stdout=output,
                                stderr=subprocess.PIPE, timeout=90, check=False)
        if result.returncode:
            # Remote stderr may include untrusted filenames. Keep it out of Dot.
            raise RuntimeError(f"Render SSH transfer failed (exit {result.returncode})")
        output.seek(0, os.SEEK_END)
        if output.tell() > MAX_WIRE_BYTES:
            raise ValueError("Remote response exceeds size limit")
        output.seek(0)
        return output.read(MAX_WIRE_BYTES + 1)


def sync(repo: Path, address: str) -> int:
    repo = repo.resolve(strict=True)
    cursor, count = "", 0
    while True:
        entries, cursor, done = decode_page(fetch_page(address, cursor), cursor)
        count += install_page(repo, entries)
        if done:
            return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-address", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    try:
        count = sync(arguments.repo, arguments.ssh_address)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Render outbox sync failed: {error}\n")
    print(f"Synced {count} new Render event(s).")


if __name__ == "__main__":
    main()
