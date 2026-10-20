"""Native document contracts and end-to-end import routing with synthetic PDFs."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_resume_import import pdf_bytes, reviewed

from internship_pipeline.profiles import pdf_model
from internship_pipeline.profiles.extract import DocumentError
from internship_pipeline.profiles.imports import ResumeImports, build_resume_import_router
from internship_pipeline.providers.connections import ConnectionInput
from internship_pipeline.providers.structured import GENERAL_ENDPOINTS
from internship_pipeline.storage import Store

KEY = "synthetic-pdf-key"
ROWS = [
    "Synthetic Candidate",
    "synthetic@example.test",
    "Experience",
    "Software Engineer | Example Labs | Remote | June 2024 - Present",
    "* Built a reporting service.",
    "Skills",
    "Python, SQL",
]


def config(provider="openai", model="gpt-4.1", **changes):
    return ConnectionInput(
        endpoint=GENERAL_ENDPOINTS[provider],
        model=model,
        expected_revision=1,
        **changes,
    )


class Connections:
    def __init__(self, selected=None, ready=True):
        self.selected = selected or config()
        self.ready = ready
        self.credentials_read = False

    def summary(self):
        return {
            "general": {
                "ready": self.ready,
                "revision": 1,
                "config": self.selected.model_dump(exclude={"expected_revision", "api_key"}),
            }
        }

    def ready_connection(self, kind, revision):
        assert kind == "general" and revision == 1
        self.credentials_read = True
        return self.selected, KEY


def response(provider, rows=ROWS):
    text = json.dumps({"rows": [{"page": 1, "text": text} for text in rows]})
    if provider == "openai":
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
    if provider == "anthropic":
        return {
            "type": "message",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
        }
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ]
    }


@pytest.mark.parametrize("provider", GENERAL_ENDPOINTS)
def test_native_pdf_wire_format_and_transcription(provider):
    data = pdf_bytes()
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        if provider == "openai":
            file = body["input"][0]["content"][0]
            assert file["type"] == "input_file" and file["filename"] == "resume.pdf"
            assert file["file_data"].startswith("data:application/pdf;base64,JVBER")
            assert body["store"] is False
        elif provider == "anthropic":
            document = body["messages"][0]["content"][0]
            assert document["type"] == "document"
            assert document["source"]["media_type"] == "application/pdf"
            assert document["source"]["data"].startswith("JVBER")
            assert request.headers["x-api-key"] == KEY
        else:
            file = body["messages"][1]["content"][0]["file"]
            assert file["file_data"].startswith("data:application/pdf;base64,JVBER")
            assert body["plugins"] == [{"id": "file-parser", "pdf": {"engine": "native"}}]
            assert body["provider"]["allow_fallbacks"] is False
        return httpx.Response(200, json=response(provider))

    lines = asyncio.run(
        pdf_model.read_pdf(
            config(provider),
            KEY,
            data,
            1,
            transport=httpx.MockTransport(respond),
        )
    )
    assert [line["text"] for line in lines] == ROWS
    assert all("AI transcription" in line["location"] for line in lines)
    assert len(calls) == 1


@pytest.mark.parametrize("model", ["gpt-3.5-turbo", "gpt-4o-audio-preview", "gpt-99", "o3-mini"])
def test_unknown_and_text_models_do_not_access_credentials(model):
    connections = Connections(config(model=model))
    assert asyncio.run(pdf_model.connection(connections)) is None
    assert not connections.credentials_read


def test_untested_and_subscription_connections_are_local():
    assert asyncio.run(pdf_model.connection(Connections(ready=False))) is None
    selected = config(auth_mode="chatgpt", chatgpt_account_id="a" * 64)
    connections = Connections(selected)
    assert asyncio.run(pdf_model.connection(connections)) is None
    assert not connections.credentials_read


@pytest.mark.parametrize(
    "modalities,expected", [(["text", "image"], False), (["text", "file"], True)]
)
def test_openrouter_needs_file_modality(modalities, expected):
    connections = Connections(config("openrouter", "vendor/model"))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model",
                        "architecture": {"input_modalities": modalities},
                    }
                ]
            },
        )
    )
    assert bool(asyncio.run(pdf_model.connection(connections, transport=transport))) is expected


def test_anthropic_needs_current_catalog_membership():
    connections = Connections(config("anthropic", "claude-sonnet-4-6"))
    for models, expected in [([], False), ([{"id": "claude-sonnet-4-6"}], True)]:
        transport = httpx.MockTransport(
            lambda request, models=models: httpx.Response(200, json={"data": models})
        )
        assert bool(asyncio.run(pdf_model.connection(connections, transport=transport))) is expected


@pytest.mark.parametrize(
    "failure", ["truncated", "refusal", "bad_page", "oversize", "credential", "429"]
)
def test_bad_model_output_is_rejected_without_retry(failure):
    calls = []

    def respond(request):
        calls.append(request)
        body = response("openai")
        if failure == "truncated":
            body["status"] = "incomplete"
        elif failure == "refusal":
            body["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
        elif failure in {"bad_page", "oversize", "credential"}:
            body["output"][0]["content"][0]["text"] = json.dumps(
                {
                    "rows": [
                        {
                            "page": 2 if failure == "bad_page" else 1,
                            "text": "x" * 2001 if failure == "oversize" else KEY,
                        }
                    ]
                }
            )
        return httpx.Response(429 if failure == "429" else 200, json=body)

    with pytest.raises(DocumentError, match="could not read"):
        asyncio.run(
            pdf_model.read_pdf(
                config(),
                KEY,
                pdf_bytes(),
                1,
                transport=httpx.MockTransport(respond),
            )
        )
    assert len(calls) == 1


def test_scan_fills_structured_profile_and_reviewed_provenance(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    app = FastAPI()
    app.include_router(build_resume_import_router(store, lambda: None, Connections()))
    calls = []
    original = pdf_model.read_pdf

    async def read(*args):
        calls.append(args)
        return await original(
            *args,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=response("openai"),
                )
            ),
        )

    monkeypatch.setattr(pdf_model, "read_pdf", read)
    with TestClient(app) as client:
        result = client.post(
            "/api/resume-imports/upload?format=pdf&expected_revision=0",
            content=pdf_bytes(text=False),
        )
    assert result.status_code == 200, result.text
    draft = result.json()
    assert draft["method"] == "native_pdf" and not draft["warnings"] and len(calls) == 1
    service = ResumeImports(store)
    filled, evidence = service.prepare(draft["id"], reviewed(draft))
    fact = filled.profile.facts[0]
    assert (fact.title, fact.company, fact.location) == (
        "Software Engineer",
        "Example Labs",
        "Remote",
    )
    assert fact.start_date == "2024-06" and fact.current and fact.end_date is None
    assert fact.text == "* Built a reporting service."
    assert service.settings.read().revision == 0
    assert all("AI transcription" in item["location"] for item in evidence)
    assert service.confirm(draft["id"], reviewed(draft)).profile == filled.profile


def test_local_opt_out_and_failed_model_use_deterministic_import(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    app = FastAPI()
    app.include_router(build_resume_import_router(store, lambda: None, Connections()))
    calls = []

    async def fail(*args):
        calls.append(args)
        raise DocumentError("The model could not read the PDF.")

    monkeypatch.setattr(pdf_model, "read_pdf", fail)
    with TestClient(app) as client:
        url = "/api/resume-imports/upload?format=pdf&expected_revision=0"
        local = client.post(url + "&use_model=false", content=pdf_bytes())
        assert local.status_code == 200 and local.json()["method"] == "local"
        assert not calls
        failed = client.post(url, content=pdf_bytes())
        assert failed.status_code == 200 and failed.json()["method"] == "local"
        assert failed.json()["warnings"] and len(calls) == 1
        assert client.post(url, content=b"invalid").status_code == 422
        assert len(calls) == 1
        stale = client.post(url.replace("revision=0", "revision=1"), content=pdf_bytes())
        assert stale.status_code == 409 and len(calls) == 1
