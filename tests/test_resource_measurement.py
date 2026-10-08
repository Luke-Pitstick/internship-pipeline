"""Resource reports fail closed on wrong scope, restarts and invalid counters."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
SPEC = importlib.util.spec_from_file_location(
    "resource_measurement", DEPLOY / "measure-resources.py"
)
assert SPEC and SPEC.loader
measurements = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurements)


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.replaced = False
        self.running = True
        self.counter = 0
        self.payload = None
        self.reset_cpu = False
        self.inspections = 0

    def check(self):
        pass

    def require_owned(self, manifest):
        self.inspections += 1
        return {
            "Id": "changed" if self.replaced and self.inspections > 1 else "owned-id",
            "Image": "sha256:" + "a" * 64,
            "State": {"Running": self.running, "StartedAt": "synthetic-start"},
        }

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.counter += 1
        return self.payload if self.payload is not None else json.dumps({
            "memory_bytes": self.counter * 100,
            "lifetime_peak_bytes": None,
            "cpu_usage_usec": 100 - self.counter if self.reset_cpu else self.counter * 10,
            "data_filesystem_free_bytes": 1000 - self.counter,
            "data_filesystem_total_bytes": 2000,
        })


@pytest.fixture
def manifest():
    return SimpleNamespace(
        runtime=SimpleNamespace(name="docker"), container_name="owned-container",
        data_dir="/var/data/restored",
    )


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(measurements.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        measurements.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay)
    )


def test_report_measures_existing_owned_container_and_marks_sampling_limits(manifest, clock):
    runtime = FakeRuntime()
    report = measurements.measure(runtime, manifest, phase="pdf", seconds=1, interval=0.5)
    assert report["sampled_peak_memory_bytes"] == 300
    assert report["cpu_usage_delta_usec"] == 20
    assert report["minimum_data_filesystem_free_bytes"] == 997
    assert len(report["samples"]) == 3
    assert "container lifetime" in report["limits"][0]
    assert all(args[:2] == ("exec", "owned-container") for args, _ in runtime.calls)
    assert all(args[-1] == "/var/data/restored" for args, _ in runtime.calls)
    assert all(options["timeout"] == 10 for _, options in runtime.calls)


@pytest.mark.parametrize("payload", [
    "private-error-details", "null", "[]", '{"credential":"private-value"}',
    '{"memory_bytes":true,"lifetime_peak_bytes":null,"cpu_usage_usec":1,'
    '"data_filesystem_free_bytes":1,"data_filesystem_total_bytes":2}',
])
def test_unexpected_counter_output_is_rejected_without_leaking_it(manifest, payload):
    runtime = FakeRuntime()
    runtime.payload = payload
    with pytest.raises(measurements.Failure, match="Invalid resource counters") as error:
        measurements.sample(runtime, manifest)
    assert "private" not in str(error.value)


def test_stopped_instance_does_not_start_or_execute_a_probe(manifest, clock):
    runtime = FakeRuntime()
    runtime.running = False
    with pytest.raises(measurements.Failure, match="Start the owned installation"):
        measurements.measure(runtime, manifest, phase="idle", seconds=1, interval=1)
    assert not runtime.calls


@pytest.mark.parametrize("changed", ["replaced", "reset_cpu"])
def test_restarted_or_replaced_container_is_rejected(manifest, clock, changed):
    runtime = FakeRuntime()
    setattr(runtime, changed, True)
    with pytest.raises(measurements.Failure, match="discard the sample"):
        measurements.measure(runtime, manifest, phase="run", seconds=1, interval=0.5)


@pytest.mark.parametrize("seconds,interval", [(float("nan"), 1), (601, 1), (1, 0), (1, 2)])
def test_sampling_is_bounded_before_contacting_engine(manifest, seconds, interval):
    runtime = FakeRuntime()
    with pytest.raises(measurements.Failure, match="Choose idle/run/pdf"):
        measurements.measure(runtime, manifest, phase="run", seconds=seconds, interval=interval)
    assert runtime.inspections == 0


@pytest.mark.parametrize("namespace", ["0::/", "0::/host/other-container"])
@pytest.mark.parametrize("optimize", [0, 1])
def test_probe_refuses_host_scope_and_reads_private_numeric_counters(
    monkeypatch, capsys, namespace, optimize
):
    files = {
        "/proc/self/cgroup": namespace,
        "/sys/fs/cgroup/cpu.stat": "usage_usec 123\nuser_usec 100\nsystem_usec 23\n",
        "/sys/fs/cgroup/memory.current": "256",
    }
    monkeypatch.setattr(Path, "read_text", lambda path: files[str(path)])
    monkeypatch.setattr(Path, "is_file", lambda path: path.name == "cgroup.controllers")
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: SimpleNamespace(free=500, total=1000)
    )
    monkeypatch.setattr(sys, "argv", ["probe", "/var/data/restored"])
    probe = compile(measurements.PROBE, "resource-probe", "exec", optimize=optimize)
    if namespace != "0::/":
        with pytest.raises(RuntimeError, match="private cgroup"):
            exec(probe, {})
        assert capsys.readouterr().out == ""
    else:
        exec(probe, {})
        assert json.loads(capsys.readouterr().out) == {
            "memory_bytes": 256, "lifetime_peak_bytes": None, "cpu_usage_usec": 123,
            "data_filesystem_free_bytes": 500, "data_filesystem_total_bytes": 1000,
        }
