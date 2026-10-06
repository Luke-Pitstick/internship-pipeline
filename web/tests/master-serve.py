"""Real authenticated API and compile-only queue worker for synthetic T11 browser QA."""
import json
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from internship_pipeline.app import create_app, runtime_settings
from internship_pipeline.resumes.master import MasterResumes
from internship_pipeline.storage import Store

with tempfile.TemporaryDirectory(prefix="pipeline-master-browser-") as directory:
    root = Path(directory)
    settings = runtime_settings(root, None)
    app = create_app(root, origin="http://127.0.0.1:4175",
                     static_dir=Path("build").resolve(), settings=settings)
    Path("test-results-master").mkdir(exist_ok=True)
    Path("test-results-master/setup.json").write_text(
        json.dumps({"token": app.state.identity.setup_token()}))
    worker = MasterResumes(Store(settings.database_path), settings)
    stop = threading.Event()

    def work():
        while not stop.is_set():
            if not worker.process_next():
                stop.wait(.2)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=4175, access_log=False)
    finally:
        stop.set()
        thread.join(timeout=65)
