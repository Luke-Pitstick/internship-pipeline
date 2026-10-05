from pathlib import Path

import pytest

from internship_pipeline.config import ConfigurationError, load_profile, load_settings


def test_unknown_constraints_stay_unknown(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("name: Synthetic Candidate\nfacts: []\n")
    profile = load_profile(path)
    assert profile.constraints.requires_sponsorship is None
    assert profile.constraints.degree_level is None
    assert profile.constraints.locations == []


def test_invalid_secret_settings_do_not_echo_token(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("notification_urls: secret-token-not-a-list\n")
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "secret-token" not in str(error.value)


def test_duplicate_fact_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("facts:\n  - {id: x, text: first}\n  - {id: x, text: second}\n")
    with pytest.raises(ConfigurationError, match="unique"):
        load_profile(path)
