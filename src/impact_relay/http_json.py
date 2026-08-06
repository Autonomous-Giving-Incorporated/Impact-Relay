"""Small, bounded HTTPS JSON client for operator-configured aggregate bridges."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_TIMEOUT_SECONDS = 10.0


class HTTPJSONError(ValueError):
    """A remote aggregate document could not be fetched safely."""


class HTTPResponse(Protocol):
    headers: Any

    def read(self, amount: int = -1) -> bytes: ...

    def __enter__(self) -> HTTPResponse: ...

    def __exit__(self, *args: object) -> None: ...


HTTPOpener = Callable[[Request, float], HTTPResponse]


def _stdlib_open(request: Request, timeout: float) -> HTTPResponse:
    return cast(HTTPResponse, urlopen(request, timeout=timeout))


def fetch_json_object(
    url: str,
    *,
    bearer_token: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    opener: HTTPOpener | None = None,
) -> dict[str, Any]:
    """Fetch one JSON object over HTTPS with strict size and content checks.

    The URL and credentials are operator-owned configuration. Errors intentionally
    omit the URL, response body, and transport details so secrets cannot leak.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPJSONError("aggregate endpoint must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise HTTPJSONError("aggregate endpoint must not contain userinfo")
    if parsed.fragment:
        raise HTTPJSONError("aggregate endpoint must not contain a fragment")
    if timeout_seconds <= 0:
        raise HTTPJSONError("timeout_seconds must be positive")
    if max_response_bytes <= 0:
        raise HTTPJSONError("max_response_bytes must be positive")

    headers = {"Accept": "application/json", "User-Agent": "impact-relay/0.9"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(url, headers=headers, method="GET")
    open_request = opener or _stdlib_open

    try:
        with open_request(request, timeout_seconds) as response:
            content_type = str(response.headers.get("Content-Type", ""))
            media_type = content_type.partition(";")[0].strip().lower()
            if media_type != "application/json" and not media_type.endswith("+json"):
                raise HTTPJSONError("aggregate endpoint did not return JSON content")
            body = response.read(max_response_bytes + 1)
    except HTTPJSONError:
        raise
    except HTTPError as exc:
        raise HTTPJSONError(f"aggregate endpoint returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise HTTPJSONError("aggregate endpoint request failed") from None

    if len(body) > max_response_bytes:
        raise HTTPJSONError("aggregate endpoint response exceeded the size limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPJSONError("aggregate endpoint returned invalid UTF-8 JSON") from None
    if not isinstance(payload, dict):
        raise HTTPJSONError("aggregate endpoint JSON root must be an object")
    return payload
