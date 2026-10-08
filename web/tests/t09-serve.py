"""Real authenticated SQLite/HTTP browser fixture; synthetic data only."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / "src"), str(root / "tests")]
from internship_pipeline.app import create_app
from internship_pipeline.dashboard_api import DashboardAPI
from internship_pipeline.models import Settings
from test_job_workspace import seed

with tempfile.TemporaryDirectory(prefix="t09-stored-browser-") as directory:
    settings = Settings(database_path=Path(directory)/"state.sqlite3", artifact_dir=Path(directory)/"artifacts")
    app = create_app(Path(directory), origin="http://127.0.0.1:4189", static_dir=Path("build").resolve(), settings=settings)
    seed(DashboardAPI(settings), 10000)
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "INSERT INTO search_runs(id,search_id,config,target_id,stage,created,"
            "max_jobs,max_calls,max_tokens) VALUES(?,?,?,?,?,?,?,?,?)",
            ("synthetic-progress", "synthetic-source", '{"name":"Synthetic progress"}',
             "synthetic", "collecting", time.time(), 0, 0, 0),
        )
        db.executemany("INSERT INTO search_run_jobs VALUES('synthetic-progress',?)",[(f"synthetic-{i:05d}",) for i in range(100)])
    stop=threading.Event()
    def progress():
        count=0
        while not stop.wait(.1):
            count+=1
            with sqlite3.connect(settings.database_path, timeout=5) as db:
                db.execute("UPDATE search_runs SET collected=? WHERE id='synthetic-progress'",(count,))
    threading.Thread(target=progress,daemon=True).start()
    Path("test-results-t09").mkdir(exist_ok=True)
    Path("test-results-t09/t09-setup.json").write_text(json.dumps({"token":app.state.identity.setup_token()}))
    try: uvicorn.run(app,host="127.0.0.1",port=4189,access_log=False)
    finally: stop.set()
