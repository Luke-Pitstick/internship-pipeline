"""The downloadable helper completes local OAuth without writing credentials to disk."""

import io
from urllib.parse import urlencode

import pytest

from internship_pipeline.chatgpt import login_helper as helper


@pytest.mark.parametrize(
    "origin", ["https://pipeline.example.test", "http://127.0.0.1:8080", "http://localhost:8080/"]
)
def test_helper_accepts_https_and_loopback_origins(origin):
    assert helper.origin_url(origin) == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.test",
        "https://user:secret@remote.test",
        "https://remote.test/path",
        "https://remote.test?token=secret",
        "file:///tmp/private",
        "https://remote.test#fragment",
    ],
)
def test_helper_rejects_unsafe_origins(origin):
    with pytest.raises(helper.HelperError):
        helper.origin_url(origin)


@pytest.mark.parametrize(
    "query",
    [
        {"state": "wrong", "code": "code"},
        {"state": "correct", "code": ["one", "two"]},
        {"state": "correct", "code": "x" * 17_000},
    ],
)
def test_helper_rejects_wrong_state_duplicates_and_oversized_callbacks(query):
    assert (
        helper.callback_values("/auth/callback?" + urlencode(query, doseq=True), "correct") is None
    )
    assert helper.callback_values("/other?state=correct", "correct") is None


def test_helper_success_transfers_tokens_only_to_selected_origin(monkeypatch, capsys):
    origin = "https://pipeline.example.test"
    pairing = "synthetic-pairing-code-" + "x" * 32
    posts = []
    pending = dict(
        state="test-state",
        code_verifier="synthetic-verifier",
        client_id="dynamic_agent_client",
        redirect_uri="http://127.0.0.1:12345/auth/callback",
        authorize_url="https://auth.openai.com/api/accounts/authorize?state=test-state",
    )
    tokens = dict(
        access_token="synthetic-access", refresh_token="synthetic-refresh", id_token="synthetic-id"
    )

    def post(url, body, supplied_pairing=None):
        posts.append((url, body, supplied_pairing))
        if url == origin + "/api/chatgpt/pair":
            assert supplied_pairing == pairing and body == {"port": 12345}
            return pending
        if url == helper.TOKEN_URL:
            assert supplied_pairing is None
            assert body == {
                "grant_type": "authorization_code",
                "client_id": "oaiapp_test",
                "code": "synthetic-code",
                "code_verifier": "synthetic-verifier",
                "redirect_uri": pending["redirect_uri"],
                "resource": helper.RESOURCE,
            }
            return tokens
        assert url == origin + "/api/chatgpt/complete" and supplied_pairing == pairing
        assert body == {"state": "test-state", "client_id": "oaiapp_test", "tokens": tokens}
        return {"connected": True}

    class Server:
        server_port = 12345

        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 0)
            self.handler = handler

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def handle_request(self):
            request = object.__new__(self.handler)
            request.server = self
            request.path = (
                "/auth/callback?state=test-state&code=synthetic-code&client_id=oaiapp_test"
            )
            request.headers = {"Host": "127.0.0.1:12345"}
            request.wfile = io.BytesIO()
            request.send_response = lambda status: None
            request.send_header = lambda *args: None
            request.end_headers = lambda: None
            request.do_GET()
            assert b"synthetic-code" not in request.wfile.getvalue()

    monkeypatch.setattr(helper, "LocalServer", Server)
    monkeypatch.setattr(helper, "post", post)
    monkeypatch.setattr(helper.webbrowser, "open", lambda url: url == pending["authorize_url"])
    helper.connect(origin, pairing)
    assert len(posts) == 3
    output = capsys.readouterr().out
    assert "ChatGPT connected" in output
    assert all(secret not in output for secret in tokens.values())


def test_helper_never_opens_an_untrusted_authorization_origin(monkeypatch):
    class Server:
        server_port = 12345

        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(helper, "LocalServer", Server)
    monkeypatch.setattr(
        helper,
        "post",
        lambda *args: dict(
            state="s",
            authorize_url="https://attacker.test/sign-in",
            redirect_uri="http://127.0.0.1:12345/auth/callback",
        ),
    )
    monkeypatch.setattr(
        helper.webbrowser, "open", lambda _: pytest.fail("Untrusted browser navigation")
    )
    with pytest.raises(helper.HelperError, match="invalid sign-in"):
        helper.connect("https://pipeline.example.test", "synthetic-pairing-code")
