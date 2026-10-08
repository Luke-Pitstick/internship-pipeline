#!/usr/bin/env python3
"""Read cgroup-v2 counters from an existing owned installation without starting work."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from pipeline_runtime import Failure, Manifest, Runtime, load_manifest

# A private cgroup namespace is required so the root counters represent this
# container, not the engine host. Never reset the kernel's lifetime peak.
PROBE = """
import json, pathlib, shutil, sys
root = pathlib.Path('/sys/fs/cgroup')
if pathlib.Path('/proc/self/cgroup').read_text().strip() != '0::/':
    raise RuntimeError('A private cgroup namespace is required')
if not (root / 'cgroup.controllers').is_file():
    raise RuntimeError('Cgroup v2 is required')
cpu = dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())
peak = root / 'memory.peak'
disk = shutil.disk_usage(sys.argv[1])
print(json.dumps({
    'memory_bytes': int((root / 'memory.current').read_text()),
    'lifetime_peak_bytes': int(peak.read_text()) if peak.is_file() else None,
    'cpu_usage_usec': int(cpu['usage_usec']),
    'data_filesystem_free_bytes': disk.free,
    'data_filesystem_total_bytes': disk.total,
}))
"""
FIELDS = {
    "memory_bytes", "lifetime_peak_bytes", "cpu_usage_usec",
    "data_filesystem_free_bytes", "data_filesystem_total_bytes",
}


def sample(runtime: Runtime, manifest: Manifest) -> dict[str, int | None]:
    raw = runtime.run(
        "exec", manifest.container_name, "python", "-c", PROBE, manifest.data_dir,
        timeout=10,
    )
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != FIELDS:
            raise ValueError
        for key, number in value.items():
            if key == "lifetime_peak_bytes" and number is None:
                continue
            if type(number) is not int or number < 0:
                raise ValueError
        if value["data_filesystem_free_bytes"] > value["data_filesystem_total_bytes"]:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise Failure("Invalid resource counters; no measurement report was accepted.") from None


def measure(
    runtime: Runtime, manifest: Manifest, *, phase: str, seconds: float, interval: float
) -> dict[str, Any]:
    if (
        phase not in {"idle", "run", "pdf"}
        or not math.isfinite(seconds) or not 1 <= seconds <= 600
        or not math.isfinite(interval) or not 0.25 <= interval <= min(seconds, 10)
    ):
        raise Failure("Choose idle/run/pdf, 1–600 seconds and a 0.25–10 second interval.")
    runtime.check()
    before = runtime.require_owned(manifest)
    if not before.get("State", {}).get("Running"):
        raise Failure("Start the owned installation before measuring it.")
    container_id = before.get("Id")
    image_id = before.get("Image")
    if not isinstance(container_id, str) or not isinstance(image_id, str):
        raise Failure("The running container and image identities are required.")
    rows: list[dict[str, Any]] = []
    start = time.monotonic()
    while True:
        counters = sample(runtime, manifest)
        elapsed = time.monotonic() - start
        rows.append({"elapsed_seconds": round(elapsed, 6), **counters})
        if elapsed >= seconds:
            break
        time.sleep(min(interval, seconds - elapsed))
    after = runtime.require_owned(manifest)
    if (
        after.get("Id") != container_id or after.get("Image") != image_id
        or not after.get("State", {}).get("Running")
        or after.get("State", {}).get("StartedAt") != before.get("State", {}).get("StartedAt")
    ):
        raise Failure("Installation restarted or changed during measurement; discard the sample.")
    if any(
        b["cpu_usage_usec"] < a["cpu_usage_usec"]
        for a, b in zip(rows, rows[1:], strict=False)
    ):
        raise Failure("CPU counters reset during measurement; discard the sample.")
    return {
        "schema_version": 1,
        "method": "read-only private cgroup-v2 counters; exec sampling adds overhead",
        "phase": phase,
        "engine": manifest.runtime.name,
        "image_id": image_id,
        "requested_seconds": seconds,
        "interval_seconds": interval,
        "observed_seconds": rows[-1]["elapsed_seconds"],
        "sampled_peak_memory_bytes": max(row["memory_bytes"] for row in rows),
        "cpu_usage_delta_usec": rows[-1]["cpu_usage_usec"] - rows[0]["cpu_usage_usec"],
        "minimum_data_filesystem_free_bytes": min(
            row["data_filesystem_free_bytes"] for row in rows
        ),
        "samples": rows,
        "limits": [
            "Sampling can miss a short phase peak; memory.peak covers the container lifetime.",
            "Filesystem free space describes the backing filesystem, not application disk usage.",
            "This command does not trigger, authorize or verify a provider call or PDF workload.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=["idle", "run", "pdf"])
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--report", required=True, type=Path, help="new private JSON output file")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.install_dir / "installation.json")
        report = measure(
            Runtime(manifest.runtime), manifest, phase=args.phase,
            seconds=args.seconds, interval=args.interval,
        )
        descriptor = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    except (Failure, OSError):
        print(
            "Measurement failed. Check the saved installation, private cgroup-v2 support, "
            "and an unused report path; existing resources were retained.", file=sys.stderr,
        )
        return 1
    print("Resource sample saved. Review workload and sampling limits before citing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
