"""Encrypted registrations, single-use authorizations and cross-process token renewal."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from internship_pipeline.chatgpt.protocol import (
    AUTHORIZE,
    MODEL_PATTERN,
    RESOURCE,
    SCOPES,
    TOKEN,
    ChatGPTError,
    ReauthorizationRequired,
    discovery,
    request_json,
    token_bundle,
    trusted_auth_url,
    validate_identity,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ChatGPTAccounts:
    def __init__(self, path: Path, cipher: Fernet, *, transport: httpx.BaseTransport | None = None):
        self.path, self.cipher, self.transport = path, cipher, transport
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chatgpt_host (
                    id INTEGER PRIMARY KEY, host_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chatgpt_accounts (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, subject TEXT NOT NULL,
                    email TEXT NOT NULL, encrypted BLOB, expires_at REAL NOT NULL,
                    status TEXT NOT NULL, welcomed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS chatgpt_authorizations (
                    id TEXT PRIMARY KEY, state_hash TEXT UNIQUE NOT NULL, pair_hash TEXT UNIQUE,
                    expires_at REAL NOT NULL, status TEXT NOT NULL, encrypted BLOB NOT NULL
                );
            """)
            db.execute(
                "INSERT OR IGNORE INTO chatgpt_host VALUES(1,?)", ("urn:uuid:" + str(uuid.uuid4()),)
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def encrypt(self, value: dict[str, Any]) -> bytes:
        return self.cipher.encrypt(json.dumps(value).encode())

    def decrypt(self, value: bytes) -> dict[str, Any]:
        try:
            return json.loads(self.cipher.decrypt(value))
        except (InvalidToken, TypeError, ValueError):
            raise ChatGPTError(
                "ChatGPT credentials are unavailable. Restore the instance key."
            ) from None

    def accounts(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,email,client_id,status,welcomed FROM chatgpt_accounts ORDER BY rowid"
                )
            ]

    def account(self, account_id: str) -> sqlite3.Row:
        with self.connection() as db:
            row = db.execute("SELECT * FROM chatgpt_accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise ChatGPTError("Select a saved ChatGPT account or connect one first.")
        return row

    def connected(self, account_id: str | None) -> bool:
        return bool(
            account_id
            and any(
                row["id"] == account_id and row["status"] == "connected" for row in self.accounts()
            )
        )

    def begin(
        self, expected_revision: int, redirect_uri: str | None, account_id: str | None = None
    ) -> dict[str, Any]:
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        pairing = secrets.token_urlsafe(32) if redirect_uri is None else None
        attempt = secrets.token_urlsafe(24)
        saved = self.account(account_id) if account_id else None
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_revision(db, expected_revision)
            db.execute(
                "DELETE FROM chatgpt_authorizations WHERE expires_at<?", (time.time() - 86400,)
            )
            active = db.execute(
                "SELECT COUNT(*) FROM chatgpt_authorizations WHERE expires_at>?",
                (time.time() - 300,),
            ).fetchone()[0]
            if active >= 10:
                raise ChatGPTError("Too many connection attempts. Wait a few minutes and retry.")
            host = db.execute("SELECT host_id FROM chatgpt_host WHERE id=1").fetchone()[0]
            hint = (
                self.decrypt(saved["encrypted"])["id_token"]
                if saved and saved["encrypted"]
                else None
            )
            pending = dict(
                state=state,
                nonce=nonce,
                verifier=verifier,
                redirect_uri=redirect_uri,
                expected_revision=expected_revision,
                account_id=account_id,
                client_id=saved["client_id"] if saved else "dynamic_agent_client",
                host_id=host,
                id_token_hint=hint,
            )
            db.execute(
                "INSERT INTO chatgpt_authorizations VALUES(?,?,?,?,?,?)",
                (
                    attempt,
                    digest(state),
                    digest(pairing) if pairing else None,
                    time.time() + 600,
                    "pending",
                    self.encrypt(pending),
                ),
            )
        return {
            "attempt_id": attempt,
            "pairing_code": pairing,
            "authorize_url": self.authorization_url(pending) if redirect_uri else None,
        }

    @staticmethod
    def check_revision(db: sqlite3.Connection, expected: int) -> None:
        row = db.execute(
            "SELECT revision FROM model_revisions WHERE kind='general' "
            "ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        if (row[0] if row else 0) != expected:
            raise ChatGPTError("The model connection changed. Reload settings and connect again.")

    @staticmethod
    def authorization_url(pending: dict[str, Any]) -> str:
        params = {
            "client_id": pending["client_id"],
            "ext_agent_host_id": pending["host_id"],
            "response_type": "code",
            "redirect_uri": pending["redirect_uri"],
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": pending["state"],
            "nonce": pending["nonce"],
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(pending["verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
        }
        if pending["client_id"] == "dynamic_agent_client":
            params["agent_name_hint"] = "Internship Pipeline"
        elif pending.get("id_token_hint"):
            params["id_token_hint"] = pending["id_token_hint"]
        return AUTHORIZE + "?" + urlencode(params)

    def claim_pairing(self, pairing: str, port: int) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM chatgpt_authorizations WHERE pair_hash=?", (digest(pairing),)
            ).fetchone()
            if not row or row["expires_at"] <= time.time() or row["status"] != "pending":
                raise ChatGPTError(
                    "Pairing code expired or was already used. Start again in settings."
                )
            pending = self.decrypt(row["encrypted"])
            pending["redirect_uri"] = f"http://127.0.0.1:{port}/auth/callback"
            db.execute(
                "UPDATE chatgpt_authorizations SET status='paired',encrypted=? WHERE id=?",
                (self.encrypt(pending), row["id"]),
            )
        return {
            "authorize_url": self.authorization_url(pending),
            "state": pending["state"],
            "code_verifier": pending["verifier"],
            "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client_id"],
        }

    def claim_callback(self, state: str, pairing: str | None = None) -> tuple[str, dict[str, Any]]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM chatgpt_authorizations WHERE state_hash=?", (digest(state),)
            ).fetchone()
            expected = "paired" if pairing else "pending"
            if (
                not row
                or row["expires_at"] <= time.time()
                or row["status"] != expected
                or row["pair_hash"] != (digest(pairing) if pairing else None)
            ):
                raise ChatGPTError(
                    "Connection expired or was already used. Start again in settings."
                )
            db.execute(
                "UPDATE chatgpt_authorizations SET status='verifying' WHERE id=?", (row["id"],)
            )
            return row["id"], self.decrypt(row["encrypted"])

    def complete(
        self,
        state: str,
        code: str | None,
        client_id: str | None,
        *,
        pairing: str | None = None,
        tokens: dict[str, Any] | None = None,
        denied: bool = False,
    ) -> str:
        attempt, pending = self.claim_callback(state, pairing)
        try:
            if denied:
                raise ChatGPTError(
                    "ChatGPT connection was cancelled. You can connect again in settings."
                )
            issued = client_id or pending["client_id"]
            if (
                not MODEL_PATTERN.fullmatch(issued)
                or issued == "dynamic_agent_client"
                or (
                    pending["client_id"] != "dynamic_agent_client"
                    and issued != pending["client_id"]
                )
            ):
                raise ChatGPTError("ChatGPT registration was incomplete. Start again in settings.")
            if tokens is None:
                if not code:
                    raise ChatGPTError("ChatGPT did not return an authorization code.")
                tokens = request_json(
                    "POST",
                    TOKEN,
                    transport=self.transport,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": issued,
                        "code": code,
                        "code_verifier": pending["verifier"],
                        "redirect_uri": pending["redirect_uri"],
                        "resource": RESOURCE,
                    },
                )
            bundle = token_bundle(tokens)
            claims = validate_identity(bundle, issued, pending["nonce"], transport=self.transport)
            account_id = digest(issued + "\0" + claims["sub"])
            if pending["account_id"] and pending["account_id"] != account_id:
                raise ChatGPTError("ChatGPT returned a different account. Connect it separately.")
            email = claims.get("email")
            label = (
                email if isinstance(email, str) and 1 <= len(email) <= 254 else "ChatGPT account"
            )
            with self.session_lock(account_id), self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self.check_revision(db, pending["expected_revision"])
                transaction = db.execute(
                    "SELECT status,expires_at FROM chatgpt_authorizations WHERE id=?", (attempt,)
                ).fetchone()
                if transaction[0] != "verifying" or transaction[1] <= time.time():
                    raise ChatGPTError("Connection was cancelled. Start again in settings.")
                db.execute(
                    """INSERT INTO chatgpt_accounts
                    (id,client_id,subject,email,encrypted,expires_at,status)
                    VALUES(?,?,?,?,?,?,'connected')
                    ON CONFLICT(id) DO UPDATE SET email=excluded.email,encrypted=excluded.encrypted,
                    expires_at=excluded.expires_at,status='connected'""",
                    (
                        account_id,
                        issued,
                        claims["sub"],
                        label,
                        self.encrypt(bundle),
                        time.time() + bundle["expires_in"],
                    ),
                )
                db.execute(
                    "UPDATE chatgpt_authorizations SET status='connected',encrypted=? WHERE id=?",
                    (self.encrypt({"account_id": account_id}), attempt),
                )
            return account_id
        except (ChatGPTError, ValueError, TypeError, KeyError):
            with self.connection() as db:
                db.execute(
                    "UPDATE chatgpt_authorizations SET status='failed',encrypted=? WHERE id=?",
                    (self.encrypt({}), attempt),
                )
            raise

    def attempt_status(self, attempt: str) -> str:
        with self.connection() as db:
            row = db.execute(
                "SELECT status,expires_at FROM chatgpt_authorizations WHERE id=?", (attempt,)
            ).fetchone()
        if not row:
            return "expired"
        return (
            "expired"
            if row["expires_at"] <= time.time()
            and row["status"] in {"pending", "paired", "verifying"}
            else row["status"]
        )

    def attempt_account(self, attempt: str) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT encrypted FROM chatgpt_authorizations WHERE id=? AND status='connected'",
                (attempt,),
            ).fetchone()
        return self.decrypt(row[0]).get("account_id") if row else None

    def cancel(self, attempt: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE chatgpt_authorizations SET status='cancelled',encrypted=? "
                "WHERE id=? AND status IN ('pending','paired','verifying')",
                (self.encrypt({}), attempt),
            )

    @contextmanager
    def session_lock(self, account_id: str) -> Iterator[None]:
        # Separate file locks avoid blocking unrelated SQLite writers during network I/O.
        path = self.path.parent / (".chatgpt-session-" + digest(account_id) + ".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ChatGPTError(
                            "ChatGPT credentials are busy. Try again shortly."
                        ) from None
                    time.sleep(0.05)
            yield
        finally:
            os.close(fd)

    def access_token(self, account_id: str) -> str:
        with self.session_lock(account_id):
            row = self.account(account_id)
            if row["status"] != "connected" or not row["encrypted"]:
                raise ChatGPTError("Reconnect this ChatGPT account in AI settings.")
            bundle = self.decrypt(row["encrypted"])
            if row["expires_at"] > time.time() + 60:
                return bundle["access_token"]
            try:
                refreshed = request_json(
                    "POST",
                    TOKEN,
                    transport=self.transport,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": row["client_id"],
                        "refresh_token": bundle["refresh_token"],
                        "resource": RESOURCE,
                    },
                )
            except ReauthorizationRequired:
                with self.connection() as db:
                    db.execute(
                        "UPDATE chatgpt_accounts SET status='reconnect_required' WHERE id=?",
                        (account_id,),
                    )
                raise
            updated = token_bundle(refreshed, previous=bundle)
            with self.connection() as db:
                db.execute(
                    "UPDATE chatgpt_accounts SET encrypted=?,expires_at=? WHERE id=?",
                    (
                        self.encrypt(updated),
                        time.time() + updated["expires_in"],
                        account_id,
                    ),
                )
            return updated["access_token"]

    def models(self, account_id: str) -> list[dict[str, str]]:
        token = self.access_token(account_id)
        body = request_json(
            "GET",
            RESOURCE + "/models",
            transport=self.transport,
            headers={"Authorization": "Bearer " + token},
        )
        try:
            models = []
            for model in body["models"]:
                slug, name = model["slug"], model["display_name"]
                if (
                    model.get("visibility") == "list"
                    and isinstance(slug, str)
                    and MODEL_PATTERN.fullmatch(slug)
                    and isinstance(name, str)
                    and 1 <= len(name) <= 150
                    and token not in name
                    and token not in slug
                ):
                    models.append({"slug": slug, "display_name": name})
            return models[:200]
        except (KeyError, TypeError, AttributeError):
            raise ChatGPTError("ChatGPT returned an unreadable model list. Try again.") from None

    def welcome(self, account_id: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE chatgpt_accounts SET welcomed=1 WHERE id=?", (account_id,))

    def disconnect(self, account_id: str) -> bool:
        with self.session_lock(account_id):
            row = self.account(account_id)
            confirmed = row["encrypted"] is None
            if row["encrypted"]:
                bundle = self.decrypt(row["encrypted"])
                try:
                    document = discovery(transport=self.transport)
                    url = trusted_auth_url(document["revocation_endpoint"])
                    with httpx.Client(
                        timeout=15,
                        follow_redirects=False,
                        trust_env=False,
                        transport=self.transport,
                    ) as client:
                        with client.stream(
                            "POST",
                            url,
                            data={
                                "token": bundle["refresh_token"],
                                "token_type_hint": "refresh_token",
                                "client_id": row["client_id"],
                            },
                        ) as response:
                            confirmed = response.status_code == 200
                except (ChatGPTError, httpx.HTTPError, KeyError):
                    confirmed = False
            with self.connection() as db:
                db.execute(
                    "UPDATE chatgpt_accounts SET encrypted=NULL,expires_at=0,"
                    "status='disconnected' WHERE id=?",
                    (account_id,),
                )
                # Invalidate pending reconnects so a late callback cannot undo disconnect.
                for pending in db.execute(
                    "SELECT id,encrypted FROM chatgpt_authorizations "
                    "WHERE status IN ('pending','paired','verifying')"
                ):
                    if self.decrypt(pending["encrypted"]).get("account_id") == account_id:
                        db.execute(
                            "UPDATE chatgpt_authorizations SET status='cancelled',encrypted=? "
                            "WHERE id=?",
                            (self.encrypt({}), pending["id"]),
                        )
            return confirmed
