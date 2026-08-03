"""Provider-neutral accounting expense source adapter tests."""

from __future__ import annotations

import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from impact_relay.accounting import (
    AccountingSourceError,
    HTTPSJSONAccountingConfig,
    HTTPSJSONAccountingExpenseSource,
    open_accounting_expense_source,
)
from impact_relay.agents.expense_workflow import NormalizedExpenseImport


class FakeHTTPResponse:
    def __init__(self, payload: Any, *, headers: dict[str, str] | None = None) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def _config(**overrides: Any) -> HTTPSJSONAccountingConfig:
    values: dict[str, Any] = {
        "endpoint": "https://accounting.example.org/exports/expenses",
        "tenant_id": "org_hacker_dojo",
        "bearer_token": "accounting-secret-token",
    }
    values.update(overrides)
    return HTTPSJSONAccountingConfig(**values)


def _row(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "external_source_id": "bill_123",
        "vendor": "Community Hardware Shop",
        "amount": "42.50",
        "currency": "USD",
        "purchase_date": "2026-08-01",
        "category": "Hardware",
        "description": "Replacement keyboard",
        "allocation_id": "alloc_community_hardware",
        "evidence": [{"kind": "accounting_ref", "uri": "acct://bill_123"}],
    }
    values.update(overrides)
    return values


def test_accounting_config_validates_and_hides_bearer_token() -> None:
    config = _config()
    assert "accounting-secret-token" not in repr(config)
    with pytest.raises(AccountingSourceError, match="endpoint"):
        _config(endpoint="")
    with pytest.raises(AccountingSourceError, match="tenant_id"):
        _config(tenant_id="")
    with pytest.raises(AccountingSourceError, match="expenses_key"):
        _config(expenses_key="data.expenses")
    with pytest.raises(AccountingSourceError, match="timeout"):
        _config(timeout_seconds=0)
    with pytest.raises(AccountingSourceError, match="max_response"):
        _config(max_response_bytes=0)
    with pytest.raises(AccountingSourceError, match="bearer token"):
        _config(bearer_token="secret\nsecond-header")


def test_open_accounting_expense_source_fails_closed_and_uses_env() -> None:
    with pytest.raises(AccountingSourceError, match="backend is required"):
        open_accounting_expense_source(env={})
    with pytest.raises(AccountingSourceError, match="unknown"):
        open_accounting_expense_source(backend="quickbooks-live")
    with pytest.raises(AccountingSourceError, match="endpoint"):
        open_accounting_expense_source(env={"IMPACT_RELAY_ACCOUNTING_BACKEND": "https-json"})

    source = open_accounting_expense_source(
        env={
            "IMPACT_RELAY_ACCOUNTING_BACKEND": "https-json",
            "IMPACT_RELAY_ACCOUNTING_ENDPOINT": "https://accounting.example.org/expenses",
            "IMPACT_RELAY_ACCOUNTING_TENANT_ID": "org_hacker_dojo",
            "IMPACT_RELAY_ACCOUNTING_BEARER_TOKEN": "accounting-secret-token",
            "IMPACT_RELAY_ACCOUNTING_EXPENSES_KEY": "items",
        },
        opener=lambda _request, _timeout: FakeHTTPResponse({"items": []}),
    )
    assert isinstance(source, HTTPSJSONAccountingExpenseSource)
    assert source.fetch_expenses() == []


def test_https_json_accounting_source_builds_request_and_normalizes_rows() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Request, timeout: float) -> FakeHTTPResponse:
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["accept"] = request.get_header("Accept")
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        camel_case_row = {
            k: v for k, v in _row(externalSourceId="bill_124").items() if k != "external_source_id"
        }
        return FakeHTTPResponse({"expenses": [_row(), camel_case_row]})

    rows = HTTPSJSONAccountingExpenseSource(_config(), opener=opener).fetch_expenses()

    assert seen == {
        "method": "GET",
        "url": "https://accounting.example.org/exports/expenses",
        "accept": "application/json",
        "auth": "Bearer accounting-secret-token",
        "timeout": 10.0,
    }
    assert [type(row) for row in rows] == [NormalizedExpenseImport, NormalizedExpenseImport]
    assert rows[0].external_source_id == "bill_123"
    assert rows[0].tenant_id == "org_hacker_dojo"
    assert rows[0].proposed_allocation_id == "alloc_community_hardware"
    assert rows[0].evidence == [{"kind": "accounting_ref", "uri": "acct://bill_123"}]
    assert rows[0].idempotency_key
    assert rows[1].external_source_id == "bill_124"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expenses": "not-an-array"},
        {"expenses": ["not-an-object"]},
        {"expenses": [{k: v for k, v in _row().items() if k != "vendor"}]},
        {"expenses": [_row(external_source_id="", externalSourceId="")]},
    ],
)
def test_accounting_source_rejects_invalid_shapes(payload: dict[str, Any]) -> None:
    source = HTTPSJSONAccountingExpenseSource(
        _config(), opener=lambda _request, _timeout: FakeHTTPResponse(payload)
    )
    with pytest.raises(AccountingSourceError, match="accounting"):
        source.fetch_expenses()


@pytest.mark.parametrize(
    ("payload", "headers", "match"),
    [
        ({"expenses": []}, {"Content-Type": "text/html"}, "did not return JSON"),
        (b"not-json", {"Content-Type": "application/json"}, "invalid UTF-8 JSON"),
        ([{"expenses": []}], {"Content-Type": "application/json"}, "JSON root"),
    ],
)
def test_accounting_source_rejects_malformed_http_responses(
    payload: Any, headers: dict[str, str], match: str
) -> None:
    source = HTTPSJSONAccountingExpenseSource(
        _config(), opener=lambda _request, _timeout: FakeHTTPResponse(payload, headers=headers)
    )
    with pytest.raises(AccountingSourceError, match=match):
        source.fetch_expenses()


def test_accounting_source_transport_errors_are_sanitized() -> None:
    def http_error(request: Request, timeout: float) -> FakeHTTPResponse:
        headers = Message()
        raise HTTPError(
            request.full_url,
            401,
            "secret provider body included accounting-secret-token",
            headers,
            None,
        )

    with pytest.raises(AccountingSourceError) as http_exc:
        HTTPSJSONAccountingExpenseSource(_config(), opener=http_error).fetch_expenses()
    assert str(http_exc.value) == "accounting endpoint returned HTTP 401"
    assert "secret" not in str(http_exc.value)
    assert "accounting.example.org" not in str(http_exc.value)

    def transport_error(_request: Request, _timeout: float) -> FakeHTTPResponse:
        raise URLError("secret network path included accounting-secret-token")

    with pytest.raises(AccountingSourceError) as transport_exc:
        HTTPSJSONAccountingExpenseSource(_config(), opener=transport_error).fetch_expenses()
    assert str(transport_exc.value) == "accounting endpoint request failed"
    assert "secret" not in str(transport_exc.value)


def test_accounting_source_rejects_unsafe_endpoint_before_request() -> None:
    calls: list[Request] = []

    def opener(request: Request, _timeout: float) -> FakeHTTPResponse:
        calls.append(request)
        return FakeHTTPResponse({"expenses": []})

    source = HTTPSJSONAccountingExpenseSource(
        _config(endpoint="http://accounting.example.org/expenses"),
        opener=opener,
    )
    with pytest.raises(AccountingSourceError, match="absolute HTTPS"):
        source.fetch_expenses()
    assert not calls
