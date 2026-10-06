"""Ephemeral synthetic API fixture for browser integration tests only."""
import json
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from internship_pipeline.app import create_app

with tempfile.TemporaryDirectory(prefix="pipeline-browser-") as directory:
    app = create_app(Path(directory), origin="http://127.0.0.1:4174",
                     static_dir=Path("build").resolve())
    token = app.state.identity.setup_token()
    Path("test-results").mkdir(exist_ok=True)
    Path("test-results/setup.json").write_text(json.dumps({"token": token}))
    uvicorn.run(app, host="127.0.0.1", port=4174, access_log=False)
