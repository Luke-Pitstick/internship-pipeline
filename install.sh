#!/bin/sh
# Resolve the latest complete release, then execute its verified, digest-pinned launcher.
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
download "$temporary/pipeline_release.py" 'https://raw.githubusercontent.com/Luke-Pitstick/internship-pipeline/main/deploy/pipeline_release.py'
status 'Finding the latest complete release…'
download "$temporary/releases.json" 'https://api.github.com/repos/Luke-Pitstick/internship-pipeline/releases?per_page=100'
version=$(python3 "$temporary/pipeline_release.py" select "$temporary/releases.json")
base="https://github.com/Luke-Pitstick/internship-pipeline/releases/download/$version"
status "Downloading $version and verifying release identity…"
download "$temporary/release-metadata.json" "$base/release-metadata.json"
download "$temporary/install.sh" "$base/install.sh"
python3 "$temporary/pipeline_release.py" verify "$temporary/release-metadata.json" "$temporary/install.sh" "$version"
sh "$temporary/install.sh" "$@"
)
