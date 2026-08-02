"""Notification composer — email preview from canonical receipts + L3 send gate.

Channel copy is a projection of the receipt. Amounts, vendors, dates, and
attribution methods cannot be invented or altered by the composer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from impact_relay.agents.authority import assert_agent_may_propose
from impact_relay.agents.base import AgentContext
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AuthorityLevel,
    ValidationResult,
    ValidationStatus,
    stable_hash,
    to_jsonable,
    utc_now_iso,
)
from impact_relay.domain.types import UseOfFundsReceipt


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _expires(hours: int = 48) -> str:
    return (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)).isoformat()


@dataclass(frozen=True)
class EmailPreview:
    """Donor-facing email draft derived only from a canonical receipt."""

    preview_id: str
    tenant_id: str
    receipt_id: str
    channel: str
    subject: str
    body_text: str
    template_version: str
    receipt_hash: str
    content_hash: str
    facts: dict[str, str]
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def compose_email_from_uof(
    receipt: UseOfFundsReceipt,
    *,
    template_version: str = "uof_email_v1",
) -> EmailPreview:
    """Project a use-of-funds receipt into an email preview.

    Facts are copied from the receipt; the template may only rearrange wording.
    """
    facts = {
        "organization_name": receipt.organization_name,
        "allocation_name": receipt.allocation_name,
        "vendor": receipt.vendor,
        "gross_amount": f"{receipt.gross_amount:.2f}",
        "attributed_amount": f"{receipt.attributed_amount:.2f}",
        "currency": receipt.currency,
        "purchase_date": receipt.purchase_date,
        "category": receipt.category,
        "description": receipt.description,
        "attribution_method": receipt.attribution_method,
        "verification_state": receipt.verification_state,
        "remaining_designated_balance": f"{receipt.remaining_designated_balance:.2f}",
        "receipt_hash": receipt.receipt_hash,
    }
    subject = f"How your gift to {receipt.organization_name} was used — {receipt.allocation_name}"
    body = (
        f"Hello,\n\n"
        f"{receipt.organization_name} approved an expenditure from "
        f"{receipt.allocation_name}.\n\n"
        f"What was purchased: {receipt.description}\n"
        f"Vendor: {receipt.vendor}\n"
        f"Category: {receipt.category}\n"
        f"Purchase date: {receipt.purchase_date}\n"
        f"Gross amount: {facts['gross_amount']} {receipt.currency}\n"
        f"Your attributed share: {facts['attributed_amount']} {receipt.currency}\n"
        f"Attribution method: {receipt.attribution_method}\n"
        f"Verification: {receipt.verification_state}\n"
        f"Remaining designated balance: {facts['remaining_designated_balance']} "
        f"{receipt.currency}\n"
    )
    if receipt.evidence_summary:
        body += f"\nEvidence: {receipt.evidence_summary}\n"
    body += (
        f"\nThis message is a projection of use-of-funds receipt "
        f"{receipt.receipt_id} (hash {receipt.receipt_hash[:12]}…).\n"
        f"Corrections, if any, will appear as separate receipts.\n"
    )
    content_hash = stable_hash(
        {
            "subject": subject,
            "body_text": body,
            "facts": facts,
            "template_version": template_version,
            "receipt_hash": receipt.receipt_hash,
        }
    )
    return EmailPreview(
        preview_id=_new_id("emprev"),
        tenant_id=receipt.organization_id,
        receipt_id=receipt.receipt_id,
        channel="EMAIL",
        subject=subject,
        body_text=body,
        template_version=template_version,
        receipt_hash=receipt.receipt_hash,
        content_hash=content_hash,
        facts=facts,
    )


def assert_preview_matches_receipt(preview: EmailPreview, receipt: UseOfFundsReceipt) -> None:
    """Fail closed if preview facts drift from the canonical receipt."""
    if preview.receipt_id != receipt.receipt_id:
        raise ValueError("preview receipt_id mismatch")
    if preview.receipt_hash != receipt.receipt_hash:
        raise ValueError("preview receipt_hash mismatch — regenerate preview")
    expected = {
        "organization_name": receipt.organization_name,
        "allocation_name": receipt.allocation_name,
        "vendor": receipt.vendor,
        "gross_amount": f"{receipt.gross_amount:.2f}",
        "attributed_amount": f"{receipt.attributed_amount:.2f}",
        "currency": receipt.currency,
        "purchase_date": receipt.purchase_date,
        "category": receipt.category,
        "description": receipt.description,
        "attribution_method": receipt.attribution_method,
        "verification_state": receipt.verification_state,
        "remaining_designated_balance": f"{receipt.remaining_designated_balance:.2f}",
        "receipt_hash": receipt.receipt_hash,
    }
    if preview.facts != expected:
        raise ValueError("preview facts do not match canonical receipt")


class NotificationComposerAgent:
    """L1 agent: drafts send proposal; never delivers."""

    name = "notification_composer"
    version = "0.5.0"
    authority_level = AuthorityLevel.L1_PROPOSE

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        if command.command_type != "compose_send_proposal":
            raise ValueError(f"unsupported command: {command.command_type}")
        preview = command.payload.get("preview") or {}
        send_cmd = AgentCommand(
            command_type="send_notification",
            tenant_id=context.tenant_id,
            payload={
                "preview_id": preview.get("preview_id"),
                "receipt_id": preview.get("receipt_id"),
                "content_hash": preview.get("content_hash"),
                "receipt_hash": preview.get("receipt_hash"),
                "channel": preview.get("channel", "EMAIL"),
                "template_version": preview.get("template_version", "uof_email_v1"),
            },
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            idempotency_key=(
                f"send:{preview.get('receipt_id')}:{preview.get('content_hash', '')[:16]}"
            ),
            expires_at=_expires(),
        )
        assert_agent_may_propose(self.authority_level, send_cmd)
        return AgentProposal(
            proposal_id=_new_id("prop"),
            tenant_id=context.tenant_id,
            agent_name=self.name,
            agent_version=self.version,
            policy_version=context.policy_version,
            prompt_version=context.prompt_version,
            input_refs=[preview.get("receipt_id", "receipt")],
            input_hash=stable_hash(preview),
            proposed_commands=[send_cmd],
            evidence_refs=[preview.get("receipt_hash", "")],
            confidence=1.0,
            warnings=[],
            contradictions=[],
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            expires_at=_expires(),
            idempotency_key=f"compose_send:{preview.get('receipt_id')}",
            notes="email preview ready; independent send approval required",
        )

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        if proposal.tenant_id != context.tenant_id:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reasons=["tenant_id mismatch"],
            )
        for cmd in proposal.proposed_commands:
            if cmd.command_type != "send_notification":
                return ValidationResult(
                    status=ValidationStatus.REJECTED,
                    reasons=[f"unexpected command {cmd.command_type}"],
                )
            if cmd.required_authority != AuthorityLevel.L3_HUMAN_APPROVAL:
                return ValidationResult(
                    status=ValidationStatus.REJECTED,
                    reasons=["send_notification must be L3"],
                )
        return ValidationResult(status=ValidationStatus.ACCEPTED)
