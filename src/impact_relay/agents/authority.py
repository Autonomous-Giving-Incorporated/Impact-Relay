"""Deterministic L0–L3 authority enforcement."""

from __future__ import annotations

from impact_relay.agents.types import (
    AUTHORITY_RANK,
    L3_COMMAND_TYPES,
    AgentCommand,
    AgentProposal,
    ApprovalReceipt,
    AuthorityLevel,
)


class AuthorityError(PermissionError):
    """Agent or executor attempted an unauthorized action."""


def rank(level: AuthorityLevel) -> int:
    return AUTHORITY_RANK[level]


def requires_human_approval(command: AgentCommand) -> bool:
    return (
        command.command_type in L3_COMMAND_TYPES
        or command.required_authority == AuthorityLevel.L3_HUMAN_APPROVAL
    )


def assert_agent_may_propose(
    agent_ceiling: AuthorityLevel,
    command: AgentCommand,
) -> None:
    """Agents may only emit commands at or below their ceiling.

    L1 agents may propose L3 commands (as recommendations), but those commands
    still require a separate human ApprovalReceipt before execution.
    """
    # Proposing an L3 command is allowed at L1+ (recommendation). L0 is observe-only.
    if agent_ceiling == AuthorityLevel.L0_OBSERVE:
        raise AuthorityError("L0 observe agents cannot propose commands")
    if command.command_type in L3_COMMAND_TYPES:
        return  # proposal of consequential commands is allowed; execution is gated
    if rank(command.required_authority) > rank(agent_ceiling):
        raise AuthorityError(
            f"agent ceiling {agent_ceiling.value} cannot propose "
            f"{command.required_authority.value} command {command.command_type}"
        )


def assert_execution_authorized(
    command: AgentCommand,
    approval: ApprovalReceipt | None,
    *,
    agent_name: str | None = None,
) -> None:
    """Gate execution. L3 commands require a matching APPROVE receipt from a human."""
    if not requires_human_approval(command):
        return
    if approval is None:
        raise AuthorityError(f"command {command.command_type} requires human ApprovalReceipt")
    if approval.decision != "APPROVE":
        raise AuthorityError(f"approval decision is {approval.decision}, not APPROVE")
    if approval.command_idempotency_key != command.idempotency_key:
        raise AuthorityError("approval does not match command idempotency_key")
    if approval.tenant_id != command.tenant_id:
        raise AuthorityError("approval tenant_id mismatch")
    # Agents cannot approve their own consequential actions.
    if agent_name and approval.approver_id == agent_name:
        raise AuthorityError("agent cannot approve its own proposal")
    if not approval.approver_id or approval.approver_id.startswith("agent:"):
        raise AuthorityError("approver_id must be a human operator identity")


def assert_proposal_executable(
    proposal: AgentProposal,
    now: str | None = None,
    *,
    block_below: float = 0.75,
) -> None:
    if proposal.is_expired(now):
        raise AuthorityError(f"proposal {proposal.proposal_id} has expired")
    if proposal.contradictions:
        raise AuthorityError(
            f"proposal {proposal.proposal_id} has contradictions: {proposal.contradictions}"
        )
    if proposal.confidence is not None and proposal.confidence < block_below:
        raise AuthorityError(
            f"proposal {proposal.proposal_id} confidence {proposal.confidence} "
            f"< {block_below}; blocked for human review"
        )
