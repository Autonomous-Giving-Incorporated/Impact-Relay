"""Provider-neutral accounting expense source adapters.

The library does not own a nonprofit's accounting credentials or vendor SDK. This
module provides a small HTTPS JSON boundary that host apps can point at an
authorized accounting export/proxy, then feeds rows into the existing normalized
expense workflow contract.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from impact_relay.agents.expense_workflow import NormalizedExpenseImport, normalize_expense_row
from impact_relay.http_json import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    HTTPJSONError,
    HTTPOpener,
    fetch_json_object,
)


class AccountingSourceError(ValueError):
    """An accounting expense source could not be configured or read safely."""


class AccountingExpenseSource(Protocol):
    provider_name: str

    def fetch_expenses(self) -> list[NormalizedExpenseImport]:
        """Fetch normalized expense rows for one tenant."""
        ...


@dataclass(frozen=True)
class HTTPSJSONAccountingConfig:
    """Validated host-owned HTTPS JSON accounting source configuration."""

    endpoint: str
    tenant_id: str
    bearer_token: str = field(default="", repr=False)
    expenses_key: str = "expenses"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.endpoint.strip():
            raise AccountingSourceError("accounting endpoint is required")
        if not self.tenant_id.strip():
            raise AccountingSourceError("accounting tenant_id is required")
        if not self.expenses_key.strip():
            raise AccountingSourceError("accounting expenses_key is required")
        if any(ch in self.expenses_key for ch in ".[]\r\n"):
            raise AccountingSourceError("accounting expenses_key must be a single JSON object key")
        if self.timeout_seconds <= 0:
            raise AccountingSourceError("accounting timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise AccountingSourceError("accounting max_response_bytes must be positive")
        if self.bearer_token and any(ch in self.bearer_token for ch in "\r\n"):
            raise AccountingSourceError("accounting bearer token must be a single header value")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HTTPSJSONAccountingConfig:
        values = env if env is not None else os.environ
        try:
            timeout = float(values.get("IMPACT_RELAY_ACCOUNTING_TIMEOUT_SECONDS", "10"))
            max_bytes = int(
                values.get(
                    "IMPACT_RELAY_ACCOUNTING_MAX_RESPONSE_BYTES",
                    str(DEFAULT_MAX_RESPONSE_BYTES),
                )
            )
        except ValueError as exc:
            raise AccountingSourceError(
                "accounting timeout_seconds and max_response_bytes must be numeric"
            ) from exc
        return cls(
            endpoint=values.get("IMPACT_RELAY_ACCOUNTING_ENDPOINT", ""),
            tenant_id=values.get("IMPACT_RELAY_ACCOUNTING_TENANT_ID", ""),
            bearer_token=values.get("IMPACT_RELAY_ACCOUNTING_BEARER_TOKEN", ""),
            expenses_key=values.get("IMPACT_RELAY_ACCOUNTING_EXPENSES_KEY", "expenses"),
            timeout_seconds=timeout,
            max_response_bytes=max_bytes,
        )


class HTTPSJSONAccountingExpenseSource:
    """Fetch normalized expenses from a host-owned HTTPS JSON accounting endpoint."""

    provider_name = "https_json_accounting"

    def __init__(
        self,
        config: HTTPSJSONAccountingConfig,
        *,
        opener: HTTPOpener | None = None,
    ) -> None:
        self.config = config
        self._opener = opener

    def fetch_expenses(self) -> list[NormalizedExpenseImport]:
        try:
            payload = fetch_json_object(
                self.config.endpoint,
                bearer_token=self.config.bearer_token or None,
                timeout_seconds=self.config.timeout_seconds,
                max_response_bytes=self.config.max_response_bytes,
                opener=self._opener,
            )
        except HTTPJSONError as exc:
            detail = str(exc).replace("aggregate endpoint", "accounting endpoint")
            raise AccountingSourceError(detail) from None

        rows = payload.get(self.config.expenses_key)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise AccountingSourceError("accounting endpoint JSON must contain an expenses array")

        normalized: list[NormalizedExpenseImport] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise AccountingSourceError(f"accounting expense row {index} must be an object")
            try:
                normalized.append(normalize_expense_row(row, tenant_id=self.config.tenant_id))
            except (KeyError, TypeError, ValueError) as exc:
                missing = exc.args[0] if isinstance(exc, KeyError) and exc.args else "field"
                raise AccountingSourceError(
                    f"accounting expense row {index} is invalid: missing or invalid {missing}"
                ) from None
        return normalized


def open_accounting_expense_source(
    *,
    backend: str | None = None,
    env: Mapping[str, str] | None = None,
    opener: HTTPOpener | None = None,
) -> AccountingExpenseSource:
    """Open an explicit accounting expense source.

    No provider is selected implicitly. Host apps must choose ``https-json`` and
    supply endpoint credentials, or keep using fixture batch rows directly.
    """

    values = env if env is not None else os.environ
    kind = (backend or values.get("IMPACT_RELAY_ACCOUNTING_BACKEND") or "").lower().strip()
    if kind in {"https-json", "https_json"}:
        return HTTPSJSONAccountingExpenseSource(
            HTTPSJSONAccountingConfig.from_env(values), opener=opener
        )
    if not kind:
        raise AccountingSourceError(
            "accounting backend is required (use https-json or fixture batch rows)"
        )
    raise AccountingSourceError(
        f"unknown IMPACT_RELAY_ACCOUNTING_BACKEND={kind!r} (use https-json)"
    )
