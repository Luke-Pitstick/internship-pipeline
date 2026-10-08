"""Real CSV response completeness and read-connection lifecycle on disconnect."""

from __future__ import annotations

import asyncio
import csv
import io
import sqlite3

import pytest
from starlette.requests import ClientDisconnect
from test_owner_app import api as dashboard_fixture
from test_owner_app import claim
from test_owner_app import client as owner_fixture
from test_sheets_integration import inventory

from internship_pipeline.models import Job
from internship_pipeline.sheets_router import build_sheets_router

api = dashboard_fixture
client = owner_fixture


def test_csv_endpoint_exports_complete_sqlite_inventory(client):
    service = client.app.state.sheets_integration
    with service.store.connection() as db:
        row = db.execute("SELECT data FROM jobs ORDER BY id LIMIT 1").fetchone()
        job = Job.model_validate_json(row[0])
    inventory(service, job, 10003)
    with service.store.connection() as db:
        expected = [row[0] for row in db.execute("SELECT id FROM jobs ORDER BY id")]
    claim(client)
    response = client.get("/api/sheets/export.csv")
    assert response.status_code == 200
    actual = [row["job_id"] for row in csv.DictReader(io.StringIO(response.text))]
    assert len(actual) > 10000 and actual == expected
    assert len(set(actual)) == len(expected)


@pytest.mark.parametrize("failure", ["send_error", "disconnect"])
def test_csv_response_closes_sqlite_reader_on_transport_exit(client, monkeypatch, failure):
    closed = []
    original = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()

    def connect(*args, **kwargs):
        if kwargs.get("check_same_thread") is False:
            kwargs["factory"] = TrackedConnection
        return original(*args, **kwargs)

    monkeypatch.setattr("internship_pipeline.sheets_integration.sqlite3.connect", connect)
    router = build_sheets_router(client.app.state.sheets_integration, lambda request: None)
    route = next(
        route for route in router.routes if getattr(route, "path", "") == "/api/sheets/export.csv"
    )
    response = route.endpoint()

    async def run():
        row_sent = asyncio.Event()
        chunks = 0

        async def send(message):
            nonlocal chunks
            if message["type"] == "http.response.body" and message.get("body"):
                chunks += 1
                if chunks == 2:
                    row_sent.set()
                    if failure == "send_error":
                        raise OSError("Synthetic client socket closed")
                    await asyncio.Event().wait()

        async def receive():
            await row_sent.wait()
            return {"type": "http.disconnect"}

        scope = {
            "type": "http",
            "asgi": {"spec_version": "2.4" if failure == "send_error" else "2.0"},
        }
        if failure == "send_error":
            with pytest.raises(ClientDisconnect):
                await response(scope, receive, send)
        else:
            await response(scope, receive, send)
        assert chunks >= 2
        assert closed == [True], "Disconnect must close the active SQLite CSV read snapshot"

    asyncio.run(run())
