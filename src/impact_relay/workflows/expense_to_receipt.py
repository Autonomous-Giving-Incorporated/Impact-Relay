"""Expense → receipt step handlers (PR-M2).

Pure orchestration of existing agents. Domain mutation only via
``agents.executor.LedgerCommandExecutor`` (never import ledger here).
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from impact_relay.agents.base import AgentContext
from impact_relay.agents.expense_workflow import (
    AllocationClassifierAgent,
    EvidenceValidatorAgent,
    ExpenseIntakeAgent,
    FinanceReviewAgent,
    FinanceReviewPacket,
)
from impact_relay.agents.notification_composer import NotificationComposerAgent
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AuthorityLevel,
    EvidenceSufficiency,
    ValidationResult,
    ValidationStatus,
    WorkflowState,
)
from impact_relay.workflows.machine import assert_transition, default_run_status
from impact_relay.workflows.types import (
    ExecutableCommand,
    FrozenProposedCommand,
    SignalType,
    StepResult,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowRunStatus,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _expires(hours: int = 24) -> str:
    return (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)).isoformat()


@dataclass
class HandlerBundle:
    """Agent instances shared across steps for one run."""

    intake: ExpenseIntakeAgent = field(default_factory=ExpenseIntakeAgent)
    evidence: EvidenceValidatorAgent = field(default_factory=EvidenceValidatorAgent)
    classifier: AllocationClassifierAgent = field(default_factory=AllocationClassifierAgent)
    review: FinanceReviewAgent = field(default_factory=FinanceReviewAgent)
    composer: NotificationComposerAgent = field(default_factory=NotificationComposerAgent)


@dataclass
class StepOutcome:
    """Handler result plus agent artifacts for the linear driver / runtime."""

    step: StepResult
    proposals: list[AgentProposal] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)
    packet: FinanceReviewPacket | None = None
    sufficiency: EvidenceSufficiency | None = None


def freeze_command(
    command: AgentCommand,
    *,
    proposal_id: str,
    agent_name: str,
) -> FrozenProposedCommand:
    return FrozenProposedCommand(
        command_type=command.command_type,
        tenant_id=command.tenant_id,
        payload=dict(command.payload),
        idempotency_key=command.idempotency_key,
        expires_at=command.expires_at,
        required_authority=command.required_authority.value
        if hasattr(command.required_authority, "value")
        else str(command.required_authority),
        proposal_id=proposal_id,
        agent_name=agent_name,
    )


def step_intake(
    ctx: AgentContext,
    expense_rows: list[dict[str, Any]],
    *,
    agents: HandlerBundle | None = None,
    current: WorkflowState = WorkflowState.RECEIVED,
) -> StepOutcome:
    """RECEIVED → NORMALIZED (or BLOCKED). Emits L2 import commands."""
    agents = agents or HandlerBundle()
    batch_cmd = AgentCommand(
        command_type="ingest_expense_batch",
        tenant_id=ctx.tenant_id,
        payload={"expenses": expense_rows, "input_refs": ["fixture_batch"]},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    prop = agents.intake.evaluate(ctx, batch_cmd)
    validation = agents.intake.validate(ctx, prop)
    if not validation.ok:
        nxt = WorkflowState.BLOCKED
        assert_transition(current, nxt)
        return StepOutcome(
            step=StepResult(
                next_state=nxt,
                run_status=default_run_status(nxt),
                terminal_reason=";".join(validation.reasons),
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.STATE_CHANGED,
                        payload={"to": nxt.value, "reason": "intake_validation_failed"},
                    )
                ],
            ),
            proposals=[prop],
            validations=[validation],
        )

    commands = [
        ExecutableCommand(
            command=cmd,
            requires_approval=False,
            approval=None,
            agent_name=agents.intake.name,
            proposal=prop,
        )
        for cmd in prop.proposed_commands
    ]
    nxt = WorkflowState.NORMALIZED
    assert_transition(current, nxt)
    return StepOutcome(
        step=StepResult(
            next_state=nxt,
            run_status=default_run_status(nxt),
            commands_to_execute=commands,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.PROPOSAL,
                    payload={"agent": agents.intake.name, "proposal_id": prop.proposal_id},
                ),
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": nxt.value},
                ),
            ],
            context_patch={"import_command_count": len(commands)},
        ),
        proposals=[prop],
        validations=[validation],
    )


def step_evidence(
    ctx: AgentContext,
    *,
    expense_id: str,
    evidence_items: list[dict[str, Any]],
    evidence_flags: dict[str, Any] | None = None,
    sufficient_kinds: tuple[str, ...] | list[str] | None = None,
    require_donor_visible: bool = True,
    agents: HandlerBundle | None = None,
    current: WorkflowState = WorkflowState.NORMALIZED,
) -> StepOutcome:
    """NORMALIZED/EVIDENCE_PENDING → CLASSIFICATION_PENDING | BLOCKED | NEEDS_INFORMATION."""
    agents = agents or HandlerBundle()
    sufficiency = EvidenceValidatorAgent.assess(
        evidence_items,
        evidence_flags or {},
        sufficient_kinds=sufficient_kinds,
        require_donor_visible=require_donor_visible,
    )
    flags = dict(evidence_flags or {})
    if sufficiency == EvidenceSufficiency.CONTRADICTORY:
        flags["contradictory"] = True
    ev_cmd = AgentCommand(
        command_type="assess_evidence",
        tenant_id=ctx.tenant_id,
        payload={
            "expense_id": expense_id,
            "evidence": evidence_items,
            "flags": flags,
        },
        required_authority=AuthorityLevel.L0_OBSERVE,
    )
    prop = agents.evidence.evaluate(ctx, ev_cmd)
    validation = agents.evidence.validate(ctx, prop)
    if prop.warnings:
        with contextlib.suppress(ValueError):
            sufficiency = EvidenceSufficiency(prop.warnings[0])

    if not validation.ok or sufficiency in (
        EvidenceSufficiency.CONTRADICTORY,
        EvidenceSufficiency.EXPIRED,
    ):
        nxt = WorkflowState.BLOCKED
    elif sufficiency in (
        EvidenceSufficiency.MISSING,
        EvidenceSufficiency.PARTIAL,
        EvidenceSufficiency.REDACTION_REQUIRED,
    ):
        nxt = WorkflowState.NEEDS_INFORMATION
    else:
        nxt = WorkflowState.CLASSIFICATION_PENDING

    # NORMALIZED → EVIDENCE_PENDING is implicit; handlers jump to next action state
    if current == WorkflowState.NORMALIZED and nxt == WorkflowState.CLASSIFICATION_PENDING:
        # Allow via EVIDENCE_PENDING intermediate for machine: NORMALIZED → EVIDENCE_PENDING
        # then EVIDENCE_PENDING → CLASSIFICATION_PENDING. assert both.
        assert_transition(current, WorkflowState.EVIDENCE_PENDING)
        assert_transition(WorkflowState.EVIDENCE_PENDING, nxt)
    elif current == WorkflowState.NORMALIZED:
        assert_transition(current, WorkflowState.EVIDENCE_PENDING)
        assert_transition(WorkflowState.EVIDENCE_PENDING, nxt)
    else:
        assert_transition(current, nxt)

    return StepOutcome(
        step=StepResult(
            next_state=nxt,
            run_status=default_run_status(nxt),
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={
                        "to": nxt.value,
                        "evidence_sufficiency": sufficiency.value,
                    },
                )
            ],
            context_patch={
                "expense_id": expense_id,
                "evidence_sufficiency": sufficiency.value,
            },
            terminal_reason=None
            if nxt == WorkflowState.CLASSIFICATION_PENDING
            else sufficiency.value,
        ),
        proposals=[prop],
        validations=[validation],
        sufficiency=sufficiency,
    )


def step_classify(
    ctx: AgentContext,
    *,
    expense_id: str,
    allocation_id: str | None,
    amount: Any,
    evidence_refs: list[str] | None = None,
    confidence: float = 0.92,
    agents: HandlerBundle | None = None,
    current: WorkflowState = WorkflowState.CLASSIFICATION_PENDING,
) -> StepOutcome:
    """CLASSIFICATION_PENDING → REVIEW_PENDING | NEEDS_INFORMATION. Emits L2 allocate."""
    agents = agents or HandlerBundle()
    class_cmd = AgentCommand(
        command_type="classify_expense",
        tenant_id=ctx.tenant_id,
        payload={
            "expense_id": expense_id,
            "allocation_id": allocation_id,
            "amount": amount,
            "confidence": confidence,
            "evidence_refs": evidence_refs or [],
        },
        required_authority=AuthorityLevel.L1_PROPOSE,
    )
    prop = agents.classifier.evaluate(ctx, class_cmd)
    validation = agents.classifier.validate(ctx, prop)
    if not validation.ok:
        nxt = WorkflowState.NEEDS_INFORMATION
        assert_transition(current, nxt)
        return StepOutcome(
            step=StepResult(
                next_state=nxt,
                run_status=default_run_status(nxt),
                terminal_reason=";".join(validation.reasons),
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.STATE_CHANGED,
                        payload={"to": nxt.value},
                    )
                ],
            ),
            proposals=[prop],
            validations=[validation],
        )

    commands: list[ExecutableCommand] = []
    for cmd in prop.proposed_commands:
        alloc_cmd = AgentCommand(
            command_type=cmd.command_type,
            tenant_id=cmd.tenant_id,
            payload=cmd.payload,
            required_authority=AuthorityLevel.L2_REVERSIBLE,
            idempotency_key=cmd.idempotency_key,
            expires_at=cmd.expires_at,
        )
        commands.append(
            ExecutableCommand(
                command=alloc_cmd,
                requires_approval=False,
                approval=None,
                agent_name=agents.classifier.name,
                proposal=prop,
            )
        )
    nxt = WorkflowState.REVIEW_PENDING
    assert_transition(current, nxt)
    return StepOutcome(
        step=StepResult(
            next_state=nxt,
            run_status=default_run_status(nxt),
            commands_to_execute=commands,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.PROPOSAL,
                    payload={"agent": agents.classifier.name},
                ),
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": nxt.value},
                ),
            ],
            context_patch={"allocation_id": allocation_id, "expense_id": expense_id},
        ),
        proposals=[prop],
        validations=[validation],
    )


def step_review(
    ctx: AgentContext,
    *,
    expense_id: str,
    vendor: str,
    amount: Any,
    currency: str,
    purchase_date: str,
    category: str,
    description: str,
    allocation_id: str | None,
    evidence_sufficiency: str,
    evidence_summaries: list[str],
    confidence: float | None,
    warnings: list[str],
    contradictions: list[str],
    agents: HandlerBundle | None = None,
    current: WorkflowState = WorkflowState.REVIEW_PENDING,
) -> StepOutcome:
    """Assemble finance packet + freeze L3 approve command; park WAITING_SIGNAL."""
    agents = agents or HandlerBundle()
    review_cmd = AgentCommand(
        command_type="assemble_review_packet",
        tenant_id=ctx.tenant_id,
        payload={
            "expense_id": expense_id,
            "vendor": vendor,
            "amount": amount,
            "currency": currency,
            "purchase_date": purchase_date,
            "category": category,
            "description": description,
            "allocation_id": allocation_id,
            "evidence_sufficiency": evidence_sufficiency,
            "evidence_summaries": evidence_summaries,
            "confidence": confidence,
            "warnings": warnings,
            "contradictions": contradictions,
        },
        required_authority=AuthorityLevel.L1_PROPOSE,
    )
    prop = agents.review.evaluate(ctx, review_cmd)
    validation = agents.review.validate(ctx, prop)

    packet = FinanceReviewPacket(
        packet_id=prop.proposed_commands[0].payload.get("packet_id", _new_id("pkt"))
        if prop.proposed_commands
        else _new_id("pkt"),
        tenant_id=ctx.tenant_id,
        expense_id=expense_id,
        vendor=vendor,
        amount=str(amount or ""),
        currency=currency,
        purchase_date=purchase_date,
        category=category,
        description=description,
        proposed_allocation_id=allocation_id,
        evidence_sufficiency=evidence_sufficiency,
        evidence_summaries=evidence_summaries,
        classifier_confidence=confidence,
        warnings=prop.warnings,
        contradictions=prop.contradictions,
        workflow_state=WorkflowState.REVIEW_PENDING.value,
        policy_version=ctx.policy_version,
    )

    if not validation.ok:
        nxt = WorkflowState.BLOCKED
        assert_transition(current, nxt) if current != nxt else None
        # current may already be REVIEW_PENDING
        if current != nxt and not (
            current == WorkflowState.CLASSIFICATION_PENDING and nxt == WorkflowState.BLOCKED
        ):
            # from CLASSIFICATION we go REVIEW first then block — allow REVIEW_PENDING stay
            pass
        return StepOutcome(
            step=StepResult(
                next_state=WorkflowState.BLOCKED
                if validation.status == ValidationStatus.BLOCKED
                else WorkflowState.REVIEW_PENDING,
                run_status=WorkflowRunStatus.WAITING_SIGNAL
                if validation.ok
                else default_run_status(WorkflowState.BLOCKED),
                terminal_reason=";".join(validation.reasons),
            ),
            proposals=[prop],
            validations=[validation],
            packet=packet,
        )

    l3 = prop.proposed_commands[0]
    frozen = freeze_command(l3, proposal_id=prop.proposal_id, agent_name=agents.review.name)
    wait_deadline = (datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)).isoformat()
    nxt = WorkflowState.REVIEW_PENDING
    # CLASSIFICATION_PENDING → REVIEW_PENDING
    if current != nxt:
        assert_transition(current, nxt)

    return StepOutcome(
        step=StepResult(
            next_state=nxt,
            run_status=WorkflowRunStatus.WAITING_SIGNAL,
            wait_for=SignalType.APPROVAL,
            wait_payload={
                "frozen_command": frozen.to_dict(),
                "proposal_id": prop.proposal_id,
                "command_idempotency_key": l3.idempotency_key,
            },
            wait_deadline=wait_deadline,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.PROPOSAL,
                    payload={"agent": agents.review.name, "proposal_id": prop.proposal_id},
                ),
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": nxt.value, "wait": "APPROVAL"},
                ),
            ],
            context_patch={
                "wait": {
                    "signal_type": "APPROVAL",
                    "proposal_id": prop.proposal_id,
                    "command_type": l3.command_type,
                    "command_idempotency_key": l3.idempotency_key,
                    "frozen_command": frozen.to_dict(),
                },
                "packet_id": packet.packet_id,
            },
        ),
        proposals=[prop],
        validations=[validation],
        packet=packet,
    )


def step_compose_send(
    ctx: AgentContext,
    *,
    preview_dict: dict[str, Any],
    agents: HandlerBundle | None = None,
    current: WorkflowState = WorkflowState.PUBLISHED,
) -> StepOutcome:
    """PUBLISHED → NOTIFICATION_PENDING with frozen send_notification L3."""
    agents = agents or HandlerBundle()
    compose_cmd = AgentCommand(
        command_type="compose_send_proposal",
        tenant_id=ctx.tenant_id,
        payload={"preview": preview_dict},
        required_authority=AuthorityLevel.L1_PROPOSE,
    )
    prop = agents.composer.evaluate(ctx, compose_cmd)
    validation = agents.composer.validate(ctx, prop)
    nxt = WorkflowState.NOTIFICATION_PENDING
    assert_transition(current, nxt)
    if not validation.ok or not prop.proposed_commands:
        return StepOutcome(
            step=StepResult(
                next_state=nxt,
                run_status=default_run_status(nxt),
                terminal_reason=";".join(validation.reasons) or "no send command",
            ),
            proposals=[prop],
            validations=[validation],
        )
    send_cmd = prop.proposed_commands[0]
    frozen = freeze_command(send_cmd, proposal_id=prop.proposal_id, agent_name=agents.composer.name)
    return StepOutcome(
        step=StepResult(
            next_state=nxt,
            run_status=WorkflowRunStatus.WAITING_SIGNAL,
            wait_for=SignalType.APPROVAL,
            wait_payload={
                "frozen_command": frozen.to_dict(),
                "proposal_id": prop.proposal_id,
            },
            wait_deadline=(
                datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)
            ).isoformat(),
            context_patch={
                "wait": {
                    "signal_type": "APPROVAL",
                    "proposal_id": prop.proposal_id,
                    "command_type": send_cmd.command_type,
                    "command_idempotency_key": send_cmd.idempotency_key,
                    "frozen_command": frozen.to_dict(),
                }
            },
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": nxt.value, "wait": "APPROVAL"},
                )
            ],
        ),
        proposals=[prop],
        validations=[validation],
    )
