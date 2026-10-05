"""Run the protected results API alongside the independently provisioned workers."""

import sys

from internship_pipeline.supervisor import supervise

raise SystemExit(
    supervise(
        {
            "results": [
                sys.executable,
                "-m",
                "internship_pipeline.dashboard_api",
                "--config",
                "/var/data/config/settings.yaml",
            ],
            "pipeline": [sys.executable, "/app/worker-entrypoint.py"],
        }
    )
)
