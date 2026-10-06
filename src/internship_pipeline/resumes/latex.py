"""Bounded compiler for application-owned LaTeX documents."""
from __future__ import annotations
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from internship_pipeline.resumes.errors import ResumeMatcherError
from internship_pipeline.resumes.validation import ResumeValidationError

class LatexCompiler:
    def __init__(self, executable: str = "pdflatex"):
        self.executable = executable

    @property
    def identity(self) -> dict[str, str]:
        return {"engine": self.executable, "flags_revision": "1"}

    def compile(self, source: str, deadline: float) -> bytes:
        with tempfile.TemporaryDirectory(prefix="internship-latex-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / "resume.tex"
            path.write_bytes(source.encode("utf-8"))
            path.chmod(0o600)
            environment = os.environ.copy()
            environment.update({"openin_any": "p", "openout_any": "p", "TEXMFOUTPUT": str(root)})
            for _ in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ResumeMatcherError("LaTeX compilation deadline exceeded", retryable=True)
                try:
                    process = subprocess.Popen(
                        [
                            self.executable,
                            "-no-shell-escape",
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            "-file-line-error",
                            path.name,
                        ],
                        cwd=root,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise ResumeValidationError(
                        "LaTeX compiler is unavailable; install the original template's "
                        "TeX dependencies"
                    ) from exc
                try:
                    process.communicate(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise ResumeMatcherError(
                        "LaTeX compilation deadline exceeded", retryable=True
                    ) from exc
                except BaseException:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                    raise
                if process.returncode != 0:
                    raise ResumeValidationError(
                        "Original LaTeX did not compile; check template packages/assets locally"
                    )
            log_path = root / "resume.log"
            if log_path.is_file() and re.search(
                r"Overfull \\[hv]box", log_path.read_text(errors="replace")
            ):
                raise ResumeValidationError(
                    "LaTeX reports text overflow; inspect the original/tailored source layout"
                )
            pdf = root / "resume.pdf"
            if not pdf.is_file() or pdf.stat().st_size > 16 * 1024 * 1024:
                raise ResumeValidationError(
                    "LaTeX compiler produced missing or excessive PDF output"
                )
            return pdf.read_bytes()
