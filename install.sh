#!/bin/sh
# Resolve one published preview, then execute its hash-verified, digest-pinned launcher.
(
set -eu
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    printf '%s\n' 'Python 3.12 or newer is required.' >&2
    exit 1
fi
umask 077
temporary=$(mktemp -d "${TMPDIR:-/tmp}/pipeline-current.XXXXXXXX")
trap 'rm -rf -- "$temporary"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
status() {
    if [ -t 2 ] && [ "${TERM:-}" != dumb ] && [ "${NO_COLOR+x}" != x ]; then
        printf '\033[1;36m  %s\033[0m\n' "$1" >&2
    else
        printf '  %s\n' "$1" >&2
    fi
}
curl_progress=--silent
if [ -t 2 ] && [ "${TERM:-}" != dumb ]; then
    curl_progress=--progress-bar
fi
download() {
    if ! curl --disable --fail "$curl_progress" --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 30 --max-time 120 --max-filesize 2097152 --output "$1" "$2"; then
        printf 'Installation stopped: could not download %s from %s. Check your internet connection and GitHub availability, then retry.\n' "${1##*/}" "$2" >&2
        return 1
    fi
}
status 'Finding the latest complete preview…'
download "$temporary/releases.json" 'https://api.github.com/repos/Luke-Pitstick/internship-pipeline/releases?per_page=100'
version=$(python3 - "$temporary/releases.json" <<'PIPELINE_SELECT'
import json, re, sys

try:
    releases = json.load(open(sys.argv[1]))
except (OSError, json.JSONDecodeError):
    sys.exit('GitHub returned an invalid release listing. Retry when GitHub is available.')
if not isinstance(releases, list):
    if isinstance(releases, dict) and 'rate limit' in str(releases.get('message', '')).lower():
        sys.exit('GitHub API rate limit exceeded. Wait for the limit to reset, then rerun the installer.')
    sys.exit('GitHub returned an unexpected release listing. Check GitHub availability and retry.')
required = {'install.sh', 'release-metadata.json', 'bootstrap_installer.py'}
for release in releases:
    version = release.get('tag_name', '')
    if (not release.get('draft')
            and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+', version)
            and required <= {asset['name'] for asset in release.get('assets', [])}
            and any(asset['name'] == f'internship-pipeline-installer-{version}.tar.gz'
                    for asset in release.get('assets', []))):
        print(version)
        break
else:
    sys.exit('No complete published preview is available; nothing was installed.')
PIPELINE_SELECT
)
base="https://github.com/Luke-Pitstick/internship-pipeline/releases/download/$version"
status "Downloading $version and verifying release identity…"
download "$temporary/release-metadata.json" "$base/release-metadata.json"
download "$temporary/install.sh" "$base/install.sh"
python3 - "$temporary" "$version" <<'PIPELINE_VERIFY'
import hashlib, json, pathlib, re, sys

root = pathlib.Path(sys.argv[1])
metadata = json.loads((root / 'release-metadata.json').read_bytes())
if (metadata.get('repository') != 'Luke-Pitstick/internship-pipeline'
        or metadata.get('version') != sys.argv[2]
        or not re.fullmatch(r'[0-9a-f]{40}', metadata.get('source_commit', ''))
        or not re.fullmatch(r'ghcr.io/luke-pitstick/internship-pipeline@sha256:[0-9a-f]{64}',
                            metadata.get('image', ''))
        or hashlib.sha256((root / 'install.sh').read_bytes()).hexdigest()
            != metadata.get('launcher_sha256')):
    sys.exit('Release identity or launcher hash mismatch; nothing was executed.')
print(f"Installing {metadata['version']} from commit {metadata['source_commit'][:12]}")
PIPELINE_VERIFY
sh "$temporary/install.sh" "$@"
)
