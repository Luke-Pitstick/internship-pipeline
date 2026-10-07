from pathlib import Path

import pytest

from internship_pipeline.config import ConfigurationError, load_settings


def test_invalid_secret_settings_do_not_echo_token(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("notification_urls: secret-token-not-a-list\n")
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "secret-token" not in str(error.value)


def test_personal_yaml_is_not_a_profile_authority(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("profile_path: private-profile.yaml\n")
    with pytest.raises(ConfigurationError, match="profile_path"):
        load_settings(path)


@pytest.mark.parametrize(
    "field", ["notification_urls", "recording_notifications_path", "dot_outbox_path"]
)
def test_obsolete_destinations_are_rejected(tmp_path: Path, field: str) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(f"{field}: null\n")
    with pytest.raises(ConfigurationError, match=field):
        load_settings(path)
