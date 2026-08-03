"""Production SMTP adapter configuration, transport, and governed delivery tests."""

from __future__ import annotations

import copy
import json
import smtplib
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
    PostmarkConfig,
    PostmarkEmailAdapter,
    SMTPConfig,
    SMTPEmailAdapter,
    open_email_adapter,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


class FakeSMTPClient:
    def __init__(self, *, refused: dict[str, Any] | None = None, error: Exception | None = None):
        self.refused = refused or {}
        self.error = error
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.messages: list[Any] = []

    def __enter__(self) -> FakeSMTPClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self, *, context: Any) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: Any) -> dict[str, Any]:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return self.refused


class FakePostmarkResponse:
    def __init__(self, payload: Any) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakePostmarkResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def _config(**overrides: Any) -> SMTPConfig:
    values = {
        "host": "smtp.example.org",
        "port": 587,
        "from_address": "impact@example.org",
        "username": "mailer",
        "password": "correct-horse-battery-staple",
        "tls_mode": "starttls",
    }
    values.update(overrides)
    return SMTPConfig(**values)


def _postmark_config(**overrides: Any) -> PostmarkConfig:
    values = {
        "server_token": "postmark-server-secret",
        "from_address": "impact@example.org",
        "reply_to": "reply@example.org",
        "message_stream": "outbound",
    }
    values.update(overrides)
    return PostmarkConfig(**values)


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
        approval_id="smtp-approval",
        tenant_id=preview.tenant_id,
        proposal_id="smtp-proposal",
        command_idempotency_key=command.idempotency_key,
        decision="APPROVE",
        approver_id="comms.approver@example.org",
        approver_role="communications_approver",
        approved_at=utc_now_iso(),
    )
    return command, approval


def test_smtp_config_validates_and_hides_password() -> None:
    config = _config()
    assert "correct-horse" not in repr(config)
    with pytest.raises(NotificationConfigurationError, match="both be set"):
        _config(password="")
    with pytest.raises(NotificationConfigurationError, match="TLS mode"):
        _config(tls_mode="opportunistic")
    with pytest.raises(NotificationConfigurationError, match="from address"):
        _config(from_address="impact@example.org\nBcc: stolen@example.org")
    with pytest.raises(NotificationConfigurationError, match="from address"):
        _config(from_address="first@example.org,second@example.org")


def test_open_email_adapter_fails_closed_for_bad_smtp_config() -> None:
    with pytest.raises(NotificationConfigurationError, match="host is required"):
        open_email_adapter(
            env={
                "IMPACT_RELAY_EMAIL_BACKEND": "smtp",
                "IMPACT_RELAY_SMTP_FROM": "impact@example.org",
            }
        )
    with pytest.raises(NotificationConfigurationError, match="unknown"):
        open_email_adapter(backend="silent-fallback")


def test_postmark_config_and_factory_fail_closed_and_hide_token() -> None:
    config = _postmark_config()
    assert "postmark-server-secret" not in repr(config)
    with pytest.raises(NotificationConfigurationError, match="server token"):
        _postmark_config(server_token="")
    with pytest.raises(NotificationConfigurationError, match="from address"):
        _postmark_config(from_address="first@example.org,second@example.org")
    with pytest.raises(NotificationConfigurationError, match="absolute HTTPS"):
        _postmark_config(endpoint="http://api.postmarkapp.com/email")
    with pytest.raises(NotificationConfigurationError, match="query"):
        _postmark_config(endpoint="https://api.postmarkapp.com/email?token=secret")
    with pytest.raises(NotificationConfigurationError, match="server token"):
        open_email_adapter(
            env={
                "IMPACT_RELAY_EMAIL_BACKEND": "postmark",
                "IMPACT_RELAY_POSTMARK_FROM": "impact@example.org",
            }
        )
    adapter = open_email_adapter(
        env={
            "IMPACT_RELAY_EMAIL_BACKEND": "postmark",
            "IMPACT_RELAY_POSTMARK_SERVER_TOKEN": "postmark-server-secret",
            "IMPACT_RELAY_POSTMARK_FROM": "impact@example.org",
        },
        postmark_opener=lambda request, timeout: FakePostmarkResponse(
            {"ErrorCode": 0, "MessageID": "factory-message-id"}
        ),
    )
    assert isinstance(adapter, PostmarkEmailAdapter)


def test_postmark_send_builds_official_api_request_and_records_message_id() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Request, timeout: float) -> FakePostmarkResponse:
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["token"] = request.get_header("X-postmark-server-token")
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data or b"{}")
        return FakePostmarkResponse(
            {
                "ErrorCode": 0,
                "Message": "OK",
                "MessageID": "0a129aee-e1cd-480d-b08d-4f48548ff48d",
            }
        )

    adapter = PostmarkEmailAdapter(_postmark_config(), opener=opener)
    result = adapter.send_email(
        to_address="donor@example.net",
        subject="Approved impact update",
        body_text="Canonical receipt text",
        body_html="<p>Canonical receipt text</p>",
        metadata={"intent-id": "nint_1"},
    )
    assert result.success
    assert result.provider_receipt == "0a129aee-e1cd-480d-b08d-4f48548ff48d"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.postmarkapp.com/email"
    assert seen["token"] == "postmark-server-secret"
    assert seen["timeout"] == 10.0
    assert seen["payload"] == {
        "From": "impact@example.org",
        "To": "donor@example.net",
        "Subject": "Approved impact update",
        "TextBody": "Canonical receipt text",
        "HtmlBody": "<p>Canonical receipt text</p>",
        "ReplyTo": "reply@example.org",
        "MessageStream": "outbound",
        "Metadata": {"intent-id": "nint_1"},
    }


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(401, True), (422, True), (429, False), (503, False)],
)
def test_postmark_http_failures_are_classified_without_provider_body(
    status: int, permanent: bool
) -> None:
    def opener(request: Request, timeout: float) -> FakePostmarkResponse:
        raise HTTPError(
            request.full_url,
            status,
            "secret provider message",
            {},
            None,
        )

    result = PostmarkEmailAdapter(_postmark_config(), opener=opener).send_email(
        to_address="donor@example.net", subject="Subject", body_text="Body"
    )
    assert not result.success
    assert result.permanent_failure is permanent
    assert f"HTTP {status}" in result.detail
    assert "secret" not in result.detail
    assert "postmark-server-secret" not in result.detail


def test_postmark_api_rejection_and_transport_errors_are_sanitized() -> None:
    rejected = PostmarkEmailAdapter(
        _postmark_config(),
        opener=lambda request, timeout: FakePostmarkResponse(
            {
                "ErrorCode": 406,
                "Message": "inactive donor-secret@example.net",
                "MessageID": "",
            }
        ),
    ).send_email(to_address="donor@example.net", subject="Subject", body_text="Body")
    assert not rejected.success
    assert rejected.permanent_failure
    assert rejected.detail == "permanent: Postmark rejected message with error code 406"
    assert "donor-secret" not in rejected.detail

    def failing_opener(request: Request, timeout: float) -> FakePostmarkResponse:
        raise URLError("network path included postmark-server-secret")

    failed = PostmarkEmailAdapter(_postmark_config(), opener=failing_opener).send_email(
        to_address="donor@example.net", subject="Subject", body_text="Body"
    )
    assert failed.detail == "temporary Postmark transport failure"
    assert "secret" not in failed.detail


def test_postmark_production_adapter_does_not_bootstrap_consent() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    requests: list[Request] = []

    def opener(request: Request, timeout: float) -> FakePostmarkResponse:
        requests.append(request)
        return FakePostmarkResponse({"ErrorCode": 0, "MessageID": "postmark-id"})

    adapter = PostmarkEmailAdapter(
        _postmark_config(),
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


def test_smtp_send_uses_tls_auth_html_and_metadata() -> None:
    client = FakeSMTPClient()
    adapter = SMTPEmailAdapter(_config(), client_factory=lambda _config: client)
    result = adapter.send_email(
        to_address="donor@example.net",
        subject="Approved impact update",
        body_text="Canonical receipt text",
        body_html="<p>Canonical receipt text</p>",
        metadata={"intent-id": "nint_1"},
    )
    assert result.success
    assert client.started_tls
    assert client.login_args == ("mailer", "correct-horse-battery-staple")
    assert len(client.messages) == 1
    message = client.messages[0]
    assert message["From"] == "impact@example.org"
    assert message["To"] == "donor@example.net"
    assert message["Subject"] == "Approved impact update"
    assert message["X-Impact-intent-id"] == "nint_1"
    assert message.is_multipart()
    assert "Canonical receipt text" in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.parametrize(
    ("error", "permanent", "detail"),
    [
        (TimeoutError("secret transport detail"), False, "temporary"),
        (smtplib.SMTPAuthenticationError(535, b"secret auth detail"), True, "authentication"),
        (smtplib.SMTPDataError(550, b"secret provider detail"), True, "status 550"),
        (smtplib.SMTPDataError(451, b"secret provider detail"), False, "status 451"),
    ],
)
def test_smtp_failure_classification_redacts_provider_details(
    error: Exception, permanent: bool, detail: str
) -> None:
    client = FakeSMTPClient(error=error)
    adapter = SMTPEmailAdapter(_config(), client_factory=lambda _config: client)
    result = adapter.send_email(
        to_address="donor@example.net",
        subject="Subject",
        body_text="Body",
    )
    assert not result.success
    assert result.permanent_failure is permanent
    assert detail in result.detail
    assert "secret" not in result.detail
    assert "correct-horse" not in result.detail


def test_production_adapter_does_not_bootstrap_consent() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    client = FakeSMTPClient()
    resolver_calls: list[str] = []

    def resolve(intent: Any) -> str:
        resolver_calls.append(intent.donor_id)
        return "donor@example.net"

    adapter = SMTPEmailAdapter(
        _config(),
        address_resolver=resolve,
        client_factory=lambda _config: client,
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
    intent = next(iter(workspace.intents.values()))
    assert intent.status.value == "BLOCKED_NO_CONSENT"
    assert not workspace.consents
    assert not workspace.deliveries
    assert not client.messages
    assert not resolver_calls


def test_smtp_resolver_failure_is_sanitized() -> None:
    def fail_resolver(_intent: Any) -> str:
        raise RuntimeError("donor-alice-secret@example.net")

    adapter = SMTPEmailAdapter(_config(), address_resolver=fail_resolver)
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


def test_approved_preview_delivers_through_smtp_after_consent() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    client = FakeSMTPClient()
    adapter = SMTPEmailAdapter(
        _config(),
        address_resolver=lambda intent: f"{intent.donor_id}@example.net",
        client_factory=lambda _config: client,
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
    assert len(client.messages) == 1
    message = client.messages[0]
    assert message["Subject"] == preview.subject
    assert preview.body_text in message.get_body(preferencelist=("plain",)).get_content()
    delivery = next(iter(workspace.deliveries.values()))
    assert delivery.success
    assert delivery.provider == "smtp"
    assert delivery.provider_receipt == message["Message-ID"]

    # Command idempotency prevents a second provider call for the same approved send.
    second = executor.execute(
        command,
        approval=approval,
        agent_name="notification_composer",
    )
    assert second.status == "SKIPPED"
    assert len(client.messages) == 1
