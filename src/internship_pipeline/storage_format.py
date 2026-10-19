"""Declare the persistent data contract without opening an installation.

Increment this identifier when a change to databases, configuration, credential
encryption, or retained files makes the existing format incompatible. It is
independent of application versions, backup archive formats, and host manifests.
"""

from __future__ import annotations

import json

STORAGE_FORMAT = 1


def main() -> int:
    """Print machine-readable image metadata without configuration or data access."""
    print(json.dumps({"storage_format": STORAGE_FORMAT}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
