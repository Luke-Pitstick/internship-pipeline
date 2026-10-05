"""Wait for explicit provisioning before starting the private pipeline worker."""

import os
import signal
import threading
from pathlib import Path

root = Path("/var/data")
root.mkdir(parents=True, exist_ok=True)
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT, lambda *_: stop.set())
print("Worker deployed; waiting for /var/data/activated after private provisioning.", flush=True)
while not (root / "activated").is_file():
    if stop.wait(5):
        raise SystemExit(0)
os.execvp("internship-pipeline", [
    "internship-pipeline", "--config", "/var/data/config/settings.yaml", "serve",
])
