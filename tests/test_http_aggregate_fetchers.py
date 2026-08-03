from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from impact_relay.every_org import fetch_every_org_as_reconcile_aggregate
from impact_relay.http_json import HTTPJSONError, fetch_json_object
from impact_relay.notion_public import NotionPublicError, fetch_notion_public_evidence
from impact_relay.reconcile import ReconcileError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def fixture_body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fetch_json_object_sends_bearer_token_without_exposing_it() -> None:
    seen: dict[str, object] = {}

    def opener(request: Request, timeout: float) -> FakeResponse:
        seen["authorization"] = request.get_header("Authorization")
        seen["accept"] = request.get_header("Accept")
        seen["timeout"] = timeout
        return FakeResponse(b'{"ok": true}')

    assert fetch_json_object(
        "https://bridge.example/aggregate",
        bearer_token="top-secret",
        timeout_seconds=2.5,
        opener=opener,
    ) == {"ok": True}
    assert seen == {
        "authorization": "Bearer top-secret",
        "accept": "application/json",
        "timeout": 2.5,
    }


def test_fetch_every_org_aggregate_reuses_privacy_and_normalization_rules() -> None:
    aggregate = fetch_every_org_as_reconcile_aggregate(
        "https://bridge.example/every-org",
        opener=lambda request, timeout: FakeResponse(fixture_body("every_org_aggregate_v1.json")),
    )
    assert aggregate["raisedPublic"] == 12840.0
    assert aggregate["donorCountPublic"] == 37


def test_fetch_every_org_rejects_itemized_payload() -> None:
    body = json.dumps(
        {
            "processor": "every.org",
            "exportKind": "aggregate_summary",
            "gifts": [{"amount": 10}],
        }
    ).encode()
    with pytest.raises(ReconcileError, match="personal/itemized"):
        fetch_every_org_as_reconcile_aggregate(
            "https://bridge.example/every-org",
            opener=lambda request, timeout: FakeResponse(body),
        )


def test_fetch_notion_evidence_reuses_privacy_rules() -> None:
    evidence = fetch_notion_public_evidence(
        "https://bridge.example/notion-public",
        opener=lambda request, timeout: FakeResponse(
            fixture_body("notion_public_evidence_v1.json"), "application/problem+json"
        ),
    )
    assert evidence["privacy"]["piiAllowed"] is False
    assert evidence["campaignTargets"]["minimumTarget"] == 420000


def test_fetch_notion_rejects_permissive_privacy_flags() -> None:
    body = json.dumps(
        {
            "privacy": {
                "piiAllowed": True,
                "donorNamesAllowed": False,
                "individualAmountsAllowed": False,
            }
        }
    ).encode()
    with pytest.raises(NotionPublicError, match="piiAllowed"):
        fetch_notion_public_evidence(
            "https://bridge.example/notion-public",
            opener=lambda request, timeout: FakeResponse(body),
        )


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://bridge.example/data", "absolute HTTPS"),
        ("/relative", "absolute HTTPS"),
        ("https://user:pass@bridge.example/data", "userinfo"),
        ("https://bridge.example/data#secret", "fragment"),
    ],
)
def test_fetch_json_object_rejects_unsafe_urls(url: str, message: str) -> None:
    with pytest.raises(HTTPJSONError, match=message):
        fetch_json_object(url, opener=lambda request, timeout: FakeResponse(b"{}"))


def test_fetch_json_object_enforces_content_type_size_and_object_root() -> None:
    with pytest.raises(HTTPJSONError, match="JSON content"):
        fetch_json_object(
            "https://bridge.example/data",
            opener=lambda request, timeout: FakeResponse(b"{}", "text/html"),
        )
    with pytest.raises(HTTPJSONError, match="size limit"):
        fetch_json_object(
            "https://bridge.example/data",
            max_response_bytes=2,
            opener=lambda request, timeout: FakeResponse(b'{"long": true}'),
        )
    with pytest.raises(HTTPJSONError, match="root must be an object"):
        fetch_json_object(
            "https://bridge.example/data",
            opener=lambda request, timeout: FakeResponse(b"[]"),
        )


def test_fetch_json_object_sanitizes_transport_errors() -> None:
    secret = "token-value-that-must-not-leak"

    def failing_opener(request: Request, timeout: float) -> FakeResponse:
        raise URLError(f"upstream rejected {secret}: {request.full_url}")

    with pytest.raises(HTTPJSONError) as raised:
        fetch_json_object(
            "https://bridge.example/data?signature=query-secret",
            bearer_token=secret,
            opener=failing_opener,
        )
    message = str(raised.value)
    assert message == "aggregate endpoint request failed"
    assert secret not in message
    assert "query-secret" not in message
