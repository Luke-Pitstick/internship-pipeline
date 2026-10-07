"""Actual SMTP Apprise adapter contract without contacting a destination."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from internship_pipeline.email_integrations import apprise_email

CONFIG = {
    "host": "smtp.example.test",
    "port": 587,
    "username": "synthetic-user",
    "security": "starttls",
    "sender": "sender@example.test",
    "recipient": "to@example.test",
}


def mock_client(monkeypatch, accepted=True, attachment_support=True):
    import apprise

    client = MagicMock()
    client.add.return_value = True
    client.notify.return_value = accepted
    client.__iter__.return_value = iter([SimpleNamespace(attachment_support=attachment_support)])
    monkeypatch.setattr(apprise, "Apprise", lambda: client)
    return client


def test_smtp_configuration_and_optional_pdf_delegate_to_apprise(monkeypatch):
    import apprise

    client = mock_client(monkeypatch)
    content = b"%PDF-1.4 synthetic fixture"
    attached = []

    def inspect(**kwargs):
        attached.extend(kwargs["attach"])
        assert Path(attached[0]).read_bytes() == content
        assert Path(attached[0]).stat().st_mode & 0o077 == 0
        assert kwargs["body_format"] == apprise.NotifyFormat.TEXT
        assert kwargs["title"] == "Synthetic alert" and kwargs["body"] == "Synthetic body"
        return True

    client.notify.side_effect = inspect
    assert (
        apprise_email(CONFIG, "secret?&+#", "Synthetic alert", "Synthetic body", [content])
        == "accepted"
    )
    url = urlsplit(client.add.call_args.args[0])
    assert url.scheme == "mailtos"
    query = parse_qs(url.query)
    assert query["pass"] == ["secret?&+#"] and query["smtp"] == [CONFIG["host"]]
    assert query["mode"] == ["starttls"] and query["timeout"] == ["20"]
    assert all(not Path(path).exists() for path in attached)


@pytest.mark.parametrize("accepted", [False, None])
def test_ambiguous_acceptance_requires_owner_review(monkeypatch, accepted):
    mock_client(monkeypatch, accepted)
    assert apprise_email(CONFIG, "secret", "Synthetic", "Body", []) == "uncertain"


def test_timeout_is_uncertain_without_leaking_exception(monkeypatch):
    client = mock_client(monkeypatch)
    client.notify.side_effect = TimeoutError("synthetic destination secret")
    assert apprise_email(CONFIG, "secret", "Synthetic", "Body", []) == "uncertain"


def test_invalid_registration_never_attempts_send(monkeypatch):
    client = mock_client(monkeypatch)
    client.add.return_value = False
    assert apprise_email(CONFIG, "secret", "Synthetic", "Body", []) == "rejected"
    client.notify.assert_not_called()


def test_unsupported_optional_attachment_still_delivers_alert(monkeypatch):
    client = mock_client(monkeypatch, attachment_support=False)
    assert apprise_email(CONFIG, "secret", "Synthetic", "Body", [b"synthetic"]) == "accepted"
    assert client.notify.call_args.kwargs["attach"] is None
