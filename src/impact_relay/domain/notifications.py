"""Phase 3 — consent, preferences, policy engine, in-process delivery adapters."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from impact_relay.domain.types import (
    ConsentRecord,
    NotificationChannel,
    NotificationDelivery,
    NotificationIntent,
    NotificationIntentStatus,
    NotificationMessageClass,
    NotificationPreference,
    NotFoundError,
    StateError,
)

if TYPE_CHECKING:
    from impact_relay.domain.tenant import TenantWorkspace


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DeliveryAdapter(Protocol):
    """In-process delivery adapter — no live network I/O required."""

    provider_name: str

    def deliver(
        self, intent: NotificationIntent
    ) -> tuple[bool, str, str]:
        """Return (success, provider_receipt, detail)."""
        ...


class InProcessDeliveryAdapter:
    """Records delivery without calling external networks."""

    def __init__(self, provider_name: str = "in_process_fixture", *, fail: bool = False) -> None:
        self.provider_name = provider_name
        self.fail = fail
        self.attempts: list[str] = []

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        self.attempts.append(intent.id)
        if self.fail:
            return False, f"fail_{intent.id}", "simulated provider failure"
        return True, f"ok_{intent.id}", "delivered in-process"


class NotificationService:
    def __init__(
        self,
        workspace: TenantWorkspace,
        *,
        adapters: dict[NotificationChannel, DeliveryAdapter] | None = None,
    ) -> None:
        self.ws = workspace
        self.ledger = workspace.ledger
        self.adapters = adapters or {
            NotificationChannel.PUSH: InProcessDeliveryAdapter("push_fixture"),
            NotificationChannel.EMAIL: InProcessDeliveryAdapter("email_fixture"),
            NotificationChannel.SMS: InProcessDeliveryAdapter("sms_fixture"),
        }

    def record_consent(self, consent: ConsentRecord) -> ConsentRecord:
        if consent.organization_id != self.ledger.organization.id:
            raise StateError("consent organization_id mismatch")
        if consent.donor_id not in self.ledger.donors:
            raise NotFoundError(f"donor not found: {consent.donor_id}")
        key = (consent.donor_id, consent.channel.value)
        self.ws.consents[key] = consent
        return consent

    def set_preference(self, pref: NotificationPreference) -> NotificationPreference:
        if pref.organization_id != self.ledger.organization.id:
            raise StateError("preference organization_id mismatch")
        if pref.donor_id not in self.ledger.donors:
            raise NotFoundError(f"donor not found: {pref.donor_id}")
        key = (pref.donor_id, pref.channel.value)
        self.ws.preferences[key] = pref
        return pref

    def _has_consent(self, donor_id: str, channel: NotificationChannel) -> bool:
        c = self.ws.consents.get((donor_id, channel.value))
        return bool(c and c.granted)

    def _pref_allows(
        self,
        donor_id: str,
        channel: NotificationChannel,
        message_class: NotificationMessageClass,
    ) -> bool:
        pref = self.ws.preferences.get((donor_id, channel.value))
        if pref is None:
            # Default: email enabled for receipts if consent; others require pref.
            return channel == NotificationChannel.EMAIL
        if not pref.enabled:
            return False
        if pref.topics and message_class.value not in pref.topics:
            return False
        return True

    def evaluate_intent(
        self,
        *,
        donor_id: str,
        channel: NotificationChannel,
        message_class: NotificationMessageClass,
        source_type: str,
        source_id: str,
        payload: dict[str, Any],
        template_version: str = "v1.0",
        created_at: str | None = None,
        deliver: bool = True,
    ) -> NotificationIntent:
        """Create at most one intent per dedup key; deliver via in-process adapter when allowed."""
        if donor_id not in self.ledger.donors:
            raise NotFoundError(f"donor not found: {donor_id}")

        dedup_key = (
            f"{self.ledger.organization.id}|{donor_id}|{channel.value}|"
            f"{message_class.value}|{source_type}|{source_id}|{template_version}"
        )
        existing = self.ws.intents_by_dedup.get(dedup_key)
        if existing is not None:
            return existing

        created = created_at or _now_iso()
        intent_id = _new_id("nint")

        if not self._has_consent(donor_id, channel):
            intent = NotificationIntent(
                id=intent_id,
                organization_id=self.ledger.organization.id,
                donor_id=donor_id,
                channel=channel,
                message_class=message_class,
                source_type=source_type,
                source_id=source_id,
                dedup_key=dedup_key,
                policy_version=self.ledger.organization.policy_version,
                status=NotificationIntentStatus.BLOCKED_NO_CONSENT,
                template_version=template_version,
                payload=payload,
                created_at=created,
            )
            self.ws.intents[intent_id] = intent
            self.ws.intents_by_dedup[dedup_key] = intent
            return intent

        if not self._pref_allows(donor_id, channel, message_class):
            intent = NotificationIntent(
                id=intent_id,
                organization_id=self.ledger.organization.id,
                donor_id=donor_id,
                channel=channel,
                message_class=message_class,
                source_type=source_type,
                source_id=source_id,
                dedup_key=dedup_key,
                policy_version=self.ledger.organization.policy_version,
                status=NotificationIntentStatus.BLOCKED_PREFERENCE,
                template_version=template_version,
                payload=payload,
                created_at=created,
            )
            self.ws.intents[intent_id] = intent
            self.ws.intents_by_dedup[dedup_key] = intent
            return intent

        intent = NotificationIntent(
            id=intent_id,
            organization_id=self.ledger.organization.id,
            donor_id=donor_id,
            channel=channel,
            message_class=message_class,
            source_type=source_type,
            source_id=source_id,
            dedup_key=dedup_key,
            policy_version=self.ledger.organization.policy_version,
            status=NotificationIntentStatus.CREATED,
            template_version=template_version,
            payload=payload,
            created_at=created,
        )
        self.ws.intents[intent_id] = intent
        self.ws.intents_by_dedup[dedup_key] = intent

        if deliver:
            self._deliver(intent)
            intent = self.ws.intents[intent_id]
        return intent

    def _deliver(self, intent: NotificationIntent) -> NotificationDelivery:
        adapter = self.adapters.get(intent.channel)
        if adapter is None:
            from dataclasses import replace

            failed = replace(intent, status=NotificationIntentStatus.FAILED)
            self.ws.intents[intent.id] = failed
            self.ws.intents_by_dedup[intent.dedup_key] = failed
            delivery = NotificationDelivery(
                id=_new_id("ndel"),
                intent_id=intent.id,
                organization_id=intent.organization_id,
                donor_id=intent.donor_id,
                channel=intent.channel,
                success=False,
                provider="none",
                provider_receipt="",
                attempted_at=_now_iso(),
                detail="no adapter for channel",
            )
            self.ws.deliveries[delivery.id] = delivery
            return delivery

        success, provider_receipt, detail = adapter.deliver(intent)
        from dataclasses import replace

        status = (
            NotificationIntentStatus.DELIVERED
            if success
            else NotificationIntentStatus.FAILED
        )
        updated = replace(intent, status=status)
        self.ws.intents[intent.id] = updated
        self.ws.intents_by_dedup[intent.dedup_key] = updated

        delivery = NotificationDelivery(
            id=_new_id("ndel"),
            intent_id=intent.id,
            organization_id=intent.organization_id,
            donor_id=intent.donor_id,
            channel=intent.channel,
            success=success,
            provider=adapter.provider_name,
            provider_receipt=provider_receipt,
            attempted_at=_now_iso(),
            detail=detail,
        )
        self.ws.deliveries[delivery.id] = delivery
        return delivery

    def evaluate_for_use_of_funds(
        self,
        receipt_id: str,
        *,
        channel: NotificationChannel = NotificationChannel.EMAIL,
        deliver: bool = True,
    ) -> NotificationIntent:
        receipt = self.ledger.receipts.get(receipt_id)
        if receipt is None:
            raise NotFoundError(f"receipt not found: {receipt_id}")
        msg = (
            NotificationMessageClass.CORRECTION
            if receipt.corrected
            else NotificationMessageClass.MONEY_USED
        )
        return self.evaluate_intent(
            donor_id=receipt.donor_id,
            channel=channel,
            message_class=msg,
            source_type="USE_OF_FUNDS" if not receipt.corrected else "CORRECTION",
            source_id=receipt_id,
            payload=receipt.to_dict(),
            deliver=deliver,
        )

    def evaluate_for_impact(
        self,
        impact_receipt_id: str,
        *,
        channel: NotificationChannel = NotificationChannel.EMAIL,
        deliver: bool = True,
    ) -> NotificationIntent:
        ir = self.ws.impact_receipts.get(impact_receipt_id)
        if ir is None:
            raise NotFoundError(f"impact receipt not found: {impact_receipt_id}")
        return self.evaluate_intent(
            donor_id=ir.donor_id,
            channel=channel,
            message_class=NotificationMessageClass.IMPACT_OCCURRED,
            source_type="IMPACT",
            source_id=impact_receipt_id,
            payload=ir.to_dict(),
            deliver=deliver,
        )

    def intents_as_dicts(self) -> list[dict[str, Any]]:
        out = []
        for i in self.ws.intents.values():
            out.append(
                {
                    "id": i.id,
                    "donor_id": i.donor_id,
                    "channel": i.channel.value,
                    "message_class": i.message_class.value,
                    "source_type": i.source_type,
                    "source_id": i.source_id,
                    "dedup_key": i.dedup_key,
                    "status": i.status.value,
                    "policy_version": i.policy_version,
                    "template_version": i.template_version,
                    "created_at": i.created_at,
                }
            )
        return out

    def deliveries_as_dicts(self) -> list[dict[str, Any]]:
        out = []
        for d in self.ws.deliveries.values():
            out.append(
                {
                    "id": d.id,
                    "intent_id": d.intent_id,
                    "donor_id": d.donor_id,
                    "channel": d.channel.value,
                    "success": d.success,
                    "provider": d.provider,
                    "provider_receipt": d.provider_receipt,
                    "attempted_at": d.attempted_at,
                    "detail": d.detail,
                }
            )
        return out
