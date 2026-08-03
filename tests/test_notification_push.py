"""Production APNs/FCM push adapter configuration, transport, and governed delivery tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from impact_relay.agents.expense_workflow import run_expense_approval_slice
from impact_relay.agents.types import utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ConsentRecord,
    NotificationChannel,
    NotificationIntentStatus,
    NotificationMessageClass,
    NotificationPreference,
)
from impact_relay.notifications import (
    APNsPushAdapter,
    APNsPushConfig,
    FCMConfig,
    FCMPushAdapter,
    FixturePushAdapter,
    NotificationConfigurationError,
    open_push_adapter,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


class FakePushResponse:
    def __init__(self, payload: Any = b"", *, headers: dict[str, str] | None = None) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self) -> FakePushResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def _apns_config(**overrides: Any) -> APNsPushConfig:
    values = {
        "auth_token": "apns-auth-secret",
        "topic": "org.impactrelay.app",
        "bundle_id": "org.impactrelay.app",
    }
    values.update(overrides)
    return APNsPushConfig(**values)


def _fcm_config(**overrides: Any) -> FCMConfig:
    values = {
        "project_id": "impact-relay-prod",
        "server_token": "fcm-server-secret",
    }
    values.update(overrides)
    return FCMConfig(**values)


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


def _grant_push(workspace: TenantWorkspace, donor_id: str) -> None:
    workspace.notifications().record_consent(
        ConsentRecord(
            donor_id=donor_id,
            organization_id=workspace.organization.id,
            channel=NotificationChannel.PUSH,
            granted=True,
            provenance="host://consent/push",
            recorded_at=utc_now_iso(),
        )
    )
    workspace.notifications().set_preference(
        NotificationPreference(
            donor_id=donor_id,
            organization_id=workspace.organization.id,
            channel=NotificationChannel.PUSH,
            enabled=True,
            topics=("MONEY_USED", "CORRECTION"),
        )
    )


def test_apns_config_and_factory_fail_closed_and_hide_token() -> None:
    config = _apns_config()
    assert "apns-auth-secret" not in repr(config)
    with pytest.raises(NotificationConfigurationError, match="auth token"):
        _apns_config(auth_token="")
    with pytest.raises(NotificationConfigurationError, match="topic"):
        _apns_config(topic="")
    with pytest.raises(NotificationConfigurationError, match="bundle_id"):
        _apns_config(bundle_id="")
    with pytest.raises(NotificationConfigurationError, match="absolute HTTPS"):
        _apns_config(endpoint="http://api.push.apple.com")
    with pytest.raises(NotificationConfigurationError, match="query"):
        _apns_config(endpoint="https://api.push.apple.com?token=secret")

    adapter = open_push_adapter(
        backend="apns",
        env={
            "IMPACT_RELAY_APNS_AUTH_TOKEN": "apns-auth-secret",
            "IMPACT_RELAY_APNS_BUNDLE_ID": "org.impactrelay.app",
        },
        apns_opener=lambda _request, _timeout: FakePushResponse(
            b"", headers={"apns-id": "factory-apns-id"}
        ),
    )
    assert isinstance(adapter, APNsPushAdapter)
    assert isinstance(open_push_adapter(backend="fixture"), FixturePushAdapter)
    with pytest.raises(NotificationConfigurationError, match="unknown"):
        open_push_adapter(backend="silent-fallback")


def test_fcm_config_and_factory_fail_closed_and_hide_token() -> None:
    config = _fcm_config()
    assert "fcm-server-secret" not in repr(config)
    with pytest.raises(NotificationConfigurationError, match="project id"):
        _fcm_config(project_id="")
    with pytest.raises(NotificationConfigurationError, match="server token"):
        _fcm_config(server_token="")
    with pytest.raises(NotificationConfigurationError, match="absolute HTTPS"):
        _fcm_config(endpoint="http://fcm.googleapis.com/v1")
    with pytest.raises(NotificationConfigurationError, match="query"):
        _fcm_config(endpoint="https://fcm.googleapis.com/v1?token=secret")

    adapter = open_push_adapter(
        backend="fcm",
        env={
            "IMPACT_RELAY_FCM_PROJECT_ID": "impact-relay-prod",
            "IMPACT_RELAY_FCM_SERVER_TOKEN": "fcm-server-secret",
        },
        fcm_opener=lambda _request, _timeout: FakePushResponse(
            {"name": "projects/impact-relay-prod/messages/factory-id"}
        ),
    )
    assert isinstance(adapter, FCMPushAdapter)


def test_apns_send_builds_official_request_and_records_apns_id() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Request, timeout: float) -> FakePushResponse:
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["content_type"] = request.get_header("Content-type")
        seen["topic"] = request.get_header("Apns-topic")
        seen["push_type"] = request.get_header("Apns-push-type")
        seen["priority"] = request.get_header("Apns-priority")
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data or b"{}")
        return FakePushResponse(b"", headers={"apns-id": "8c1d7c42"})

    result = APNsPushAdapter(_apns_config(), opener=opener).send_push(
        device_token="device-token-1",
        title="Approved impact update",
        body="Canonical receipt text",
        data={"intent-id": "nint_1", "bad\nkey": "dropped", "count": 3},
    )

    assert result.success
    assert result.provider_receipt == "8c1d7c42"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.push.apple.com/3/device/device-token-1"
    assert seen["auth"] == "Bearer apns-auth-secret"
    assert seen["content_type"] == "application/json"
    assert seen["topic"] == "org.impactrelay.app"
    assert seen["push_type"] == "alert"
    assert seen["priority"] == "10"
    assert seen["timeout"] == 10.0
    assert seen["payload"] == {
        "aps": {
            "alert": {
                "title": "Approved impact update",
                "body": "Canonical receipt text",
            },
            "sound": "default",
        },
        "intent-id": "nint_1",
        "count": "3",
    }


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(400, True), (410, True), (429, False), (503, False)],
)
def test_apns_http_failures_are_classified_without_provider_body(
    status: int, permanent: bool
) -> None:
    def opener(request: Request, timeout: float) -> FakePushResponse:
        raise HTTPError(request.full_url, status, "secret provider message", {}, None)

    result = APNsPushAdapter(_apns_config(), opener=opener).send_push(
        device_token="device-token-1",
        title="Subject",
        body="Body",
    )
    assert not result.success
    assert result.permanent_failure is permanent
    assert f"HTTP {status}" in result.detail
    assert "secret" not in result.detail
    assert "apns-auth-secret" not in result.detail


def test_apns_transport_and_malformed_responses_are_sanitized() -> None:
    def failing_opener(request: Request, timeout: float) -> FakePushResponse:
        raise URLError("network path included apns-auth-secret")

    failed = APNsPushAdapter(_apns_config(), opener=failing_opener).send_push(
        device_token="device-token-1",
        title="Subject",
        body="Body",
    )
    assert failed.detail == "temporary APNs transport failure"
    assert "secret" not in failed.detail

    malformed = APNsPushAdapter(
        _apns_config(),
        opener=lambda _request, _timeout: FakePushResponse(
            b"not-json", headers={"Content-Type": "application/json"}
        ),
    ).send_push(device_token="device-token-1", title="Subject", body="Body")
    assert not malformed.success
    assert malformed.detail == "temporary invalid APNs response"


def test_fcm_send_builds_official_request_and_records_message_name() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Request, timeout: float) -> FakePushResponse:
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["content_type"] = request.get_header("Content-type")
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data or b"{}")
        return FakePushResponse({"name": "projects/impact-relay-prod/messages/abc123"})

    result = FCMPushAdapter(_fcm_config(), opener=opener).send_push(
        device_token="fcm-device-token-1",
        title="Approved impact update",
        body="Canonical receipt text",
        data={"intent-id": "nint_1", "bad\nkey": "dropped", "count": 3},
    )

    assert result.success
    assert result.provider_receipt == "projects/impact-relay-prod/messages/abc123"
    assert seen["method"] == "POST"
    assert seen["url"] == ("https://fcm.googleapis.com/v1/projects/impact-relay-prod/messages:send")
    assert seen["auth"] == "Bearer fcm-server-secret"
    assert seen["content_type"] == "application/json"
    assert seen["timeout"] == 10.0
    assert seen["payload"] == {
        "message": {
            "token": "fcm-device-token-1",
            "notification": {
                "title": "Approved impact update",
                "body": "Canonical receipt text",
            },
            "data": {"intent-id": "nint_1", "count": "3"},
        }
    }


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(400, True), (404, True), (429, False), (503, False)],
)
def test_fcm_http_failures_are_classified_without_provider_body(
    status: int, permanent: bool
) -> None:
    def opener(request: Request, timeout: float) -> FakePushResponse:
        raise HTTPError(request.full_url, status, "secret provider message", {}, None)

    result = FCMPushAdapter(_fcm_config(), opener=opener).send_push(
        device_token="fcm-device-token-1",
        title="Subject",
        body="Body",
    )
    assert not result.success
    assert result.permanent_failure is permanent
    assert f"HTTP {status}" in result.detail
    assert "secret" not in result.detail
    assert "fcm-server-secret" not in result.detail


def test_fcm_transport_and_malformed_responses_are_sanitized() -> None:
    def failing_opener(request: Request, timeout: float) -> FakePushResponse:
        raise URLError("network path included fcm-server-secret")

    failed = FCMPushAdapter(_fcm_config(), opener=failing_opener).send_push(
        device_token="fcm-device-token-1",
        title="Subject",
        body="Body",
    )
    assert failed.detail == "temporary FCM transport failure"
    assert "secret" not in failed.detail

    malformed = FCMPushAdapter(
        _fcm_config(),
        opener=lambda _request, _timeout: FakePushResponse({"unexpected": "shape"}),
    ).send_push(device_token="fcm-device-token-1", title="Subject", body="Body")
    assert not malformed.success
    assert malformed.detail == "temporary invalid FCM response"


def test_push_production_adapter_does_not_bootstrap_consent_or_resolve_token() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    requests: list[Request] = []
    resolver_calls: list[str] = []

    def resolve(intent: Any) -> str:
        resolver_calls.append(intent.donor_id)
        return "device-token-1"

    adapter = APNsPushAdapter(
        _apns_config(),
        token_resolver=resolve,
        opener=lambda request, _timeout: (
            requests.append(request) or FakePushResponse(b"", headers={"apns-id": "apns-id"})
        ),
    )
    workspace.configure_notification_adapters({NotificationChannel.PUSH: adapter})

    intent = workspace.notifications().evaluate_for_use_of_funds(
        receipt.receipt_id,
        channel=NotificationChannel.PUSH,
        deliver=True,
    )

    assert intent.status == NotificationIntentStatus.BLOCKED_NO_CONSENT
    assert not workspace.deliveries
    assert not requests
    assert not resolver_calls


def test_push_resolver_failure_is_sanitized() -> None:
    def fail_resolver(_intent: Any) -> str:
        raise RuntimeError("donor-alice-secret-device-token")

    adapter = FCMPushAdapter(_fcm_config(), token_resolver=fail_resolver)
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    workspace.configure_notification_adapters({NotificationChannel.PUSH: adapter})
    _grant_push(workspace, receipt.donor_id)

    intent = workspace.notifications().evaluate_intent(
        donor_id=receipt.donor_id,
        channel=NotificationChannel.PUSH,
        message_class=NotificationMessageClass.MONEY_USED,
        source_type="USE_OF_FUNDS",
        source_id=receipt.receipt_id,
        payload={},
        deliver=False,
    )
    success, _provider_receipt, detail = adapter.deliver(intent)
    assert not success
    assert detail == "permanent: device token resolution failed"
    assert "secret" not in detail


def test_push_delivers_after_consent_and_records_provider_receipt() -> None:
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    requests: list[Request] = []
    adapter = FCMPushAdapter(
        _fcm_config(),
        token_resolver=lambda intent: f"{intent.donor_id}-device-token",
        opener=lambda request, _timeout: (
            requests.append(request)
            or FakePushResponse({"name": "projects/impact-relay-prod/messages/delivered"})
        ),
    )
    workspace.configure_notification_adapters({NotificationChannel.PUSH: adapter})
    _grant_push(workspace, receipt.donor_id)

    intent = workspace.notifications().evaluate_for_use_of_funds(
        receipt.receipt_id,
        channel=NotificationChannel.PUSH,
        deliver=True,
        payload_patch={"push_title": "Your impact update", "push_body": "Receipt is ready"},
    )

    assert intent.status == NotificationIntentStatus.DELIVERED
    assert len(requests) == 1
    delivery = next(iter(workspace.deliveries.values()))
    assert delivery.success
    assert delivery.provider == "fcm"
    assert delivery.provider_receipt == "projects/impact-relay-prod/messages/delivered"
