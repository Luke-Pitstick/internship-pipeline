#!/bin/sh
# Local bundle launcher; a reviewed public download endpoint is not assigned yet.
set -eu
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.12 or newer is required. Install Python, then rerun this local installer.' >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    printf '%s\n' 'Python 3.12 or newer is required for this installer candidate.' >&2
    exit 1
fi
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -f "$bundle_dir/install.py" ] || [ ! -f "$bundle_dir/pipeline_runtime.py" ] || [ ! -f "$bundle_dir/pipeline_management.py" ] || [ ! -f "$bundle_dir/internship-pipeline" ]; then
    printf '%s\n' 'Use the complete reviewed local deploy bundle. No hosted streaming installer has been published.' >&2
    exit 1
fi
exec python3 "$bundle_dir/install.py" "$@"
