"""Resend email adapter configuration, transport, and governed delivery tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from impact_relay.agents.expense_workflow import LedgerCommandExecutor, run_expense_approval_slice
from impact_relay.agents.notification_composer import compose_email_from_uof
from impact_relay.agents.types import AgentCommand, ApprovalReceipt, AuthorityLevel, utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ConsentRecord,
    NotificationChannel,
    NotificationMessageClass,
    NotificationPreference,
)
from impact_relay.notifications import (
    NotificationConfigurationError,
    ResendConfig,
    ResendEmailAdapter,
    open_email_adapter,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


class FakeResendResponse:
    def __init__(self, payload: Any) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeResendResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def _resend_config(**overrides: Any) -> ResendConfig:
    values = {
        "api_key": "re_test_secret_key",
        "from_address": "Impact Relay <impact@example.org>",
        "reply_to": "reply@example.org",
    }
    values.update(overrides)
    return ResendConfig(**values)


def _ledger_with_receipt():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    rows = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
                "created_at": "2026-08-12T12:00:00+00:00",
            }
        ],
        send_email=False,
    )
    return ledger, result.receipts[0]


def _send_command(preview: Any) -> tuple[AgentCommand, ApprovalReceipt]:
    command = AgentCommand(
        command_type="send_notification",
        tenant_id=preview.tenant_id,
        payload={
            "preview_id": preview.preview_id,
            "receipt_id": preview.receipt_id,
            "content_hash": preview.content_hash,
            "receipt_hash": preview.receipt_hash,
            "channel": "EMAIL",
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
    )
    approval = ApprovalReceipt(
        approval_id="resend-approval",
        tenant_id=preview.tenant_id,
        proposal_id="resend-proposal",
        command_idempotency_key=command.idempotency_key,
        decision="APPROVE",
        approver_id="comms.approver@example.org",
        approver_role="communications_approver",
        approved_at=utc_now_iso(),
    )
    return command, approval


def test_resend_config_and_factory_fail_closed_and_hide_key() -> None:
    config = _resend_config()
    assert "re_test_secret_key" not in repr(config)
    with pytest.raises(NotificationConfigurationError, match="API key"):
        _resend_config(api_key="")
    with pytest.raises(NotificationConfigurationError, match="from address"):
        _resend_config(from_address="first@example.org,second@example.org")
    with pytest.raises(NotificationConfigurationError, match="from address"):
        _resend_config(from_address="Impact Relay <impact@example.org>\nBcc: stolen@example.org")
    with pytest.raises(NotificationConfigurationError, match="absolute HTTPS"):
        _resend_config(endpoint="http://api.resend.com/emails")
    with pytest.raises(NotificationConfigurationError, match="query"):
        _resend_config(endpoint="https://api.resend.com/emails?token=secret")
    with pytest.raises(NotificationConfigurationError, match="API key"):
        open_email_adapter(
            env={
                "IMPACT_RELAY_EMAIL_BACKEND": "resend",
                "IMPACT_RELAY_RESEND_FROM": "impact@example.org",
            }
        )
    adapter = open_email_adapter(
        env={
            "IMPACT_RELAY_EMAIL_BACKEND": "resend",
            "IMPACT_RELAY_RESEND_API_KEY": "re_test_secret_key",
            "IMPACT_RELAY_RESEND_FROM": "Impact Relay <impact@example.org>",
        },
        resend_opener=lambda request, timeout: FakeResendResponse({"id": "factory-message-id"}),
    )
    assert isinstance(adapter, ResendEmailAdapter)


def test_resend_send_builds_official_api_request_and_records_id() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Request, timeout: float) -> FakeResendResponse:
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["idempotency"] = request.get_header("Idempotency-key")
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data or b"{}")
        return FakeResendResponse({"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"})

    adapter = ResendEmailAdapter(_resend_config(), opener=opener)
    result = adapter.send_email(
        to_address="donor@example.net",
        subject="Approved impact update",
        body_text="Canonical receipt text",
        body_html="<p>Canonical receipt text</p>",
        metadata={"intent-id": "nint_1", "tenant-id": "org_1"},
    )
    assert result.success
    assert result.provider_receipt == "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["authorization"] == "Bearer re_test_secret_key"
    assert seen["idempotency"] == "nint_1"
    assert seen["timeout"] == 10.0
    assert seen["payload"] == {
        "from": "Impact Relay <impact@example.org>",
        "to": ["donor@example.net"],
        "subject": "Approved impact update",
        "text": "Canonical receipt text",
        "html": "<p>Canonical receipt text</p>",
        "reply_to": "reply@example.org",
        "headers": {
            "X-Impact-intent-id": "nint_1",
            "X-Impact-tenant-id": "org_1",
        },
        "tags": [
            {"name": "intent-id", "value": "nint_1"},
            {"name": "tenant-id", "value": "org_1"},
        ],
    }


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(401, True), (403, True), (422, True), (429, False), (503, False)],
)
def test_resend_http_failures_are_classified_without_provider_body(
    status: int, permanent: bool
) -> None:
    def opener(request: Request, timeout: float) -> FakeResendResponse:
        raise HTTPError(
            request.full_url,
            status,
            "secret provider message donor-secret@example.net",
            {},
            None,
        )

    result = ResendEmailAdapter(_resend_config(), opener=opener).send_email(
        to_address="donor@example.net", subject="Subject", body_text="Body"
    )
    assert not result.success
    assert result.permanent_failure is permanent
    assert f"HTTP {status}" in result.detail
    assert "secret" not in result.detail
    assert "re_test_secret_key" not in result.detail
    assert "donor-secret" not in result.detail


def test_resend_api_rejection_and_transport_errors_are_sanitized() -> None:
    rejected = ResendEmailAdapter(
        _resend_config(),
        opener=lambda request, timeout: FakeResendResponse(
            {
                "statusCode": 422,
                "name": "validation_error",
                "message": "inactive donor-secret@example.net",
            }
        ),
    ).send_email(to_address="donor@example.net", subject="Subject", body_text="Body")
    assert not rejected.success
    assert rejected.permanent_failure
    assert rejected.detail == "permanent: Resend rejected message with validation_error"
    assert "donor-secret" not in rejected.detail

    def failing_opener(request: Request, timeout: float) -> FakeResendResponse:
        raise URLError("network path included re_test_secret_key")

    failed = ResendEmailAdapter(_resend_config(), opener=failing_opener).send_email(
        to_address="donor@example.net", subject="Subject", body_text="Body"
    )
    assert failed.detail == "temporary Resend transport failure"
    assert "secret" not in failed.detail


def test_resend_production_adapter_does_not_bootstrap_consent() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    requests: list[Request] = []

    def opener(request: Request, timeout: float) -> FakeResendResponse:
        requests.append(request)
        return FakeResendResponse({"id": "resend-id"})

    adapter = ResendEmailAdapter(
        _resend_config(),
        address_resolver=lambda intent: "donor@example.net",
        opener=opener,
    )
    workspace.configure_notification_adapters({NotificationChannel.EMAIL: adapter})
    preview = compose_email_from_uof(receipt)
    executor = LedgerCommandExecutor(ledger, workspace=workspace)
    executor.register_preview(preview)
    command, approval = _send_command(preview)
    execution = executor.execute(
        command,
        approval=approval,
        agent_name="notification_composer",
    )
    assert execution.status == "FAILED"
    assert "BLOCKED_NO_CONSENT" in (execution.error or "")
    assert not workspace.consents
    assert not workspace.deliveries
    assert not requests


def test_approved_preview_delivers_through_resend_after_consent() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    requests: list[Request] = []

    def opener(request: Request, timeout: float) -> FakeResendResponse:
        requests.append(request)
        return FakeResendResponse({"id": "resend-live-id"})

    adapter = ResendEmailAdapter(
        _resend_config(),
        address_resolver=lambda intent: f"{intent.donor_id}@example.net",
        opener=opener,
    )
    workspace.configure_notification_adapters({NotificationChannel.EMAIL: adapter})
    workspace.notifications().record_consent(
        ConsentRecord(
            donor_id=receipt.donor_id,
            organization_id=receipt.organization_id,
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="host://consent/email",
            recorded_at=utc_now_iso(),
        )
    )
    workspace.notifications().set_preference(
        NotificationPreference(
            donor_id=receipt.donor_id,
            organization_id=receipt.organization_id,
            channel=NotificationChannel.EMAIL,
            enabled=True,
            topics=("MONEY_USED", "CORRECTION"),
        )
    )
    preview = compose_email_from_uof(receipt)
    executor = LedgerCommandExecutor(ledger, workspace=workspace)
    executor.register_preview(preview)
    command, approval = _send_command(preview)
    execution = executor.execute(
        command,
        approval=approval,
        agent_name="notification_composer",
    )
    assert execution.status == "SUCCEEDED"
    assert len(requests) == 1
    payload = json.loads(requests[0].data or b"{}")
    assert payload["subject"] == preview.subject
    assert preview.body_text == payload["text"]
    assert payload["to"] == [f"{receipt.donor_id}@example.net"]
    delivery = next(iter(workspace.deliveries.values()))
    assert delivery.success
    assert delivery.provider == "resend"
    assert delivery.provider_receipt == "resend-live-id"

    second = executor.execute(
        command,
        approval=approval,
        agent_name="notification_composer",
    )
    assert second.status == "SKIPPED"
    assert len(requests) == 1


def test_resend_resolver_failure_is_sanitized() -> None:
    def fail_resolver(_intent: Any) -> str:
        raise RuntimeError("donor-alice-secret@example.net")

    adapter = ResendEmailAdapter(_resend_config(), address_resolver=fail_resolver)
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    workspace.configure_notification_adapters({NotificationChannel.EMAIL: adapter})
    intent = workspace.notifications().evaluate_intent(
        donor_id=receipt.donor_id,
        channel=NotificationChannel.EMAIL,
        message_class=NotificationMessageClass.MONEY_USED,
        source_type="USE_OF_FUNDS",
        source_id=receipt.receipt_id,
        payload={},
        deliver=False,
    )
    success, _provider_receipt, detail = adapter.deliver(intent)
    assert not success
    assert detail == "permanent: donor email resolution failed"
    assert "secret" not in detail
