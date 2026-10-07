"""Fresh installation with real API, ATS parser/queues and synthetic HTTP/SMTP transports."""
import asyncio
import json
import sys
import tempfile
import threading
from pathlib import Path

import httpx
import uvicorn
from ats_scrapers.fetch import Fetcher, FetchResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from test_assessments import response
from test_model_connections import general_response, jev_response
from internship_pipeline.app import create_app, runtime_settings
from internship_pipeline.assessments import EvaluationError
from internship_pipeline.model_connection_router import probe as actual_probe
from internship_pipeline import model_connection_router
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.storage import Store


async def perform(self, method, url, **kwargs):
    if "brokenboard" in url:
        return FetchResponse(403, "{}", {}, "synthetic")
    return FetchResponse(200, json.dumps({"jobs": [{
        "id": 1, "title": "Synthetic Python internship",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/1",
        "content": "Python internship. All citizenships welcome.",
        "location": {"name": "Remote"}, "updated_at": "2026-10-01T00:00:00Z",
    }]}), {}, "synthetic")


Fetcher._perform = perform


def capability(request):
    if "invalid" in request.headers.get("Authorization", ""):
        return httpx.Response(401, json={})
    return httpx.Response(200, json=jev_response() if request.url.host == "api.typesafe.ai"
                          else general_response())


async def probe(kind, config, key):
    return await actual_probe(kind, config, key, transport=httpx.MockTransport(capability))


model_connection_router.probe = probe
with tempfile.TemporaryDirectory(prefix="pipeline-setup-browser-") as directory:
    root = Path(directory)
    settings = runtime_settings(root, None)
    app = create_app(root, origin="http://127.0.0.1:4184",
                     static_dir=Path("build").resolve(), settings=settings)
    app.state.assessments.transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=response(json.loads(request.content))))
    app.state.email_integrations.transport = lambda *args: "credential_unavailable"
    runs = SearchRuns(Store(settings.database_path))
    stop = threading.Event()

    def work():
        while not stop.is_set():
            asyncio.run(runs.process_next(settings))
            app.state.assessments.reconcile()
            for job in runs.store.list_jobs():
                try:
                    app.state.assessments.evaluate(job.id)
                except EvaluationError:
                    pass
            app.state.email_integrations.process_next()
            stop.wait(.1)

    Path("test-results-setup").mkdir(exist_ok=True)
    Path("test-results-setup/setup.json").write_text(
        json.dumps({"token": app.state.identity.setup_token()}))
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=4184, access_log=False)
    finally:
        stop.set()
        worker.join(timeout=3)
