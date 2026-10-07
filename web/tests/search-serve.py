"""Real API/SQLite/browser run path with synthetic ATS and HTTP Jev responses."""
import asyncio
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from test_assessments import setup, response
from internship_pipeline.app import create_app
from internship_pipeline.models import FetchResult, Settings, SourceJob
from internship_pipeline.storage import enqueue
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.assessments import EvaluationError
from internship_pipeline.sources import ats

async def synthetic_fetch(company, timeout):
    if company.id.endswith('brokenboard'):
        return FetchResult(complete=False, error='Synthetic provider unavailable')
    return FetchResult(jobs=[SourceJob(
        source='greenhouse',source_id=str(i),board_id=company.id,
        company=company.name,title=f'Synthetic Python internship {i}',
        description='Python internship. All citizenships welcome.',
        apply_url=f'https://example.test/browser/{i}') for i in [1,2]])

with tempfile.TemporaryDirectory(prefix='pipeline-search-browser-') as directory:
    root = Path(directory)
    matcher, _ = setup(root)
    matcher.transport = httpx.MockTransport(lambda request: httpx.Response(
        200,json=response(json.loads(request.content))))
    ats.fetch_company = synthetic_fetch
    settings = Settings(database_path=matcher.store.path)
    runs = SearchRuns(matcher.store)
    with matcher.store.transaction() as db:
        enqueue(db,'master_resume','synthetic-diagnostic-failure',{},time.time())
        db.execute("UPDATE tasks SET status='failed',error='synthetic-secret-token /private/secret.pdf' WHERE key='synthetic-diagnostic-failure'")
    def worker():
        while True:
            asyncio.run(runs.process_next(settings))
            matcher.reconcile()
            for job in matcher.store.list_jobs():
                try: matcher.evaluate(job.id)
                except EvaluationError: pass
            time.sleep(0.1)
    threading.Thread(target=worker,daemon=True).start()
    app = create_app(root,origin='http://127.0.0.1:4183',
                     static_dir=Path('build').resolve(),settings=settings)
    token = app.state.identity.setup_token(rotate=True)
    Path('test-results').mkdir(exist_ok=True)
    Path('test-results/search-setup.json').write_text(json.dumps({'token':token}))
    uvicorn.run(app,host='127.0.0.1',port=4183,access_log=False)
