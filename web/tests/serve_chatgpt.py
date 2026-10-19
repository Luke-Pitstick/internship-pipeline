"""Isolated synthetic owner API for ChatGPT connection browser tests."""

import json
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from internship_pipeline.app import create_app  # noqa: E402

with tempfile.TemporaryDirectory(prefix="pipeline-chatgpt-browser-") as directory:
    app = create_app(Path(directory), origin="http://127.0.0.1:4187",
                     static_dir=Path("build").resolve())
    evidence = Path("test-results-chatgpt")
    evidence.mkdir(exist_ok=True)
    (evidence / "setup.json").write_text(json.dumps({"token": app.state.identity.setup_token()}))
    uvicorn.run(app, host="127.0.0.1", port=4187, access_log=False)
