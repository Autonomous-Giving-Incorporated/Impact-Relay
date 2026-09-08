"""Stdlib Mailosaur capture client for optional live email probes.

This is not a production delivery backend. Default pytest stays offline; live
calls require ``MAILOSAUR_API_KEY`` and must never log tokens or donor PII.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MailosaurOpener = Callable[[Request, float], Any]
MailosaurSleeper = Callable[[float], None]

MAILOSAUR_API_BASE = "https://mailosaur.com/api"
DEFAULT_MAILOSAUR_SERVER_ID = "qpbqeifu"

_TOKEN_QUERY = re.compile(r"(?:token_hash|token|access_token)=[^&\s\"'<>]+", re.IGNORECASE)
_ACTION_URL = re.compile(
    r"https?://[^\s\"'<>]+(?:token_hash|token|type=magiclink|type=invite)[^\s\"'<>]*",
    re.IGNORECASE,
)


class MailosaurError(RuntimeError):
    """Sanitized Mailosaur client failure."""


def inbox_address(server_id: str, local_part: str) -> str:
    server = server_id.strip().lower()
    local = local_part.strip().lower()
    if not server:
        raise MailosaurError("server_id_required")
    if not local:
        raise MailosaurError("local_part_required")
    return f"{local}@{server}.mailosaur.net"


def is_mailosaur_configured(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    has_key = bool(values.get("MAILOSAUR_API_KEY", "").strip())
    has_server = bool(values.get("MAILOSAUR_SERVER_ID", "").strip())
    return has_key and has_server


def _basic_auth_header(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode()).decode("ascii")
    return f"Basic {token}"


def _message_text(payload: Any) -> str:
    if isinstance(payload, Mapping):
        return str(payload.get("body") or "")
    return "" if payload is None else str(payload)


def redact_captured_email(message: Mapping[str, Any]) -> dict[str, str]:
    def redact(value: str) -> str:
        return _TOKEN_QUERY.sub("[redacted-token]", _ACTION_URL.sub("[redacted-action-url]", value))

    html = (
        _message_text(message.get("html"))
        if isinstance(message.get("html"), Mapping)
        else str(message.get("html") or "")
    )
    text = (
        _message_text(message.get("text"))
        if isinstance(message.get("text"), Mapping)
        else str(message.get("text") or "")
    )
    return {
        "id": str(message.get("id") or ""),
        "subject": str(message.get("subject") or ""),
        "html": redact(html),
        "text": redact(text),
    }


class MailosaurClient:
    """Thin Mailosaur REST client with redacted errors and no SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        server_id: str,
        opener: MailosaurOpener | None = None,
        sleep: MailosaurSleeper | None = None,
        base_url: str = MAILOSAUR_API_BASE,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not api_key.strip():
            raise MailosaurError("api_key_required")
        if not server_id.strip():
            raise MailosaurError("server_id_required")
        self.api_key = api_key
        self.server_id = server_id.strip()
        self._opener = opener or (lambda request, timeout: urlopen(request, timeout=timeout))
        self._sleep = sleep or time.sleep
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, *, payload: Mapping[str, Any] | None = None) -> Any:
        data = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": _basic_auth_header(self.api_key),
                "User-Agent": "impact-relay/0.9",
            },
            method=method,
        )
        try:
            with self._opener(request, self.timeout_seconds) as response:
                raw = response.read(65_537)
        except HTTPError as exc:
            raise MailosaurError(f"mailosaur_http_{exc.code}") from None
        except (URLError, OSError, TimeoutError):
            raise MailosaurError("mailosaur_transport_failure") from None
        if not raw:
            return None
        if len(raw) > 65_536:
            raise MailosaurError("mailosaur_invalid_response")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MailosaurError("mailosaur_invalid_response") from None

    def search_messages(
        self, sent_to: str, *, received_after: str | None = None
    ) -> list[dict[str, Any]]:
        query = f"server={quote(self.server_id, safe='')}"
        if received_after:
            query += f"&receivedAfter={quote(received_after, safe=':')}"
        result = self._request(
            "POST",
            f"/messages/search?{query}",
            payload={"sentTo": sent_to},
        )
        items = result.get("items") if isinstance(result, dict) else None
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def get_message(self, message_id: str) -> dict[str, str]:
        payload = self._request("GET", f"/messages/{quote(message_id, safe='')}")
        if not isinstance(payload, dict):
            raise MailosaurError("mailosaur_invalid_response")
        return redact_captured_email(payload)

    def delete_message(self, message_id: str) -> None:
        self._request("DELETE", f"/messages/{quote(message_id, safe='')}")

    def wait_for_message(
        self,
        sent_to: str,
        *,
        received_after: str | None = None,
        timeout_seconds: float = 20.0,
        interval_seconds: float = 1.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            items = self.search_messages(sent_to, received_after=received_after)
            if items and items[0].get("id"):
                return self.get_message(str(items[0]["id"]))
            if time.monotonic() >= deadline:
                raise MailosaurError("mailosaur_timeout")
            self._sleep(interval_seconds)
