"""Channel adapter contracts — host apps plug real Postmark/APNs/FCM later.

Fixture adapters keep Hacker Dojo pilot offline and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from impact_relay.domain.types import NotificationIntent


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    provider_receipt: str
    detail: str = ""
    permanent_failure: bool = False

    def as_tuple(self) -> tuple[bool, str, str]:
        detail = self.detail
        if self.permanent_failure and "permanent" not in detail.lower():
            detail = f"permanent: {detail}" if detail else "permanent failure"
        return self.success, self.provider_receipt, detail


@runtime_checkable
class EmailAdapter(Protocol):
    provider_name: str

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult: ...

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        """NotificationService-compatible entrypoint."""
        ...


@runtime_checkable
class PushAdapter(Protocol):
    provider_name: str

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult: ...

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]: ...


class FixtureEmailAdapter:
    """In-process email — no network (pilot / tests)."""

    provider_name = "fixture_email"

    def __init__(self, *, fail: bool = False, permanent: bool = False) -> None:
        self.fail = fail
        self.permanent = permanent
        self.sent: list[dict[str, Any]] = []

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult:
        self.sent.append(
            {
                "to": to_address,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "metadata": metadata or {},
            }
        )
        if self.fail:
            return DeliveryResult(
                False,
                f"fail_{len(self.sent)}",
                "bounce" if self.permanent else "temporary error",
                permanent_failure=self.permanent,
            )
        return DeliveryResult(True, f"msg_{len(self.sent)}", "accepted")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        to = str(intent.payload.get("donor_email") or f"{intent.donor_id}@example.invalid")
        subject = f"[{intent.message_class.value}] Impact Relay update"
        body = str(intent.payload.get("description") or intent.source_id)
        return self.send_email(to_address=to, subject=subject, body_text=body).as_tuple()


class FixturePushAdapter:
    """In-process push stand-in for APNs/FCM."""

    provider_name = "fixture_push"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        self.sent.append({"token": device_token, "title": title, "body": body, "data": data or {}})
        if self.fail:
            return DeliveryResult(False, "push_fail", "device unreachable")
        return DeliveryResult(True, f"push_{len(self.sent)}", "queued")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        token = str(intent.payload.get("device_token") or "fixture-token")
        return self.send_push(
            device_token=token,
            title=intent.message_class.value,
            body=str(intent.source_id),
            data={"intent_id": intent.id},
        ).as_tuple()


class APNsPushAdapter:
    """Contract placeholder — host supplies credentials and HTTP/2 client.

    Not for production use until configured; raises if deliver is called.
    """

    provider_name = "apns"

    def __init__(self, *, team_id: str = "", key_id: str = "", bundle_id: str = "") -> None:
        self.team_id = team_id
        self.key_id = key_id
        self.bundle_id = bundle_id

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        raise NotImplementedError("Configure host APNs client; use FixturePushAdapter for pilot")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        raise NotImplementedError("APNs not configured")


class FCMPushAdapter:
    """Contract placeholder for Firebase Cloud Messaging."""

    provider_name = "fcm"

    def __init__(self, *, project_id: str = "") -> None:
        self.project_id = project_id

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        raise NotImplementedError("Configure host FCM client; use FixturePushAdapter for pilot")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        raise NotImplementedError("FCM not configured")
