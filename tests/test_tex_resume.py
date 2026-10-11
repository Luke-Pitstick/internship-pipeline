"""Source import/review, bounded AI edits, and explicitly requested PDF rendering."""

import json
import subprocess
import time

import httpx
import pytest
from test_resume_import import docx_bytes, reviewed
from test_tailored_resume import request
from test_tailored_resume import service as _service

from internship_pipeline.profile_settings import SaveSettings
from internship_pipeline.profiles.extract import DocumentError, extract, tex_source
from internship_pipeline.profiles.imports import ResumeImports
from internship_pipeline.resumes.latex import LatexCompiler
from internship_pipeline.resumes.master_template import render_master
from internship_pipeline.resumes.source_edits import SourceEdit, apply_edits
from internship_pipeline.resumes.validation import TexIsolationUnavailable

SOURCE = r"""\documentclass{article}
\newcommand{\resumeItem}[1]{\item #1}
\begin{document}
Synthetic Candidate
synthetic@example.test
\section{Education}
Example University
Bachelor of Science in Computing
\section{Experience}
\begin{itemize}
\resumeItem{Built an example reporting tool.}
\end{itemize}
\end{document}
"""


@pytest.fixture
def service(tmp_path):
    return _service.__wrapped__(tmp_path)


def test_tex_extraction_and_review_activation(tmp_path):
    from internship_pipeline.storage import Store

    imports = ResumeImports(Store(tmp_path / "state.sqlite3"))
    draft = imports.upload(SOURCE.encode(), "tex", 0)
    assert imports.template() is None  # Preview/discard cannot change the saved template.
    assert any("Built an example" in line["text"] for line in draft["lines"])
    saved = imports.confirm(draft["id"], reviewed(draft))
    assert saved.profile.name == "Synthetic Candidate"
    assert saved.profile.education[0].institution == "Example University"
    assert saved.profile.facts[0].text == "Built an example reporting tool."
    assert imports.template() == SOURCE
    # A replacement PDF/DOCX import selects the application template again.
    replacement = imports.upload(docx_bytes(), "docx", saved.revision)
    assert imports.template() == SOURCE
    imports.confirm(replacement["id"], reviewed(replacement))
    assert imports.template() is None


@pytest.mark.parametrize("data", [b"\xff", b"\x00", b"%\\begin{document}\n%\\end{document}"])
def test_tex_rejects_invalid_source(data):
    with pytest.raises(DocumentError):
        tex_source(data)


def test_tex_extraction_does_not_expand_inputs(tmp_path):
    secret = tmp_path / "private-marker.tex"
    secret.write_text("private-candidate-marker")
    lines = extract(SOURCE.replace("Synthetic Candidate", rf"\input{{{secret}}}").encode(), "tex")
    assert all("private-candidate-marker" not in line["text"] for line in lines)


def test_edit_contract_rejects_fabrication_partial_and_overlapping_blocks():
    assert "Built an example" not in apply_edits(
        SOURCE, [SourceEdit(old="\\resumeItem{Built an example reporting tool.}\n", new="")], []
    )
    for edits in [
        [SourceEdit(old="Synthetic Candidate\n", new="Invented Candidate\n")],
        [SourceEdit(old="reporting", new="machine learning")],
        [SourceEdit(old="Synthetic Candidate\n", new="") for _ in range(2)],
        [SourceEdit(old="Synthetic Candidate\n", new="\\input{/private/secret}\n")],
    ]:
        with pytest.raises(ValueError):
            apply_edits(SOURCE, edits, [])


def set_template(service):
    snapshot = service.profiles.read()
    source = render_master(snapshot).source
    draft = service.imports.upload(source.encode(), "tex", snapshot.revision)
    review = reviewed(draft)
    review.settings = SaveSettings(
        expected_revision=snapshot.revision,
        profile=snapshot.profile,
        preferences=snapshot.preferences,
    )
    service.imports.confirm(draft["id"], review)
    calls = []

    def respond(req):
        payload = json.loads(req.content)
        calls.append(payload)
        assert json.loads(payload["input"])["untrusted_tex_template"] == source
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
                "usage": {"input_tokens": 40, "output_tokens": 20},
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "fact_ids": ["experience-api", "project-dashboard"],
                                        "edits": [{"old": "\\pagestyle{plain}\n", "new": ""}],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    # A preamble edit must fail, even if its replacement is otherwise grounded.
    service.transport = httpx.MockTransport(respond)
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "failed"
    assert not service.latest(service.job_id).get("source_url")

    def valid(req):
        response = respond(req)
        body = json.loads(response.content)
        plan = {"fact_ids": ["experience-api", "project-dashboard"], "edits": []}
        # Edit an actual body block, preserving all selected evidence.
        plan["edits"] = [{"old": "\\resumesection{Technical skills}\n", "new": ""}]
        body["output"][0]["content"][0]["text"] = json.dumps(plan)
        return httpx.Response(200, json=body)

    service.transport = httpx.MockTransport(valid)
    return source, calls


def test_tex_draft_then_explicit_pdf_and_stale_source(service):
    source, calls = set_template(service)
    compiler = service.compiler

    class NoCompile:
        def compile(self, *args, **kwargs):
            raise AssertionError("Draft generation must not compile TeX")

    service.compiler = NoCompile()
    request(service)
    service.process_next()
    draft = service.latest(service.job_id)
    assert draft["state"] == "draft", draft
    assert draft["source_url"] and not draft.get("preview_url")
    edited = service.source(draft["key"])
    assert edited != source and "\\resumesection{Technical skills}" not in edited
    assert service.imports.template() == source
    assert service.review(draft["key"])["state"] == "reviewed"
    assert request(service)["key"] == draft["key"]
    assert len(calls) == 2
    with pytest.raises(FileNotFoundError):
        service.pdf(draft["key"])
    service.compiler = compiler
    assert service.render_pdf(draft["key"])["state"] == "pending"
    service.process_next()
    rendered = service.latest(service.job_id)
    assert rendered["state"] in {"draft", "reviewed"}, rendered
    assert service.pdf(draft["key"]).startswith(b"%PDF-")
    assert len(calls) == 2  # Explicit rendering never repeats inference.
    snapshot = service.profiles.read()
    service.profiles.save(
        SaveSettings(
            expected_revision=snapshot.revision,
            profile=snapshot.profile,
            preferences=snapshot.preferences,
        )
    )
    with pytest.raises(FileNotFoundError):
        service.source(draft["key"])
    with pytest.raises(FileNotFoundError):
        service.render_pdf(draft["key"])


def test_render_failure_retains_source_without_repeating_ai(service):
    _, calls = set_template(service)
    request(service)
    service.process_next()
    draft = service.latest(service.job_id)

    class Broken:
        def compile(self, *args, **kwargs):
            raise ValueError("synthetic compiler failure")

    service.compiler = Broken()
    service.render_pdf(draft["key"])
    service.process_next()
    failed = service.latest(service.job_id)
    assert failed["state"] == "failed" and failed["source_url"]
    assert service.source(draft["key"])
    assert len(calls) == 2


@pytest.mark.parametrize("remove_selected", [False, True])
def test_source_must_match_selected_and_omitted_facts(service, remove_selected):
    source, _ = set_template(service)
    plan = {"fact_ids": ["experience-api"], "edits": []}
    if remove_selected:
        plan["fact_ids"].append("project-dashboard")
        line = next(line for line in source.splitlines(True) if "Built a Python API" in line)
        plan["edits"].append({"old": line, "new": ""})

    def respond(req):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
                "usage": {"input_tokens": 40, "output_tokens": 20},
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(plan),
                            }
                        ],
                    }
                ],
            },
        )

    service.transport = httpx.MockTransport(respond)
    request(service)
    service.process_next()
    draft = service.latest(service.job_id)
    assert draft["state"] == "failed" and not draft.get("source_url")


def test_unavailable_isolation_retains_source_with_actionable_error(service):
    set_template(service)
    request(service)
    service.process_next()
    draft = service.latest(service.job_id)

    class Unavailable:
        def compile(self, *args, **kwargs):
            raise TexIsolationUnavailable

    service.compiler = Unavailable()
    service.render_pdf(draft["key"])
    service.process_next()
    failed = service.latest(service.job_id)
    assert failed["state"] == "failed" and failed["source_url"]
    assert "Landlock ABI 4+" in failed["error"]
    assert service.source(draft["key"])


def test_untrusted_compiler_cannot_read_private_file_or_run_shell(tmp_path, monkeypatch):
    class SyntheticCompilerProcess(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            super().__init__(
                *args, **(kwargs | {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
            )

        def communicate(self, *args, **kwargs):
            stdout, stderr = super().communicate(*args, **kwargs)
            if self.returncode:
                # This test compiles only fixed synthetic source; never print user documents.
                print(stdout.decode(errors="replace")[-6000:])
                print(stderr.decode(errors="replace")[-2000:])
            return stdout, stderr

    monkeypatch.setattr(subprocess, "Popen", SyntheticCompilerProcess)
    secret = tmp_path / "candidate-secret.tex"
    secret.write_text("private-candidate-marker")
    source = SOURCE.replace("Synthetic Candidate", rf"\input{{{secret}}}")
    with pytest.raises(ValueError):
        LatexCompiler().compile(source, time.monotonic() + 20, untrusted=True)
    output = tmp_path / "shell-escape-marker"
    source = SOURCE.replace("Synthetic Candidate", rf"\immediate\write18{{touch {output}}}")
    content = LatexCompiler().compile(source, time.monotonic() + 20, untrusted=True)
    assert content.startswith(b"%PDF-") and not output.exists()


def test_source_download_and_render_require_owner_csrf_and_current_revision(service, tmp_path):
    from fastapi.testclient import TestClient
    from test_owner_app import claim

    from internship_pipeline.app import create_app

    set_template(service)
    request(service)
    service.process_next()
    draft = service.latest(service.job_id)
    render = f"/api/tailored-resume/{draft['key']}/render"
    app = create_app(tmp_path, origin="http://localhost:8080", settings=service.settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get(draft["source_url"]).status_code == 401
        assert client.post(render, json={}).status_code == 401
        headers = claim(client)
        tex = client.get(draft["source_url"])
        assert tex.status_code == 200
        assert tex.headers["cache-control"] == "no-store"
        assert "attachment" in tex.headers["content-disposition"]
        assert tex.text == service.source(draft["key"])
        assert client.post(render, json={}).status_code == 403
        assert (
            client.post(
                render, json={}, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post(render, json={}, headers=headers).status_code == 202
        client.post("/api/logout", headers=headers)
        assert client.get(draft["source_url"]).status_code == 401
