import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync_render_outbox.py"
SPEC = importlib.util.spec_from_file_location("render_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
render_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_sync)


def payload(event_id: str = "a" * 64, attachment: str | None = None) -> dict:
    return {"id": event_id, "created_at": "2026-10-05T00:00:00+00:00", "title": "Opening",
            "body": "Untrusted $(touch /tmp/nope); `whoami`", "attachment": attachment,
            "status": "awaiting_dot_relay"}


def page(events: list[dict], *, done: bool = True) -> bytes:
    return json.dumps({"events": events, "next_cursor": events[-1]["payload"]["id"]
                       if events else "", "done": done}).encode()


def entry(event_id: str = "a" * 64, attachment: str | None = None) -> dict:
    return {"payload": payload(event_id, attachment),
            "pdf": base64.b64encode(b"%PDF-1.7\nsynthetic\n").decode() if attachment else None}


def test_sync_preserves_relay_state_and_is_idempotent(tmp_path, monkeypatch):
    state = tmp_path / "data/dot-relay-state.json"
    state.parent.mkdir()
    state.write_text('{"seen": ["old-event"]}')
    raw = page([entry(attachment="/var/data/artifacts/resume.pdf")])
    monkeypatch.setattr(render_sync, "fetch_page", lambda address, cursor: raw)
    assert render_sync.sync(tmp_path, "unused") == 1
    event = tmp_path / f"data/dot-outbox/{'a' * 64}.json"
    data = json.loads(event.read_text())
    assert data["body"] == payload()["body"]
    assert data["attachment"] == f"artifacts/render/{'a' * 64}.pdf"
    assert (tmp_path / data["attachment"]).read_bytes().startswith(b"%PDF-")
    assert render_sync.sync(tmp_path, "unused") == 0
    assert state.read_text() == '{"seen": ["old-event"]}'


def test_pagination_does_not_starve_later_events(tmp_path, monkeypatch):
    pages = {"": page([entry("a" * 64)], done=False),
             "a" * 64: page([entry("b" * 64)])}
    monkeypatch.setattr(render_sync, "fetch_page", lambda address, cursor: pages[cursor])
    assert render_sync.sync(tmp_path, "unused") == 2
    assert len(list((tmp_path / "data/dot-outbox").glob("*.json"))) == 2


@pytest.mark.parametrize("attachment", ["/etc/passwd.pdf", "relative.pdf",
                                        "/var/data/artifacts/../../secret.pdf"])
def test_unsafe_remote_attachment_is_rejected(attachment):
    with pytest.raises(ValueError):
        render_sync.decode_page(page([entry(attachment=attachment)]), "")


@pytest.mark.parametrize("mutation", [
    lambda event: event["payload"].update(id="../../escape"),
    lambda event: event["payload"].update(status="delivered"),
    lambda event: event["payload"].update(body={"command": "touch /tmp/nope"}),
    lambda event: event.update(pdf="invalid!"),
    lambda event: event.update(pdf=base64.b64encode(b"not a PDF").decode()),
    lambda event: event["payload"].update(attachment=None),
])
def test_invalid_event_or_pdf_is_rejected(mutation):
    event = entry(attachment="/var/data/artifacts/resume.pdf")
    mutation(event)
    with pytest.raises(ValueError):
        render_sync.decode_page(page([event]), "")


def test_bundle_limits_and_cursor_validation(monkeypatch):
    with pytest.raises(ValueError):
        render_sync.decode_page(page([entry()] * 101), "")
    with pytest.raises(ValueError):
        render_sync.decode_page(page([], done=False), "")
    monkeypatch.setattr(render_sync, "MAX_PDF_BYTES", 5)
    with pytest.raises(ValueError):
        render_sync.decode_page(page([entry(attachment="/var/data/artifacts/a.pdf")]), "")


@pytest.mark.parametrize("conflict", ["event", "pdf"])
def test_conflicting_existing_files_are_never_overwritten(tmp_path, conflict):
    entries, _, _ = render_sync.decode_page(
        page([entry(attachment="/var/data/artifacts/resume.pdf")]), "")
    assert render_sync.install_page(tmp_path, entries) == 1
    destination = tmp_path / (f"data/dot-outbox/{'a' * 64}.json" if conflict == "event"
                              else f"artifacts/render/{'a' * 64}.pdf")
    if conflict == "event":
        changed = json.loads(destination.read_text())
        changed["body"] = "different body"
        destination.write_text(json.dumps(changed))
    else:
        destination.write_bytes(b"%PDF-different")
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="Conflicting"):
        render_sync.install_page(tmp_path, entries)
    assert destination.read_bytes() == before


def test_local_symlink_cannot_escape_repository(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "artifacts").symlink_to(outside, target_is_directory=True)
    entries, _, _ = render_sync.decode_page(
        page([entry(attachment="/var/data/artifacts/resume.pdf")]), "")
    with pytest.raises(ValueError, match="symlink"):
        render_sync.install_page(repo, entries)
    assert list(outside.iterdir()) == []
    assert not (repo / "data").exists()


def test_pdf_exists_before_event_becomes_visible(tmp_path, monkeypatch):
    original = render_sync.publish

    def observe(path, content, *, event=False):
        if event:
            attachment = json.loads(content)["attachment"]
            assert (tmp_path / attachment).is_file()
        return original(path, content, event=event)

    monkeypatch.setattr(render_sync, "publish", observe)
    entries, _, _ = render_sync.decode_page(
        page([entry(attachment="/var/data/artifacts/resume.pdf")]), "")
    assert render_sync.install_page(tmp_path, entries) == 1


@pytest.mark.parametrize("address", ["-oProxyCommand=bad", "user@evil.example",
                                    "user@ssh.oregon.render.com;bad"])
def test_ssh_address_cannot_inject_options_or_commands(address):
    with pytest.raises(ValueError):
        render_sync.fetch_page(address, "")


def run_remote(tmp_path: Path) -> subprocess.CompletedProcess:
    # Exercise exactly the shipped remote program with synthetic directories.
    program = render_sync.REMOTE_SCRIPT.replace("/var/data", str(tmp_path))
    return subprocess.run([sys.executable, "-", ""], input=program.encode(),
                          capture_output=True, check=False)


@pytest.mark.parametrize("unsafe", ["outside", "symlink", "missing", "empty", "event_symlink"])
def test_remote_program_rejects_unsafe_or_incomplete_files(tmp_path, unsafe):
    outbox = tmp_path / "dot-outbox"
    outbox.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"%PDF-1.7\nsynthetic\n")
    pdf = artifacts / "resume.pdf"
    if unsafe == "outside":
        pdf = outside
    elif unsafe == "symlink":
        pdf.symlink_to(outside)
    elif unsafe == "empty":
        pdf.touch()
    event = outbox / f"{'a' * 64}.json"
    event.write_text(json.dumps(payload(attachment=str(pdf))))
    if unsafe == "event_symlink":
        pdf.write_bytes(b"%PDF-synthetic")
        event.unlink()
        external_event = tmp_path / "external.json"
        external_event.write_text(json.dumps(payload(attachment=str(pdf))))
        event.symlink_to(external_event)
    result = run_remote(tmp_path)
    assert result.returncode != 0
    assert result.stdout == b""


def test_remote_program_transfers_complete_pdf(tmp_path):
    outbox, artifacts = tmp_path / "dot-outbox", tmp_path / "artifacts"
    outbox.mkdir()
    artifacts.mkdir()
    pdf = artifacts / "resume.pdf"
    content = b"%PDF-1.7\nsynthetic\n"
    pdf.write_bytes(content)
    (outbox / f"{'a' * 64}.json").write_text(json.dumps(payload(attachment=str(pdf))))
    (outbox / "unfinished-temporary-file").write_text("partial JSON")
    result = run_remote(tmp_path)
    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["done"] is True
    assert base64.b64decode(response["events"][0]["pdf"]) == content
