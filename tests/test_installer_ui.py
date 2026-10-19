"""Installer terminal output stays usable in logs and releases animation resources."""

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
from installer_ui import InstallProgress  # noqa: E402


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_redirected_output_has_no_terminal_controls_or_false_completion():
    output = io.StringIO()
    progress = InstallProgress(stream=output)
    progress.header()
    progress.start("Checking engine")
    progress.start("Installing command")
    progress.finish(success=False)
    text = output.getvalue()
    assert "\033" not in text and "\r" not in text
    assert "OK [1/4] Checking engine" in text
    assert "STOPPED [1/4] Installing command" in text
    assert "complete" not in text


@pytest.mark.parametrize("success", [True, False])
def test_terminal_animation_stops_on_completion_and_failure(monkeypatch, success):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("NO_COLOR", "")
    output = Terminal()
    progress = InstallProgress(total=1, stream=output)
    progress.start("Waiting for readiness")
    worker = progress.worker
    assert worker is not None
    progress.finish(success=success)
    assert not worker.is_alive()
    assert progress.worker is None
    text = output.getvalue()
    assert "\033[36m" not in text
    assert ("1/1 complete" in text) is success
    assert ("STOPPED" in text) is not success


def test_dumb_terminal_uses_plain_logs(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    output = Terminal()
    progress = InstallProgress(total=1, stream=output)
    progress.start("Checking engine")
    progress.finish()
    assert "\033" not in output.getvalue()
    assert progress.worker is None


def test_animation_fits_narrow_terminal_and_redirected_summary_is_plain(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        "installer_ui.shutil.get_terminal_size", lambda **_: os.terminal_size((30, 24))
    )
    output = Terminal()
    progress = InstallProgress(stream=output)
    progress.label = "Preparing storage and downloading application image"
    progress.render(0)
    visible = output.getvalue().removeprefix("\r\033[2K\033[36m").removesuffix("\033[0m")
    assert len(visible) < 30
    assert progress.style("Ready", "1;32", stream=io.StringIO()) == "Ready"
