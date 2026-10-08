#!/usr/bin/env python3
"""Freeze a clean source revision into a versioned, digest-pinned curl installer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from build_installer_bundle import ARCHIVE_FILES, build_bundle
from release_launcher import render_launcher

GENERATOR_FILES = ("build_release_assets.py", "build_installer_bundle.py", "release_launcher.py")
SOURCE_FILES = (
    "LICENSE",
    "deploy/bootstrap_installer.py",
    "pyproject.toml",
    "uv.lock",
    "web/package-lock.json",
    *("deploy/" + name for name in ARCHIVE_FILES if name != "LICENSE"),
    *("deploy/" + name for name in GENERATOR_FILES),
)


def clean_source(source_dir: Path, source_commit: str) -> None:
    """Reject dirty/untracked source or a revision other than the accepted candidate."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Supply the complete lowercase source SHA.")
    for args, expected in (
        (["rev-parse", "HEAD"], source_commit),
        (["status", "--porcelain", "--untracked-files=all"], ""),
    ):
        actual = subprocess.check_output(["git", "-C", str(source_dir), *args], text=True).strip()
        if actual != expected:
            raise ValueError("Release source must be clean and match the accepted source SHA.")
    for name in SOURCE_FILES:
        path = source_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Release input must be a regular committed file: {name}")
        try:
            committed = subprocess.check_output(
                ["git", "-C", str(source_dir), "show", f"{source_commit}:{name}"],
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"Release input is not committed: {name}") from exc
        if path.read_bytes() != committed:
            raise ValueError(f"Release input differs from committed bytes: {name}")
    for name in GENERATOR_FILES:
        if (Path(__file__).resolve().parent / name).read_bytes() != (
            source_dir / "deploy" / name
        ).read_bytes():
            raise ValueError(f"Executing generator differs from accepted source: {name}")


def build_release_assets(
    source_dir: Path,
    output_dir: Path,
    *,
    repository: str,
    version: str,
    source_commit: str,
    image: str,
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    """Generate all assets once; no network access or registry/release mutation."""
    # Validate renderer identities before creating any output.
    render_launcher(
        repository=repository,
        version=version,
        bootstrap_sha256="0" * 64,
        bundle_sha256="0" * 64,
        image=image,
    )
    if not image.startswith(f"ghcr.io/{repository.lower()}@sha256:"):
        raise ValueError("The image must use this repository's GHCR package and a digest.")
    clean_source(source_dir, source_commit)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Release output already exists; use a fresh directory.")
    bootstrap_path = source_dir / "deploy/bootstrap_installer.py"
    if bootstrap_path.is_symlink() or not bootstrap_path.is_file():
        raise ValueError("The bootstrap must be a regular source file.")
    bootstrap = bootstrap_path.read_bytes()
    if not bootstrap or len(bootstrap) > 1024 * 1024:
        raise ValueError("The bootstrap is empty or too large.")
    bundle = build_bundle(source_dir / "deploy", output_dir, version, source_commit)
    bootstrap_digest = hashlib.sha256(bootstrap).hexdigest()
    launcher = render_launcher(
        repository=repository,
        version=version,
        bootstrap_sha256=bootstrap_digest,
        bundle_sha256=str(bundle["archive_sha256"]),
        image=image,
    ).encode()
    for name, payload in (
        ("bootstrap_installer.py", bootstrap),
        ("install.sh", launcher),
        ("LICENSE", (source_dir / "LICENSE").read_bytes()),
    ):
        with (output_dir / name).open("xb") as stream:
            stream.write(payload)
    (output_dir / "install.sh").chmod(0o755)
    metadata: dict[str, object] = {
        "schema": 1,
        "repository": repository,
        "version": version,
        "source_commit": source_commit,
        "image": image,
        "bootstrap_sha256": bootstrap_digest,
        "bundle_sha256": bundle["archive_sha256"],
        "launcher_sha256": hashlib.sha256(launcher).hexdigest(),
        "candidate": candidate,
        "publication": "Draft prerelease; anonymous hosting and host acceptance remain separate.",
    }
    (output_dir / "release-metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    )
    names = sorted(path.name for path in output_dir.iterdir())
    (output_dir / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}  {name}\n"
            for name in names
        )
    )
    return metadata


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    cli.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--repository", required=True)
    cli.add_argument("--version", required=True)
    cli.add_argument("--source-commit", required=True)
    cli.add_argument("--image", required=True)
    cli.add_argument("--candidate-metadata", type=Path)
    args = cli.parse_args()
    try:
        candidate = (
            json.loads(args.candidate_metadata.read_text()) if args.candidate_metadata else None
        )
        result = build_release_assets(
            args.source_dir,
            args.output_dir,
            repository=args.repository,
            version=args.version,
            source_commit=args.source_commit,
            image=args.image,
            candidate=candidate,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Release assets failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
