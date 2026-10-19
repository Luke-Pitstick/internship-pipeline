"""Native update-copy verification never initializes workers or uses real candidate data."""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from internship_pipeline.identity import Identity
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Settings
from internship_pipeline.operations import OperationError, backup_installation, restore_installation
from internship_pipeline.storage import Store
from internship_pipeline.update_validation import Readiness, check_application, validate


@pytest.fixture
def restored(tmp_path):
    source = tmp_path / "source"
    settings = Settings(database_path=source / "state.sqlite3", artifact_dir=source / "artifacts")
    store = Store(settings.database_path)
    Identity(source / "identity.sqlite3")
    ModelConnectionStore(store.path, source / "model-credentials.key")
    settings.artifact_dir.mkdir()
    (settings.artifact_dir / "synthetic.pdf").write_bytes(b"synthetic-retained-document")
    candidate = tmp_path / "candidate"
    backup_installation(source, settings, candidate / "backup")
    restore_installation(candidate / "backup", candidate / "restored")
    return candidate / "restored"


def test_verified_update_copy_keeps_retained_bytes_and_does_not_rewrite_data(restored):
    before = {
        str(p.relative_to(restored)): p.read_bytes() for p in restored.rglob("*") if p.is_file()
    }
    validate(restored)
    after = {
        str(p.relative_to(restored)): p.read_bytes() for p in restored.rglob("*") if p.is_file()
    }
    assert before == after


@pytest.mark.parametrize("filename", ["artifacts/synthetic.pdf", "model-credentials.key"])
def test_update_validation_refuses_damaged_retained_data(restored, filename):
    (restored / filename).write_bytes(b"corrupted")
    with pytest.raises((OperationError, ValueError)):
        validate(restored)


def test_real_application_preflight_uses_candidate_data_without_external_transport(
    restored, tmp_path, monkeypatch
):
    import httpx

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("Synthetic application")
    monkeypatch.setenv("PIPELINE_WEB_DIR", str(web))
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(restored))
    monkeypatch.delenv("PIPELINE_SUPERVISOR_STATUS", raising=False)

    def unexpected(*args, **kwargs):
        pytest.fail("Update preflight must not contact external providers")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", unexpected)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unexpected)
    asyncio.run(check_application(restored))
    validate(restored)
    assert (restored / "artifacts/synthetic.pdf").read_bytes() == b"synthetic-retained-document"


def test_missing_frontend_fails_real_application_preflight(restored, tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_WEB_DIR", str(tmp_path / "missing-web"))
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(restored))
    monkeypatch.delenv("PIPELINE_SUPERVISOR_STATUS", raising=False)
    with pytest.raises(OperationError, match="not ready"):
        asyncio.run(check_application(restored))


@pytest.mark.parametrize("path,status", [("/readyz", 200), ("/api/jobs", 503), ("/", 503)])
def test_validation_server_exposes_only_readiness(path, status):
    class Handler(Readiness):
        def __init__(self):
            self.path = path
            self.wfile = io.BytesIO()
            self.status = None

        def send_response(self, code, message=None):
            self.status = code

        def send_error(self, code, message=None, explain=None):
            self.status = code

        def send_header(self, *args):
            pass

        def end_headers(self):
            pass

    handler = Handler()
    handler.do_GET()
    assert handler.status == status
    if status == 200:
        assert json.loads(handler.wfile.getvalue()) == {"ready": True, "mode": "update-validation"}
