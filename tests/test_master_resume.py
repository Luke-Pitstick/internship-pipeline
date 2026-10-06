"""Synthetic master generation: queue, immutable facts, safe delivery and real TeX."""

from __future__ import annotations

import io
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from test_owner_app import claim
from test_resumes import textual_pdf

from internship_pipeline.app import create_app
from internship_pipeline.models import Settings
from internship_pipeline.profile_settings import (
    Fact,
    Preferences,
    Profile,
    ProfileSettings,
    SaveSettings,
)
from internship_pipeline.resumes.latex import LatexCompiler
from internship_pipeline.resumes.master import MasterConflict, MasterResumes, validate_master_pdf
from internship_pipeline.resumes.master_template import TEMPLATE_REVISION, escape, render_master
from internship_pipeline.resumes.validation import ResumeValidationError
from internship_pipeline.storage import Store


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    profile = Profile.model_validate_json(
        (Path(__file__).parent / "fixtures/master_profile.json").read_text()
    )
    profiles = ProfileSettings(store)
    profiles.save(
        SaveSettings(
            expected_revision=0,
            profile=profile,
            preferences=Preferences(soft={"skills": ["Unlearned Rust"]}),
        )
    )
    result = MasterResumes(
        store, Settings(database_path=store.path, artifact_dir=tmp_path / "artifacts")
    )
    result.compiler = FakeCompiler(result)
    return result


class FakeCompiler(LatexCompiler):
    def __init__(self, service):
        self.service = service
        self.calls = 0
        self.callback = lambda: None
        self.error = None

    def compile(self, source, deadline):
        assert deadline > time.monotonic()
        assert deadline - time.monotonic() <= 60
        self.calls += 1
        snapshot = self.service.profiles.read()
        document = render_master(snapshot)
        assert source == document.source
        self.callback()
        if self.error:
            raise ResumeValidationError(self.error)
        return textual_pdf("\n".join(document.required_text))


def update(service, **changes):
    snapshot = service.profiles.read()
    return service.profiles.save(
        SaveSettings(
            expected_revision=snapshot.revision,
            profile=snapshot.profile.model_copy(update=changes),
            preferences=snapshot.preferences,
        )
    )


def test_literal_facts_multiple_education_and_manifest(service):
    snapshot = service.profiles.read()
    doc = render_master(snapshot)
    assert "Unverified" not in doc.source and "Unlearned" not in doc.source
    assert doc.omitted_unknown == 2
    assert doc.manifest["profile_revision"] == 1
    assert doc.manifest["template_revision"] == TEMPLATE_REVISION
    assert [e["id"] for e in doc.manifest["education"]] == [
        "education-bachelor",
        "education-certificate",
    ]
    assert doc.manifest["skills_provenance"]["Python"] == ["experience-api"]
    assert "25\\%" in doc.source and "120" in doc.source
    assert snapshot.candidate().constraints.degree_level is None


def test_queue_cache_private_files_and_reopen(service):
    request = service.request(1)
    assert request["state"] == "pending"
    assert service.request(1)["key"] == request["key"]
    assert service.process_next()
    ready = service.latest()
    assert ready["state"] == "ready" and ready["pages"] == 1
    assert not service.process_next()
    assert service.request(1)["state"] == "ready"
    assert service.compiler.calls == 1
    files = list(service.root.iterdir())
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    assert service.root.stat().st_mode & 0o777 == 0o700
    reopened = MasterResumes(Store(service.store.path), service.settings)
    assert reopened.pdf(ready["key"]) == service.pdf(ready["key"])
    with service.store.connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM tasks WHERE kind='master_resume'").fetchone()[
                0
            ]
            == 1
        )
        manifest = json.loads(
            connection.execute("SELECT manifest FROM master_resumes").fetchone()[0]
        )
    assert manifest["contact"] == {"name": "Synthetic Candidate", "email": "synthetic@example.test"}


def test_concurrent_requests_share_one_task(service):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.request(1), range(4)))
    assert len({result["key"] for result in results}) == 1
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_stale_compile_never_becomes_latest(service):
    request = service.request(1)
    service.compiler.callback = lambda: update(service, name="New Synthetic Candidate")
    assert service.process_next()
    assert service.latest()["state"] == "idle"
    assert service.latest()["profile_revision"] == 2
    assert service.status(request["key"])["state"] == "stale"
    with pytest.raises(MasterConflict):
        service.request(1)


def test_lost_lease_cannot_publish(service):
    service.request(1)

    def lose():
        with service.store.connection() as connection:
            connection.execute("UPDATE tasks SET token='another-worker'")

    service.compiler.callback = lose
    service.process_next()
    assert service.latest()["state"] == "running"
    assert list(service.root.iterdir()) == []


@pytest.mark.parametrize("method", ["delete", "corrupt", "symlink"])
def test_cache_damage_is_detected_and_explicitly_repaired(service, tmp_path, method):
    service.request(1)
    service.process_next()
    key = service.latest()["key"]
    path = next(service.root.iterdir())
    if method == "corrupt":
        path.write_bytes(b"%PDF-broken")
    else:
        path.unlink()
        if method == "symlink":
            private = tmp_path / "private.pdf"
            private.write_bytes(b"%PDF-private")
            path.symlink_to(private)
    with pytest.raises((OSError, ValueError)):
        service.pdf(key)
    assert service.request(1)["state"] == "pending"
    service.process_next()
    assert service.latest()["state"] == "ready"
    assert service.compiler.calls == 2


@pytest.mark.parametrize(
    "error, recovery",
    [
        ("LaTeX compiler is unavailable", "pdflatex"),
        ("LaTeX reports text overflow", "Shorten facts"),
        ("Resume PDF exceeds the allowed page count", "two-page"),
    ],
)
def test_actionable_failure_and_bounded_retry(service, error, recovery):
    service.compiler.error = error
    service.request(1)
    service.process_next()
    assert service.latest()["state"] == "failed"
    assert recovery in service.latest()["error"]
    assert not service.process_next()
    service.compiler.error = None
    service.request(1)
    service.process_next()
    assert service.latest()["state"] == "ready"


def test_unknown_empty_and_unsupported_profiles_fail_before_queue(service):
    update(service, facts=[Fact(id="uncertain", text="Unknown", status="unknown")], education=[])
    with pytest.raises(ResumeValidationError, match="Confirm at least"):
        service.request(2)
    update(service, name="", facts=[Fact(id="fact", text="Known", status="confirmed")])
    with pytest.raises(ResumeValidationError, match="name"):
        service.request(3)
    update(service, name="Unsupported 😃")
    with pytest.raises(ResumeValidationError, match="unsupported character"):
        service.request(4)
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize(
    "text",
    [
        r"\input{/etc/passwd} & 100% #1 ${x}_ ~ ^",
        r"\write18{touch /tmp/pwned} \end{document}",
        "Quotation \" and apostrophe ' with {-} brackets.",
    ],
)
def test_escape_prevents_tex_commands(text):
    escaped = escape(text)
    assert r"\input" not in escaped and r"\write18" not in escaped
    assert "\\textbackslash{}" in escaped or "textquotesingle" in escaped


def test_pdf_checks_factual_text_page_count_readability_and_bounds(service):
    snapshot = service.profiles.read()
    document = render_master(snapshot)
    text = "\n".join(document.required_text)
    assert validate_master_pdf(textual_pdf(text, pages=2), snapshot, document) == 2
    for content in [
        b"not pdf",
        textual_pdf(""),
        textual_pdf(text, pages=3),
        textual_pdf(text, x=-100),
        textual_pdf(text.replace("120", "121")),
    ]:
        with pytest.raises(ResumeValidationError):
            validate_master_pdf(content, snapshot, document)


def test_authenticated_api_csrf_and_safe_pdf(service, tmp_path):
    app = create_app(tmp_path / "app", origin="http://localhost:8080", settings=service.settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/master-resume").status_code == 401
        assert client.get("/api/master-resume/" + "a" * 64 + "/pdf").status_code == 401
        headers = claim(client)
        assert client.post("/api/master-resume", json={"expected_revision": 1}).status_code == 403
        assert (
            client.post(
                "/api/master-resume",
                headers={**headers, "Origin": "https://evil.test"},
                json={"expected_revision": 1},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/master-resume", headers=headers, json={"expected_revision": 0}
            ).status_code
            == 409
        )
        response = client.post("/api/master-resume", headers=headers, json={"expected_revision": 1})
        assert response.status_code == 202
        service.process_next()
        ready = client.get("/api/master-resume").json()
        response = client.get(ready["preview_url"])
        assert response.status_code == 200 and response.content.startswith(b"%PDF-")
        assert response.headers["content-disposition"].startswith("inline")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        download = client.get(ready["download_url"])
        assert download.headers["content-disposition"].startswith("attachment")
        assert client.get("/api/master-resume/not-a-key/pdf").status_code == 404
        assert "filename" not in ready and "manifest" not in ready
        client.post("/api/logout", headers=headers)
        assert client.get(ready["download_url"]).status_code == 401


def test_real_compile_literal_injection_and_multiple_education(service, tmp_path):
    executable = shutil.which("pdflatex")
    if executable is None:
        pytest.skip("pdflatex unavailable; actual master template compile unverified")
    injection = r"Literal \input{/etc/passwd} & 25% \write18{touch /tmp/pwned} $100 #1 _ ~ ^"
    snapshot = service.profiles.read()
    update(
        service,
        facts=[*snapshot.profile.facts, Fact(id="literal", status="confirmed", text=injection)],
    )
    service.compiler = LatexCompiler(executable)
    service.request(2)
    service.process_next()
    assert service.latest()["state"] == "ready", service.latest()
    pdf = service.pdf(service.latest()["key"])
    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Example University" in text and "Synthetic College" in text
    assert "Unverified" not in text and "Unconfirmed" not in text
    assert "/etc/passwd" in text and "root:" not in text
    (tmp_path / "review.pdf").write_bytes(pdf)
