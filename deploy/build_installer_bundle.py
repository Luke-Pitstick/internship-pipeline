#!/usr/bin/env python3
"""Build a deterministic, allowlisted installer archive and its review metadata."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

BUNDLE_FILES = (
    "install.sh",
    "install.py",
    "pipeline_runtime.py",
    "pipeline_management.py",
    "internship-pipeline",
)
ARCHIVE_FILES = (*BUNDLE_FILES, "LICENSE")
MAX_FILE_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024


def build_bundle(
    deploy_dir: Path, output_dir: Path, version: str, source_commit: str
) -> dict[str, object]:
    """Read the five deploy files and root license; fail rather than replace output."""
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", version):
        raise ValueError("Use an explicit release version such as v0.1.0-rc.1.")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Supply the complete lowercase Git source commit SHA.")
    source: dict[str, bytes] = {}
    for name in ARCHIVE_FILES:
        path = deploy_dir.parent / "LICENSE" if name == "LICENSE" else deploy_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Installer source must be a regular file: {name}")
        data = path.read_bytes()
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError(f"Installer source is empty or too large: {name}")
        source[name] = data

    stem = f"internship-pipeline-installer-{version}"
    archive_name = f"{stem}.tar.gz"
    output_names = (archive_name, f"{archive_name}.sha256", f"{stem}.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(
        (output_dir / name).exists() or (output_dir / name).is_symlink() for name in output_names
    ):
        raise ValueError("Output already exists; use a fresh directory for this candidate.")
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in source.items():
                member = tarfile.TarInfo(f"{stem}/{name}")
                member.size = len(data)
                member.mode = 0o755 if name in {"install.sh", "internship-pipeline"} else 0o644
                # TarInfo defaults: mtime/uid/gid = 0, uname/gname = empty.
                archive.addfile(member, io.BytesIO(data))
    payload = compressed.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("Installer archive exceeds the bootstrap download size limit.")
    digest = hashlib.sha256(payload).hexdigest()
    metadata: dict[str, object] = {
        "schema": 1,
        "version": version,
        "source_commit": source_commit,
        "archive": archive_name,
        "archive_bytes": len(payload),
        "archive_sha256": digest,
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in source.items()
        },
        "scope": "Installer bytes only; image/support/provenance/publication gates are separate.",
    }
    outputs = (
        payload,
        f"{digest}  {archive_name}\n".encode(),
        (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode(),
    )
    for name, data in zip(output_names, outputs, strict=True):
        with (output_dir / name).open("xb") as stream:
            stream.write(data)
    return metadata


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    cli.add_argument("--deploy-dir", type=Path, default=Path(__file__).resolve().parent)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--version", required=True)
    cli.add_argument("--source-commit", required=True)
    args = cli.parse_args()
    try:
        metadata = build_bundle(args.deploy_dir, args.output_dir, args.version, args.source_commit)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f"Bundle failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
