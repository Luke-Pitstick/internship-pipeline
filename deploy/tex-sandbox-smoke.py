"""Diagnose isolated TeX rendering using only a fixed synthetic document."""

import os
import subprocess
import tempfile
from pathlib import Path

from internship_pipeline.resumes.tex_sandbox import command

with tempfile.TemporaryDirectory(prefix="synthetic-tex-smoke-") as directory:
    root = Path(directory)
    (root / "resume.tex").write_text(
        r"\documentclass{article}\begin{document}Synthetic compiler check."
        r"\begin{itemize}\item Synthetic bullet.\end{itemize}\end{document}"
    )
    result = subprocess.run(
        command(
            "pdflatex",
            root,
            ["-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
        ),
        cwd=root,
        env={
            "PATH": os.defpath,
            "HOME": str(root),
            "TMPDIR": str(root),
            "openin_any": "p",
            "openout_any": "p",
            "TEXMFOUTPUT": str(root),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        print(result.stdout[-6000:])
        print(result.stderr[-2000:])
        raise SystemExit(f"Synthetic isolated compiler failed ({result.returncode})")
    assert (root / "resume.pdf").read_bytes().startswith(b"%PDF-")
    print("PASS isolated synthetic TeX rendering")
