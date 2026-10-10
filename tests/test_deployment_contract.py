"""Shipped operational examples and offline recovery contracts, without an engine."""

from pathlib import Path

import pytest

from internship_pipeline import cli
from internship_pipeline.config import load_settings
from internship_pipeline.identity import Identity
from internship_pipeline.operations import installation_lock

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative", ["deploy/settings.yaml", "config/settings.example.yaml"])
def test_every_shipped_operational_settings_example_uses_strict_current_schema(relative):
    assert load_settings(ROOT / relative)


def test_deployment_documents_require_offline_same_image_recovery():
    compose = (ROOT / "docs/deployment.md").read_text()
    render = (ROOT / "docs/render-deployment.md").read_text()
    assert "docker compose exec app internship-pipeline setup-token" not in compose
    assert "docker compose exec app internship-pipeline recover-owner" not in compose
    assert "docker compose stop app" in compose
    assert "--entrypoint internship-pipeline" in compose
    assert "docker compose start app" in compose
    assert "offline" in render.lower()
    assert "Browser profile/model editing is not available yet" not in render
    assert "Codex login" not in render
    assert "CODEX_HOME" not in (ROOT / "render.yaml").read_text()


def test_native_recovery_refuses_active_lock_then_rotates_stopped_token(tmp_path, capsys):
    account = Identity(tmp_path / "identity.sqlite3")
    original = account.setup_token()
    with account.connection() as db:
        original_hash = db.execute("SELECT token_hash FROM owner_setup").fetchone()[0]
    with installation_lock(tmp_path):
        for command in ["setup-token", "recover-owner"]:
            assert cli.main([command, "--data-dir", str(tmp_path)]) == 2
            assert "Stop the application" in capsys.readouterr().err
    with account.connection() as db:
        assert db.execute("SELECT token_hash FROM owner_setup").fetchone()[0] == original_hash
    assert cli.main(["setup-token", "--data-dir", str(tmp_path)]) == 0
    rotated = capsys.readouterr().out.strip().removeprefix("Owner setup token: ")
    assert rotated and rotated != original
    assert account.claim(rotated, "synthetic-owner", "synthetic-password-123")


def test_setup_link_works_with_running_service_and_cannot_reopen_owner(tmp_path, capsys):
    account = Identity(tmp_path / "identity.sqlite3")
    original = account.setup_token()
    args = ["setup-link", "--data-dir", str(tmp_path), "--origin", "http://localhost:8080"]
    with installation_lock(tmp_path):
        assert cli.main(args) == 0
    url = capsys.readouterr().out.strip()
    assert url.startswith("http://localhost:8080/#setup=")
    token = url.split("#setup=")[1]
    assert len(token) == 43 and token != original
    with pytest.raises(ValueError):
        account.claim(original, "synthetic-owner", "synthetic-password-123")
    account.claim(token, "synthetic-owner", "synthetic-password-123")
    assert cli.main(args) == 0
    assert capsys.readouterr().out.strip() == "http://localhost:8080/"
    with pytest.raises(ValueError):
        account.claim(token, "another-owner", "synthetic-password-123")


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://example.com/#secret",
        "https://u:p@example.com",
        "https://example.com/path",
    ],
)
def test_setup_link_rejects_unsafe_origins_without_rotating(tmp_path, capsys, origin):
    account = Identity(tmp_path / "identity.sqlite3")
    original = account.setup_token()
    assert cli.main(["setup-link", "--data-dir", str(tmp_path), "--origin", origin]) == 2
    assert "#setup=" not in capsys.readouterr().out
    account.claim(original, "synthetic-owner", "synthetic-password-123")
