"""Resolve and verify one complete public release using bounded HTTPS requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPOSITORY = "Luke-Pitstick/internship-pipeline"
VERSION = r"v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?"
LIMIT = 2 * 1024 * 1024


def fetch(url: str) -> bytes:
    """GitHub metadata is trusted through TLS, with bounded size and time."""
    from bootstrap_installer import HTTPSRedirects, require_https

    try:
        require_https(url)
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
        deadline = time.monotonic() + 120
        with urllib.request.build_opener(HTTPSRedirects()).open(request, timeout=30) as response:
            chunks = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise ValueError("GitHub metadata download exceeded its deadline.")
                chunk = response.read1(min(65536, LIMIT + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > LIMIT:
                    raise ValueError("GitHub response exceeds the release metadata limit.")
            payload = b"".join(chunks)
        if not payload or len(payload) > LIMIT:
            raise ValueError("GitHub response is empty or exceeds the release metadata limit.")
        return bytes(payload)
    except (OSError, urllib.error.URLError):
        raise ValueError(
            "Could not download GitHub release metadata; check connectivity and retry."
        ) from None


def require_forward_source(installed: str, target: str) -> None:
    """Admit newer code independently of the human-facing release numbering."""
    if not all(
        isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (installed, target)
    ):
        raise ValueError("Release source identity is invalid; update refused.")
    if installed == target:
        return
    try:
        # Page two omits file patches; only ancestry metadata is needed.
        comparison = json.loads(
            fetch(
                f"https://api.github.com/repos/{REPOSITORY}/compare/"
                f"{installed}...{target}?per_page=1&page=2"
            )
        )
        if (
            comparison["status"] != "ahead"
            or comparison["base_commit"]["sha"] != installed
            or comparison["merge_base_commit"]["sha"] != installed
        ):
            raise ValueError("Target source is older or divergent; downgrade refused.")
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("Could not verify release source ancestry; update refused.") from None


@dataclass(frozen=True)
class Release:
    version: str
    source_commit: str
    image: str
    storage_format: int
    bootstrap_sha256: str
    bundle_sha256: str
    launcher_sha256: str

    @classmethod
    def parse(cls, metadata: dict[str, Any], version: str) -> Release:
        try:
            release = cls(**{key: metadata[key] for key in cls.__dataclass_fields__})
            if (
                type(metadata.get("schema")) is not int
                or metadata["schema"] != 1
                or metadata.get("repository") != REPOSITORY
                or release.version != version
                or not re.fullmatch(VERSION, release.version)
                or not re.fullmatch(r"[0-9a-f]{40}", release.source_commit)
                or not re.fullmatch(
                    r"ghcr\.io/luke-pitstick/internship-pipeline@sha256:[0-9a-f]{64}", release.image
                )
                or type(release.storage_format) is not int
                or release.storage_format < 1
                or not all(
                    re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in (
                        release.bootstrap_sha256,
                        release.bundle_sha256,
                        release.launcher_sha256,
                    )
                )
            ):
                raise ValueError
            return release
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "Release identity or storage format is invalid; nothing was updated."
            ) from None

    @property
    def base(self) -> str:
        return f"https://github.com/{REPOSITORY}/releases/download/{self.version}"

    def stage(self, destination: Path) -> Path:
        from bootstrap_installer import download, unpack

        # Verify every published executable asset before retaining the target bundle.
        download(self.base + "/bootstrap_installer.py", self.bootstrap_sha256, progress=False)
        download(self.base + "/install.sh", self.launcher_sha256, progress=False)
        payload = download(
            f"{self.base}/internship-pipeline-installer-{self.version}.tar.gz", self.bundle_sha256
        )
        try:
            bundle = unpack(payload, destination, self.version)
        except tarfile.TarError:
            raise ValueError("Release archive is invalid; the original app is unchanged.") from None
        if (
            hashlib.sha256((bundle / "bootstrap_installer.py").read_bytes()).hexdigest()
            != self.bootstrap_sha256
        ):
            raise ValueError("The bundled bootstrap differs from the published bootstrap.")
        return bundle


def select_release(releases: Any) -> str:
    """Select the most recently published complete release, including numbering resets."""
    try:
        if isinstance(releases, dict) and "rate limit" in str(releases.get("message", "")).lower():
            raise ValueError("GitHub API rate limit exceeded; wait for its reset and retry.")
        if not isinstance(releases, list):
            raise ValueError("GitHub returned an invalid release listing.")
        complete = []
        for item in releases:
            if not isinstance(item, dict):
                raise ValueError("GitHub returned an invalid release entry.")
            version = item.get("tag_name", "")
            if (
                not isinstance(version, str)
                or not re.fullmatch(VERSION, version)
                or item.get("draft")
            ):
                continue
            required = {
                "install.sh",
                "release-metadata.json",
                "bootstrap_installer.py",
                f"internship-pipeline-installer-{version}.tar.gz",
            }
            if not required <= {asset["name"] for asset in item.get("assets", [])}:
                continue
            published = item.get("published_at")
            identifier = item.get("id")
            if (
                not isinstance(published, str)
                or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", published)
                or type(identifier) is not int
                or identifier <= 0
            ):
                raise ValueError("Published release identity or timestamp is invalid.")
            complete.append((datetime.fromisoformat(published), identifier, version))
        if complete:
            return max(complete)[2]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError(
            "GitHub returned malformed release metadata; nothing was updated."
        ) from None
    raise ValueError("No complete published release is available; nothing was updated.")


def latest() -> Release:
    version = select_release(
        json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"))
    )
    metadata = json.loads(
        fetch(f"https://github.com/{REPOSITORY}/releases/download/{version}/release-metadata.json")
    )
    return Release.parse(metadata, version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    select = actions.add_parser("select")
    select.add_argument("listing", type=Path)
    verify = actions.add_parser("verify")
    verify.add_argument("metadata", type=Path)
    verify.add_argument("launcher", type=Path)
    verify.add_argument("version")
    args = parser.parse_args()
    try:
        if args.action == "select":
            print(select_release(json.loads(args.listing.read_bytes())))
        else:
            release = Release.parse(json.loads(args.metadata.read_bytes()), args.version)
            if hashlib.sha256(args.launcher.read_bytes()).hexdigest() != release.launcher_sha256:
                raise ValueError(
                    "Release identity or launcher hash mismatch; nothing was executed."
                )
            print(f"Installing {release.version} from commit {release.source_commit[:12]}")
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
