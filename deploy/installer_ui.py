"""Small terminal presentation layer for the dependency-free installer bundle."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import TextIO


class InstallProgress:
    """Show completed stages and elapsed activity without inventing byte progress."""

    def __init__(self, total: int = 4, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.total = total
        self.completed = 0
        self.label = ""
        self.started = 0.0
        self.interactive = self.stream.isatty() and os.environ.get("TERM") != "dumb"
        self.color = self.interactive and "NO_COLOR" not in os.environ
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None

    def style(self, text: str, code: str, *, stream: TextIO | None = None) -> str:
        use_color = self.color and (stream is None or stream.isatty())
        return f"\033[{code}m{text}\033[0m" if use_color else text

    def write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def header(self) -> None:
        self.write("\n" + self.style("  Internship Pipeline", "1;36") + "\n")
        self.write("  Your local job-search workspace\n\n")

    def start(self, label: str) -> None:
        self.finish()
        self.label = label
        self.started = time.perf_counter()
        self.stop.clear()
        if self.interactive:
            self.render(0)
            self.worker = threading.Thread(target=self.animate, daemon=True)
            self.worker.start()
        else:
            self.write(f"  [{self.completed + 1}/{self.total}] {label}\n")

    def render(self, frame: int) -> None:
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
        bar = "=" * (self.completed * 12 // self.total)
        bar = bar.ljust(12, "-")
        elapsed = int(time.perf_counter() - self.started)
        spinner = "|/-\\"[frame % 4]
        line = f"  {spinner} [{bar}] {self.completed}/{self.total} {self.label} ({elapsed}s)"
        # Keep updates on one line, even in a narrow terminal.
        self.write("\r\033[2K" + self.style(line[: max(1, width - 1)], "36"))

    def animate(self) -> None:
        frame = 1
        while not self.stop.wait(0.12):
            self.render(frame)
            frame += 1

    def finish(self, success: bool = True) -> None:
        if not self.label:
            return
        self.stop.set()
        if self.worker is not None:
            self.worker.join()
            self.worker = None
        if success:
            self.completed += 1
        prefix = "\r\033[2K" if self.interactive else ""
        status = "OK" if success else "STOPPED"
        elapsed = time.perf_counter() - self.started
        self.write(
            prefix
            + self.style(f"  {status}", "32" if success else "31")
            + f" [{self.completed}/{self.total}] {self.label} ({elapsed:.1f}s)\n"
        )
        self.label = ""
        if self.interactive and success and self.completed == self.total:
            self.write(self.style(f"  [============] {self.total}/{self.total} complete\n", "32"))
