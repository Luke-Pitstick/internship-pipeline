"""Readiness must fail closed for failures and unexpected HTTP payloads."""

import io
from urllib.error import URLError

import pytest

from internship_pipeline import healthcheck


@pytest.mark.parametrize("status,payload,expected", [
    (200, b'{"ready":true,"mode":"setup"}', 0),
    (200, b'{"ready":true,"mode":"owner"}', 0),
    (200, b'{"ready":false,"mode":"owner"}', 1),
    (200, b'{"ready":true,"mode":"unknown"}', 1),
    (503, b'{"ready":true,"mode":"owner"}', 1),
    (200, b'<html>proxy error</html>', 1),
])
def test_readiness_response(monkeypatch, status, payload, expected):
    class Response(io.BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "http://127.0.0.1:8080/readyz"
            assert request.get_header("Host") == "pipeline.example.test"
            assert timeout == 3
            response = Response(payload)
            response.status = status
            return response

    monkeypatch.setenv("PIPELINE_ORIGIN", "https://pipeline.example.test")
    monkeypatch.setattr(healthcheck, "build_opener", lambda *handlers: Opener())
    assert healthcheck.main() == expected


def test_connection_failure_is_unhealthy_and_quiet(monkeypatch, capsys):
    class Opener:
        def open(self, *args, **kwargs):
            raise URLError("synthetic private diagnostic")

    monkeypatch.setattr(healthcheck, "build_opener", lambda *handlers: Opener())
    assert healthcheck.main() == 1
    assert capsys.readouterr() == ("", "")
