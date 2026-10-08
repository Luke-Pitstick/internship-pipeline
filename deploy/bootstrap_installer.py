#!/usr/bin/env python3
"""Fetch a reviewed versioned installer, verify its digest, then launch its shell entrypoint."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import io
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

BUNDLE_FILES = (
    "install.sh",
    "install.py",
    "pipeline_runtime.py",
    "pipeline_management.py",
    "internship-pipeline",
    "LICENSE",
)
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_TAR_BYTES = len(BUNDLE_FILES) * MAX_FILE_BYTES + 1024 * 1024


def require_https(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Download URLs must use HTTPS, without credentials or fragments.")


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    """Allow normal artifact CDN redirects, but never leave verified TLS."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def download(url: str, expected_sha256: str) -> bytes:
    require_https(url)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Supply the complete lowercase SHA-256 from the reviewed trust source.")
    opener = urllib.request.build_opener(HTTPSRedirects())
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    deadline = time.monotonic() + 120
    with opener.open(request, timeout=30) as response:
        require_https(response.geturl())
        if response.status != 200:
            raise ValueError(f"Download returned HTTP {response.status}; expected 200.")
        length_text = response.headers.get("Content-Length")
        length = None
        if length_text is not None:
            if not re.fullmatch(r"[0-9]+", length_text):
                raise ValueError("Download supplied an invalid Content-Length.")
            length = int(length_text)
            if not 0 < length <= MAX_DOWNLOAD_BYTES:
                raise ValueError("Download is empty or exceeds the installer size limit.")
        chunks: list[bytes] = []
        size = 0
        while True:
            if time.monotonic() > deadline:
                raise ValueError("Installer download exceeded its deadline.")
            chunk = response.read1(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError("Download exceeds the installer size limit.")
            chunks.append(chunk)
    if size == 0 or (length is not None and size != length):
        raise ValueError("Installer download is empty or incomplete.")
    payload = b"".join(chunks)
    if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_sha256):
        raise ValueError("Installer SHA-256 mismatch; nothing was extracted or executed.")
    return payload


def unpack(payload: bytes, destination: Path, version: str) -> Path:
    """Validate the entire archive, then write only fixed filenames in a private directory."""
    stem = f"internship-pipeline-installer-{version}"
    expected = {f"{stem}/{name}" for name in BUNDLE_FILES}
    # Bound decompression and consume the gzip trailer (including CRC) before tar parsing.
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
        raw_tar = compressed.read(MAX_TAR_BYTES + 1)
    if len(raw_tar) > MAX_TAR_BYTES:
        raise ValueError("Installer archive expands beyond the size limit.")
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        for member in archive:
            if (
                member.name not in expected
                or member.name in files
                or not member.isfile()
                or member.pax_headers
                or not 0 < member.size <= MAX_FILE_BYTES
            ):
                raise ValueError("Installer archive contains an unsafe, extra or duplicate member.")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Installer archive member cannot be read.")
            with stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) != member.size:
                raise ValueError("Installer archive contains an incomplete file.")
            files[member.name] = data
    if set(files) != expected:
        raise ValueError(
            "Installer archive is incomplete; five deploy files and LICENSE are required."
        )
    bundle = destination / stem
    bundle.mkdir(mode=0o700)
    # Never use tar extraction paths, link handling, owner fields or stored modes.
    for name in BUNDLE_FILES:
        target = bundle / name
        with target.open("xb") as output:
            output.write(files[f"{stem}/{name}"])
        target.chmod(0o700 if name in {"install.sh", "internship-pipeline"} else 0o600)
    return bundle


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    cli.add_argument(
        "--bundle-url", required=True, help="HTTPS URL ending in the versioned filename"
    )
    cli.add_argument(
        "--sha256", required=True, help="reviewed archive SHA-256; never fetched implicitly"
    )
    cli.add_argument("--version", required=True, help="reviewed release version, e.g. v0.1.0-rc.1")
    images = cli.add_mutually_exclusive_group()
    images.add_argument(
        "--image", help="reviewed OCI image digest; omit for saved-manifest reruns/restore"
    )
    images.add_argument(
        "--release-image",
        help="pinned release default; saved installations/restores retain their image",
    )
    cli.add_argument("installer_args", nargs=argparse.REMAINDER, help="installer options after --")
    args = cli.parse_args(argv)
    try:
        if sys.version_info < (3, 12):  # noqa: UP036 - standalone host prerequisite check
            raise ValueError("Python 3.12 or newer is required.")
        if not re.fullmatch(
            r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", args.version
        ):
            raise ValueError("Supply an explicit release version such as v0.1.0-rc.1.")
        expected_name = f"internship-pipeline-installer-{args.version}.tar.gz"
        if urlsplit(args.bundle_url).path.rsplit("/", 1)[-1] != expected_name:
            raise ValueError("Bundle URL filename must match the supplied release version.")
        forwarded = args.installer_args
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        if any(
            item.partition("=")[0] in {"--im", "--ima", "--imag", "--image"}
            or (item.startswith("--") and "--default-image".startswith(item.partition("=")[0]))
            for item in forwarded
        ):
            raise ValueError("Installer options cannot override the reviewed image digest.")
        restore_flags = {item.partition("=")[0] for item in forwarded} & {
            "--restore-source",
            "--restore-from",
        }
        if restore_flags:
            if len(restore_flags) != 2 or args.image is not None:
                raise ValueError("Restoration requires both restore flags and no --image override.")
            image_args: list[str] = []
        else:
            # First installation requires an image; reruns preserve the saved manifest
            # image, including a stopped-source restoration's inspected local image ID.
            image_args = ["--image", args.image] if args.image is not None else []
        for image in (args.image, args.release_image):
            if image is not None and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}", image
            ):
                raise ValueError(
                    "Supply the reviewed image reference with a complete sha256 digest."
                )
        if args.release_image is not None:
            image_args = ["--default-image", args.release_image]
        payload = download(args.bundle_url, args.sha256)
        with tempfile.TemporaryDirectory(prefix="pipeline-reviewed-installer-") as temporary:
            bundle = unpack(payload, Path(temporary), args.version)
            return subprocess.run(
                ["sh", str(bundle / "install.sh"), *forwarded, *image_args],
                check=False,
            ).returncode
    except (OSError, ValueError, EOFError, tarfile.TarError, urllib.error.URLError) as exc:
        print(f"Installer bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
