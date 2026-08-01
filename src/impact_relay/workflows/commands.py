"""L3 command rebuild from frozen snapshots (PR-M3)."""

from __future__ import annotations

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.types import AgentCommand, ApprovalReceipt, AuthorityLevel
from impact_relay.workflows.types import FrozenProposedCommand


def build_executable_command(
    frozen: FrozenProposedCommand,
    approval: ApprovalReceipt,
) -> AgentCommand:
    """Rebuild exact command; overlay human identity from ApprovalReceipt (K16)."""
    if approval.command_idempotency_key != frozen.idempotency_key:
        raise AuthorityError("approval does not match frozen command_idempotency_key")
    if approval.tenant_id != frozen.tenant_id:
        raise AuthorityError("approval tenant_id mismatch")

    payload = dict(frozen.payload)
    if frozen.command_type == "approve_expense":
        payload["approved_by"] = approval.approver_id
    elif frozen.command_type == "publish_use_of_funds_receipt":
        payload["actor"] = approval.approver_id
        payload.setdefault("approved_by", approval.approver_id)
    elif frozen.command_type == "send_notification":
        payload["approved_by"] = approval.approver_id
    elif frozen.command_type in (
        "reverse_expense",
        "supersede_expense",
        "correct_published_amount",
    ):
        payload["actor"] = approval.approver_id
        payload.setdefault("approved_by", approval.approver_id)

    return AgentCommand(
        command_type=frozen.command_type,
        tenant_id=frozen.tenant_id,
        payload=payload,
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key=frozen.idempotency_key,
        expires_at=frozen.expires_at,
    )
