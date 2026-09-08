"""Offline Mailosaur capture-client tests. Default pytest must not hit the network."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from impact_relay.notifications.mailosaur import (
    MailosaurClient,
    MailosaurError,
    inbox_address,
    is_mailosaur_configured,
    redact_captured_email,
)


class FakeMailosaurResponse:
    def __init__(self, payload: Any, *, status: int = 200) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeMailosaurResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def test_inbox_address_and_config_helpers() -> None:
    assert inbox_address("qpbqeifu", "ir-p8") == "ir-p8@qpbqeifu.mailosaur.net"
    with pytest.raises(MailosaurError, match="server_id"):
        inbox_address("", "ir-p8")
    assert is_mailosaur_configured(
        {"MAILOSAUR_API_KEY": "ms_test", "MAILOSAUR_SERVER_ID": "qpbqeifu"}
    )
    assert not is_mailosaur_configured({"MAILOSAUR_SERVER_ID": "qpbqeifu"})


def test_redact_captured_email_strips_tokens_and_action_urls() -> None:
    redacted = redact_captured_email(
        {
            "id": "msg_1",
            "subject": "How your gift was used",
            "html": (
                "<p>Open https://auth.example/verify?token_hash=abc123secret&type=magiclink</p>"
            ),
            "text": "token=super-secret-value leftover",
        }
    )
    assert redacted["id"] == "msg_1"
    assert "abc123secret" not in redacted["html"]
    assert "super-secret-value" not in redacted["text"]
    assert "[redacted-action-url]" in redacted["html"]
    assert "[redacted-token]" in redacted["text"]


def test_wait_for_message_uses_received_after_query_and_deletes() -> None:
    seen: list[dict[str, Any]] = []
    calls = {"n": 0}

    def opener(request: Request, timeout: float) -> FakeMailosaurResponse:
        calls["n"] += 1
        seen.append(
            {
                "method": request.method or "GET",
                "url": request.full_url,
                "auth": request.get_header("Authorization"),
                "body": request.data,
            }
        )
        search = "/messages/search?server=qpbqeifu&receivedAfter=2026-08-22T04:00:00Z"
        if request.full_url.endswith(search):
            return FakeMailosaurResponse({"items": [{"id": "msg_found"}]})
        if request.full_url.endswith("/messages/msg_found"):
            if (request.method or "GET") == "DELETE":
                return FakeMailosaurResponse(b"")
            return FakeMailosaurResponse(
                {
                    "id": "msg_found",
                    "subject": "How your gift to Hacker Dojo was used",
                    "html": {"body": "<p>Gross amount: 720.00 USD</p>"},
                    "text": {"body": "Gross amount: 720.00 USD"},
                }
            )
        raise AssertionError(request.full_url)

    client = MailosaurClient(
        api_key="ms_test_key",
        server_id="qpbqeifu",
        opener=opener,
        sleep=lambda _seconds: None,
    )
    message = client.wait_for_message(
        "ir-p8@qpbqeifu.mailosaur.net",
        received_after="2026-08-22T04:00:00Z",
        timeout_seconds=1,
        interval_seconds=0,
    )
    assert message["subject"].startswith("How your gift")
    assert "720.00" in message["text"]
    client.delete_message("msg_found")
    assert any(item["method"] == "DELETE" for item in seen)
    assert "ms_test_key" not in json.dumps(message)
    assert seen[0]["auth"].startswith("Basic ")
    assert "ms_test_key" not in seen[0]["auth"]


def test_mailosaur_http_errors_are_sanitized() -> None:
    def opener(request: Request, timeout: float) -> FakeMailosaurResponse:
        raise HTTPError(request.full_url, 401, "secret key leaked", {}, None)

    client = MailosaurClient(api_key="ms_test_key", server_id="qpbqeifu", opener=opener)
    with pytest.raises(MailosaurError, match="mailosaur_http_401") as exc_info:
        client.search_messages("ir-p8@qpbqeifu.mailosaur.net")
    assert "secret" not in str(exc_info.value)
    assert "ms_test_key" not in str(exc_info.value)
