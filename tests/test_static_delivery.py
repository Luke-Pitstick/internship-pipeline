"""Real response negotiation for the static mount and authenticated API boundary."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_dashboard_api import api as dashboard_fixture
from test_owner_app import claim

from internship_pipeline.app import create_app

api = dashboard_fixture


def test_static_gzip_negotiation_preserves_content_and_api_scope(tmp_path: Path, api) -> None:
    web = tmp_path / "web"
    web.mkdir()
    content = "const syntheticValue = 'release-acceptance';\n" * 300
    (web / "app.js").write_text(content)
    app = create_app(
        tmp_path / "installation",
        origin="http://localhost:8080",
        static_dir=web,
        settings=api.settings,
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        compressed = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
        assert compressed.status_code == 200
        assert compressed.headers["content-encoding"] == "gzip"
        assert "accept-encoding" in compressed.headers["vary"].lower()
        assert compressed.text == content
        assert int(compressed.headers["content-length"]) < len(content.encode())

        plain = client.get("/app.js", headers={"Accept-Encoding": "identity"})
        assert plain.status_code == 200
        assert "content-encoding" not in plain.headers
        assert plain.text == content

        claim(client)
        private = client.get("/api/jobs", headers={"Accept-Encoding": "gzip"})
        assert private.status_code == 200
        assert len(private.content) > 500
        assert "content-encoding" not in private.headers


@pytest.mark.parametrize(
    "encoding,compressed,status",
    [
        ("gzip;q=0, identity;q=1", False, 200),
        ("GZIP;Q=0, *;q=1", False, 200),
        ("x-gzip", False, 200),
        ("br", False, 200),
        ("GZip;Q=1", True, 200),
        ("gzip;q=1, identity;q=0", True, 200),
        ("gzip;q=0.2, identity;q=0.8", False, 200),
        ("gzip;q=0.8, identity;q=0.2", True, 200),
        ("*;q=1", True, 200),
        ("*;q=0, identity;q=1", False, 200),
        ("gzip;q=NaN", False, 200),
        ("gzip;q=1.001", False, 200),
        ("gzip;q=0, gzip;q=1", False, 200),
        ("br, identity;q=0", False, 406),
        ("gzip;q=0, identity;q=0", False, 406),
        ("*;q=0", False, 406),
    ],
)
def test_static_encoding_quality_tokens_and_refusal(
    tmp_path: Path, api, encoding: str, compressed: bool, status: int
) -> None:
    web = tmp_path / "web"
    web.mkdir()
    content = "const syntheticValue = 1;\n" * 300
    (web / "app.js").write_text(content)
    app = create_app(
        tmp_path / "installation",
        origin="http://localhost:8080",
        static_dir=web,
        settings=api.settings,
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        response = client.get("/app.js", headers={"Accept-Encoding": encoding})
        assert response.status_code == status
        assert (response.headers.get("content-encoding") == "gzip") is compressed
        assert "accept-encoding" in response.headers["vary"].lower()
        if status == 200:
            assert response.text == content


def test_identity_refusal_does_not_leak_uncompressed_static_fallback(tmp_path: Path, api) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "small.js").write_text("const value=1;")
    (web / "large.js").write_text("const value=1;\n" * 300)
    app = create_app(
        tmp_path / "installation",
        origin="http://localhost:8080",
        static_dir=web,
        settings=api.settings,
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        headers = {"Accept-Encoding": "gzip, identity;q=0"}
        small = client.get("/small.js", headers=headers)
        assert small.status_code == 406
        assert small.content == b""
        ranged = client.get("/large.js", headers={**headers, "Range": "bytes=0-9"})
        assert ranged.status_code == 406
        assert ranged.content == b""
