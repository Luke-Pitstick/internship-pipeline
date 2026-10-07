"""Real owner API and delivery worker using only synthetic SMTP acceptance."""
import json
import sys
import tempfile
import threading
from pathlib import Path
import uvicorn
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from internship_pipeline.app import create_app, runtime_settings
with tempfile.TemporaryDirectory(prefix="pipeline-email-browser-") as directory:
    root=Path(directory)
    settings=runtime_settings(root,None)
    app=create_app(root,origin="http://127.0.0.1:4178",static_dir=Path("build").resolve(),settings=settings)
    app.state.email_integrations.transport=lambda *args:"accepted"
    Path("test-results-email").mkdir(exist_ok=True)
    Path("test-results-email/setup.json").write_text(json.dumps({"token":app.state.identity.setup_token()}))
    stop=threading.Event()
    def work():
        while not stop.is_set():
            app.state.email_integrations.schedule()
            if not app.state.email_integrations.process_next():stop.wait(.2)
    worker=threading.Thread(target=work,daemon=True);worker.start()
    try:uvicorn.run(app,host="127.0.0.1",port=4178,access_log=False)
    finally:stop.set();worker.join(timeout=3)
