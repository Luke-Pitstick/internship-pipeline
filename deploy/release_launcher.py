"""Render a versioned curl launcher bound to reviewed installer and image bytes."""

from __future__ import annotations

import re
import shlex


def render_launcher(
    *, repository: str, version: str, bootstrap_sha256: str, bundle_sha256: str, image: str
) -> str:
    """Return a POSIX launcher; its complete outer block must arrive before execution."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*", repository):
        raise ValueError("Supply a GitHub owner/repository without URL or shell syntax.")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", version):
        raise ValueError("Supply an explicit release version such as v0.1.0-rc.1.")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (bootstrap_sha256, bundle_sha256)):
        raise ValueError("Supply complete lowercase bootstrap and bundle SHA-256 values.")
    if not re.fullmatch(
        r"ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}", image
    ) or any(part in {"", ".", ".."} for part in image.split("@")[0].split("/")[1:]):
        raise ValueError("Supply an immutable lowercase GHCR image with a SHA-256 digest.")
    base = f"https://github.com/{repository}/releases/download/{version}"
    bundle = f"{base}/internship-pipeline-installer-{version}.tar.gz"
    # A complete compound command is parsed before anything in it runs. In particular,
    # ending a pipe early cannot execute a partially delivered download/install command.
    return f"""#!/bin/sh
# Generated for {repository} {version}; reruns preserve the saved installation image.
(
set -eu
case "${{1-}}" in
    -h|--help)
        cat <<'PIPELINE_HELP'
Install Internship Pipeline from this pinned release.
Usage: sh install.sh [--install-dir PATH] [--command-dir PATH] [--port PORT]
                     [--runtime docker|podman] [--ready-timeout SECONDS]
                     [--restore-source PATH --restore-from PATH]
For a pipe: curl -fsSL RELEASE_INSTALL_URL | sh -s -- [OPTIONS]
Requires Python 3.12+, curl, and a healthy local Docker or Podman endpoint.
Set up those prerequisites first; this installer does not install runtimes or VMs.
Saved installations retain their image, runtime, port and data on every rerun.
Restoration retains the stopped source's exact local image. Configure keys in Settings.
PIPELINE_HELP
        exit 0
        ;;
esac
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.12 or newer is required. Install Python, then rerun.' >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    printf '%s\n' 'Python 3.12 or newer is required. Upgrade Python, then rerun.' >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' 'curl is required. Install curl, then rerun.' >&2
    exit 1
fi
umask 077
temporary=$(mktemp -d "${{TMPDIR:-/tmp}}/pipeline-release.XXXXXXXX")
trap 'rm -rf -- "$temporary"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
curl --disable --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \\
    --connect-timeout 30 --max-time 120 --max-filesize 2097152 \\
    --output "$temporary/bootstrap_installer.py" {shlex.quote(base + "/bootstrap_installer.py")}
python3 - "$temporary/bootstrap_installer.py" {shlex.quote(bootstrap_sha256)} <<'PIPELINE_VERIFY'
import hashlib
import hmac
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
with path.open('rb') as stream:
    payload = stream.read(2097153)
if not 0 < len(payload) <= 2097152:
    sys.exit('Bootstrap download is empty or exceeds its size limit; nothing was executed.')
if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), sys.argv[2]):
    sys.exit('Bootstrap SHA-256 mismatch; nothing was executed.')
PIPELINE_VERIFY
python3 "$temporary/bootstrap_installer.py" \\
    --bundle-url {shlex.quote(bundle)} \\
    --sha256 {shlex.quote(bundle_sha256)} \\
    --version {shlex.quote(version)} \\
    --release-image {shlex.quote(image)} -- "$@"
)
"""
