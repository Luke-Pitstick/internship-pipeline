"""Readiness command shared by image metadata and explicit runtime health checks."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def main() -> int:
    origin = os.environ.get("PIPELINE_ORIGIN", "http://localhost:8080")
    try:
        request = Request("http://127.0.0.1:8080/readyz", headers={"Host": urlsplit(origin).netloc})
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=3) as response:
            payload = json.loads(response.read(1024))
            return 0 if response.status == 200 and payload in (
                {"ready": True, "mode": "setup"}, {"ready": True, "mode": "owner"}
            ) else 1
    except (OSError, URLError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
