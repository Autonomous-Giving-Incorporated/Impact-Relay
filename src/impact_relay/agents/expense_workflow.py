"""Fixture-backed expense → human approval → ledger → UOF receipt vertical slice.

Agents propose; ``LedgerCommandExecutor`` (agents.executor) is the sole ledger
mutation gateway. Step handlers live in ``workflows.expense_to_receipt``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from impact_relay.agents.authority import AuthorityError, assert_agent_may_propose
from impact_relay.agents.base import AgentContext, CommandExecutor, build_run_receipt
from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.notification_composer import (
    EmailPreview,
    assert_preview_matches_receipt,
    compose_email_from_uof,
)
from impact_relay.agents.privacy import assert_public_safe
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AgentRunReceipt,
    AgentRunStatus,
    ApprovalReceipt,
    AuthorityLevel,
    EvidenceSufficiency,
    ExecutionReceipt,
    ValidationResult,
    ValidationStatus,
    WorkflowState,
    stable_hash,
    to_jsonable,
    utc_now_iso,
)
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import UseOfFundsReceipt
from impact_relay.policy import TenantPolicy, default_policy
from impact_relay.public_export import receipt_to_public

if TYPE_CHECKING:
    from impact_relay.domain.ledger import Ledger


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _expires(hours: int = 24) -> str:
    return (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Normalized import contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedExpenseImport:
    """Provider-normalized expense row (fixture or future adapter output)."""

    external_source_id: str
    tenant_id: str
    vendor: str
    amount: str
    currency: str
    purchase_date: str
    category: str
    description: str
    proposed_allocation_id: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            key = stable_hash(
                {
                    "external_source_id": self.external_source_id,
                    "tenant_id": self.tenant_id,
                    "amount": self.amount,
                    "purchase_date": self.purchase_date,
                }
            )
            object.__setattr__(self, "idempotency_key", key)


def normalize_expense_row(row: dict[str, Any], *, tenant_id: str) -> NormalizedExpenseImport:
    ext = row.get("external_source_id") or row.get("externalSourceId") or row.get("id")
    if not ext:
        raise ValueError("expense row missing external_source_id")
    return NormalizedExpenseImport(
        external_source_id=str(ext),
        tenant_id=tenant_id,
        vendor=str(row["vendor"]),
        amount=str(row["amount"]),
        currency=str(row.get("currency", "USD")),
        purchase_date=str(row["purchase_date"]),
        category=str(row.get("category", "UNCLASSIFIED")),
        description=str(row.get("description", "")),
        proposed_allocation_id=row.get("allocation_id") or row.get("proposed_allocation_id"),
        evidence=list(row.get("evidence") or []),
    )


# ---------------------------------------------------------------------------
# Agents (pure evaluate / validate)
# ---------------------------------------------------------------------------


class ExpenseIntakeAgent:
    name = "expense_intake"
    version = "0.5.0"
    authority_level = AuthorityLevel.L2_REVERSIBLE

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        if command.command_type != "ingest_expense_batch":
            raise ValueError(f"unsupported command: {command.command_type}")
        rows = command.payload.get("expenses") or []
        normalized: list[dict[str, Any]] = []
        proposed: list[AgentCommand] = []
        warnings: list[str] = []
        for raw in rows:
            n = normalize_expense_row(raw, tenant_id=context.tenant_id)
            normalized.append(to_jsonable(n))
            import_cmd = AgentCommand(
                command_type="import_normalized_expense",
                tenant_id=context.tenant_id,
                payload={"expense": to_jsonable(n)},
                required_authority=AuthorityLevel.L2_REVERSIBLE,
                idempotency_key=f"import:{n.idempotency_key}",
                expires_at=_expires(),
            )
            assert_agent_may_propose(self.authority_level, import_cmd)
            proposed.append(import_cmd)

        if not rows:
            warnings.append("empty expense batch")

        return AgentProposal(
            proposal_id=_new_id("prop"),
            tenant_id=context.tenant_id,
            agent_name=self.name,
            agent_version=self.version,
            policy_version=context.policy_version,
            prompt_version=context.prompt_version,
            input_refs=command.payload.get("input_refs") or ["batch"],
            input_hash=stable_hash(command.payload),
            proposed_commands=proposed,
            evidence_refs=[],
            confidence=1.0 if rows else 0.0,
            warnings=warnings,
            contradictions=[],
            required_authority=AuthorityLevel.L2_REVERSIBLE,
            expires_at=_expires(),
            idempotency_key=f"intake:{stable_hash(command.payload)[:16]}",
            notes=f"normalized {len(normalized)} expense row(s)",
        )

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        if proposal.tenant_id != context.tenant_id:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reasons=["tenant_id mismatch"],
            )
        if proposal.is_expired(context.now):
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reasons=["proposal expired"],
            )
        return ValidationResult(status=ValidationStatus.ACCEPTED)


class AllocationClassifierAgent:
    name = "allocation_classifier"
    version = "0.5.0"
    authority_level = AuthorityLevel.L1_PROPOSE

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        if command.command_type != "classify_expense":
            raise ValueError(f"unsupported command: {command.command_type}")
        expense_id = command.payload["expense_id"]
        allocation_id = command.payload.get("allocation_id") or context.facts.get(
            "default_allocation_id"
        )
        amount = command.payload.get("amount")
        confidence = float(command.payload.get("confidence", 0.9))
        contradictions: list[str] = list(command.payload.get("contradictions") or [])
        warnings: list[str] = []
        if not allocation_id:
            confidence = 0.0
            warnings.append("no allocation_id available")
        classify_cmd = AgentCommand(
            command_type="allocate_expense",
            tenant_id=context.tenant_id,
            payload={
                "expense_id": expense_id,
                "allocation_id": allocation_id,
                "amount": amount,
            },
            required_authority=AuthorityLevel.L1_PROPOSE,
            idempotency_key=f"alloc:{expense_id}:{allocation_id}:{amount}",
            expires_at=_expires(),
        )
        # Classification is a proposal; applying allocation is reversible L2 in executor
        # but the *approval* of the expense remains L3.
        assert_agent_may_propose(self.authority_level, classify_cmd)
        return AgentProposal(
            proposal_id=_new_id("prop"),
            tenant_id=context.tenant_id,
            agent_name=self.name,
            agent_version=self.version,
            policy_version=context.policy_version,
            prompt_version=context.prompt_version,
            input_refs=[expense_id],
            input_hash=stable_hash(command.payload),
            proposed_commands=[classify_cmd],
            evidence_refs=list(command.payload.get("evidence_refs") or []),
            confidence=confidence,
            warnings=warnings,
            contradictions=contradictions,
            required_authority=AuthorityLevel.L1_PROPOSE,
            expires_at=_expires(),
            idempotency_key=f"classify:{expense_id}",
            notes="allocation classification proposal",
        )

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        if proposal.contradictions:
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                reasons=["contradictory classification signals"],
                warnings=proposal.contradictions,
            )
        threshold = context.confidence_block_below
        if proposal.confidence is not None and proposal.confidence < threshold:
            return ValidationResult(
                status=ValidationStatus.NEEDS_INFORMATION,
                reasons=[f"low confidence {proposal.confidence} < {threshold}"],
            )
        return ValidationResult(status=ValidationStatus.ACCEPTED)


class EvidenceValidatorAgent:
    name = "evidence_validator"
    version = "0.5.0"
    authority_level = AuthorityLevel.L0_OBSERVE

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        # L0: observe-only — produce assessment, no commands.
        evidence_items = command.payload.get("evidence") or []
        flags = command.payload.get("flags") or {}
        state = self.assess(evidence_items, flags)
        return AgentProposal(
            proposal_id=_new_id("prop"),
            tenant_id=context.tenant_id,
            agent_name=self.name,
            agent_version=self.version,
            policy_version=context.policy_version,
            prompt_version=context.prompt_version,
            input_refs=[command.payload.get("expense_id", "expense")],
            input_hash=stable_hash(command.payload),
            proposed_commands=[],  # L0 never proposes mutations
            evidence_refs=[e.get("id", f"ev_{i}") for i, e in enumerate(evidence_items)],
            confidence=1.0 if state == EvidenceSufficiency.SUFFICIENT else 0.5,
            warnings=[] if state == EvidenceSufficiency.SUFFICIENT else [state.value],
            contradictions=(
                ["contradictory evidence"] if state == EvidenceSufficiency.CONTRADICTORY else []
            ),
            required_authority=AuthorityLevel.L0_OBSERVE,
            expires_at=_expires(48),
            idempotency_key=f"evidence:{command.payload.get('expense_id', 'x')}",
            notes=f"evidence sufficiency={state.value}",
        )

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        if proposal.proposed_commands:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reasons=["evidence validator must not propose commands"],
            )
        if proposal.contradictions:
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                reasons=proposal.contradictions,
            )
        return ValidationResult(status=ValidationStatus.ACCEPTED)

    @staticmethod
    def assess(
        evidence_items: list[dict[str, Any]],
        flags: dict[str, Any] | None = None,
        *,
        sufficient_kinds: tuple[str, ...] | list[str] | None = None,
        require_donor_visible: bool = True,
    ) -> EvidenceSufficiency:
        flags = flags or {}
        if flags.get("contradictory"):
            return EvidenceSufficiency.CONTRADICTORY
        if flags.get("expired"):
            return EvidenceSufficiency.EXPIRED
        if flags.get("redaction_required"):
            return EvidenceSufficiency.REDACTION_REQUIRED
        if not evidence_items:
            return EvidenceSufficiency.MISSING
        kinds_ok = tuple(sufficient_kinds or ("invoice", "receipt", "accounting_ref"))
        if require_donor_visible:
            donor_visible = [e for e in evidence_items if e.get("donor_visible", True)]
            if not donor_visible:
                return EvidenceSufficiency.PARTIAL
            scan = donor_visible
        else:
            scan = evidence_items
        kinds = {e.get("kind") for e in scan}
        if any(k in kinds for k in kinds_ok):
            return EvidenceSufficiency.SUFFICIENT
        return EvidenceSufficiency.PARTIAL


@dataclass
class FinanceReviewPacket:
    """Projection for human finance review — not a ledger mutation."""

    packet_id: str
    tenant_id: str
    expense_id: str
    vendor: str
    amount: str
    currency: str
    purchase_date: str
    category: str
    description: str
    proposed_allocation_id: str | None
    evidence_sufficiency: str
    evidence_summaries: list[str]
    classifier_confidence: float | None
    warnings: list[str]
    contradictions: list[str]
    workflow_state: str
    policy_version: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


class FinanceReviewAgent:
    name = "finance_review"
    version = "0.5.0"
    authority_level = AuthorityLevel.L1_PROPOSE

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        if command.command_type != "assemble_review_packet":
            raise ValueError(f"unsupported command: {command.command_type}")
        packet = FinanceReviewPacket(
            packet_id=_new_id("pkt"),
            tenant_id=context.tenant_id,
            expense_id=command.payload["expense_id"],
            vendor=command.payload.get("vendor", ""),
            amount=str(command.payload.get("amount", "")),
            currency=command.payload.get("currency", "USD"),
            purchase_date=command.payload.get("purchase_date", ""),
            category=command.payload.get("category", ""),
            description=command.payload.get("description", ""),
            proposed_allocation_id=command.payload.get("allocation_id"),
            evidence_sufficiency=command.payload.get(
                "evidence_sufficiency", EvidenceSufficiency.MISSING.value
            ),
            evidence_summaries=list(command.payload.get("evidence_summaries") or []),
            classifier_confidence=command.payload.get("confidence"),
            warnings=list(command.payload.get("warnings") or []),
            contradictions=list(command.payload.get("contradictions") or []),
            workflow_state=WorkflowState.REVIEW_PENDING.value,
            policy_version=context.policy_version,
        )
        approve_cmd = AgentCommand(
            command_type="approve_expense",
            tenant_id=context.tenant_id,
            payload={
                "expense_id": packet.expense_id,
                "packet_id": packet.packet_id,
            },
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            idempotency_key=f"approve:{packet.expense_id}:{packet.packet_id}",
            expires_at=_expires(72),
        )
        assert_agent_may_propose(self.authority_level, approve_cmd)
        return AgentProposal(
            proposal_id=_new_id("prop"),
            tenant_id=context.tenant_id,
            agent_name=self.name,
            agent_version=self.version,
            policy_version=context.policy_version,
            prompt_version=context.prompt_version,
            input_refs=[packet.expense_id, packet.packet_id],
            input_hash=stable_hash(packet.to_dict()),
            proposed_commands=[approve_cmd],
            evidence_refs=[],
            confidence=command.payload.get("confidence", 0.9),
            warnings=packet.warnings,
            contradictions=packet.contradictions,
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            expires_at=_expires(72),
            idempotency_key=f"review:{packet.expense_id}",
            notes="finance review packet assembled; human approval required",
        )

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        if proposal.contradictions:
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                reasons=["cannot advance contradictory review packet"],
            )
        return ValidationResult(status=ValidationStatus.ACCEPTED)


# Re-export for backward compatibility (canonical home: agents.executor)
__all_executor__ = ("LedgerCommandExecutor",)

# ---------------------------------------------------------------------------
# Orchestrated vertical slice (linear driver over step handlers)
# ---------------------------------------------------------------------------


@dataclass
class ExpenseSliceResult:
    workflow_state: WorkflowState
    packets: list[FinanceReviewPacket]
    proposals: list[AgentProposal]
    validations: list[ValidationResult]
    approvals: list[ApprovalReceipt]
    executions: list[ExecutionReceipt]
    receipts: list[UseOfFundsReceipt]
    run_receipt: AgentRunReceipt
    public_previews: list[dict[str, Any]] = field(default_factory=list)
    email_previews: list[EmailPreview] = field(default_factory=list)
    delivery_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_state": self.workflow_state.value,
            "packets": [p.to_dict() for p in self.packets],
            "proposals": [to_jsonable(p) for p in self.proposals],
            "validations": [to_jsonable(v) for v in self.validations],
            "approvals": [to_jsonable(a) for a in self.approvals],
            "executions": [to_jsonable(e) for e in self.executions],
            "receipt_ids": [r.receipt_id for r in self.receipts],
            "run_receipt": to_jsonable(self.run_receipt),
            "public_previews": self.public_previews,
            "email_previews": [p.to_dict() for p in self.email_previews],
            "delivery_refs": self.delivery_refs,
        }


def run_expense_approval_slice(
    ledger: Ledger,
    *,
    expense_rows: list[dict[str, Any]],
    human_approver_id: str,
    human_approver_role: str = "finance_approver",
    approve: bool = True,
    simulation: bool = False,
    publish_specs: list[dict[str, Any]] | None = None,
    evidence_flags: dict[str, Any] | None = None,
    send_email: bool = False,
    communications_approver_id: str | None = None,
    tenant_policy: TenantPolicy | None = None,
) -> ExpenseSliceResult:
    """Public entry: dispatches via WORKFLOW_SLICE_FACADE (default runtime, PR-M6).

    Set ``WORKFLOW_SLICE_FACADE=legacy`` to force the linear driver.
    """
    from impact_relay.workflows.facade import (
        run_expense_approval_slice as _facade_run_expense_approval_slice,
    )

    return _facade_run_expense_approval_slice(
        ledger,
        expense_rows=expense_rows,
        human_approver_id=human_approver_id,
        human_approver_role=human_approver_role,
        approve=approve,
        simulation=simulation,
        publish_specs=publish_specs,
        evidence_flags=evidence_flags,
        send_email=send_email,
        communications_approver_id=communications_approver_id,
        tenant_policy=tenant_policy,
    )


def run_expense_approval_slice_legacy(
    ledger: Ledger,
    *,
    expense_rows: list[dict[str, Any]],
    human_approver_id: str,
    human_approver_role: str = "finance_approver",
    approve: bool = True,
    simulation: bool = False,
    publish_specs: list[dict[str, Any]] | None = None,
    evidence_flags: dict[str, Any] | None = None,
    send_email: bool = False,
    communications_approver_id: str | None = None,
    tenant_policy: TenantPolicy | None = None,
) -> ExpenseSliceResult:
    """Linear driver over step handlers (T0/legacy path).

    When ``approve`` is False, stops at REVIEW_PENDING with a packet and L3 proposal.
    When ``simulation`` is True, CommandExecutor never mutates the ledger.
    When ``send_email`` is True (after publish), composes an email preview and
    requires a *separate* L3 send approval before fixture delivery.
    """
    # Lazy import avoids circular import: steps import agent classes from this module.
    from impact_relay.workflows.expense_to_receipt import (
        HandlerBundle,
        step_classify,
        step_compose_send,
        step_evidence,
        step_intake,
        step_review,
    )

    started = utc_now_iso()
    tenant_id = ledger.organization.id
    policy = tenant_policy or default_policy(tenant_id, ledger.organization.policy_version)
    ctx = AgentContext(
        tenant_id=tenant_id,
        policy_version=policy.version,
        facts={
            "default_allocation_id": next(iter(ledger.allocations), None),
            "default_attribution_method": policy.attribution.default_method,
        },
        policy=policy.to_dict(),
    )
    agents = HandlerBundle()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    executor = LedgerCommandExecutor(ledger, simulation=simulation, workspace=workspace)

    proposals: list[AgentProposal] = []
    validations: list[ValidationResult] = []
    approvals: list[ApprovalReceipt] = []
    packets: list[FinanceReviewPacket] = []
    receipts: list[UseOfFundsReceipt] = []
    public_previews: list[dict[str, Any]] = []
    email_previews: list[EmailPreview] = []
    delivery_refs: list[dict[str, Any]] = []
    send_approver = communications_approver_id or human_approver_id

    # 1) Intake batch via step handler
    intake_out = step_intake(ctx, expense_rows, agents=agents)
    proposals.extend(intake_out.proposals)
    validations.extend(intake_out.validations)
    if intake_out.step.next_state == WorkflowState.BLOCKED:
        return _blocked_result(
            tenant_id,
            started,
            proposals,
            validations,
            approvals,
            executor,
            packets,
            receipts,
        )

    for executable in intake_out.step.commands_to_execute:
        executor.execute(executable.command)

    imported_ids: list[str] = []
    for executable in intake_out.step.commands_to_execute:
        row = executable.command.payload["expense"]
        ext = row["external_source_id"]
        if simulation:
            imported_ids.append(f"sim_{ext}")
            continue
        match = next(
            (e for e in ledger.expenses.values() if e.external_source_id == ext),
            None,
        )
        if match:
            imported_ids.append(match.id)

    workflow = WorkflowState.NORMALIZED
    if not imported_ids and not simulation:
        workflow = WorkflowState.DUPLICATE

    for idx, expense_id in enumerate(imported_ids):
        row = expense_rows[idx] if idx < len(expense_rows) else {}
        amount = row.get("amount")
        if not simulation and expense_id in ledger.expenses:
            amount = str(ledger.expenses[expense_id].amount)
            vendor = ledger.expenses[expense_id].vendor
            purchase_date = ledger.expenses[expense_id].purchase_date
            category = ledger.expenses[expense_id].category
            description = ledger.expenses[expense_id].description
            currency = ledger.expenses[expense_id].currency
            evidence_items = [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "summary": e.summary,
                    "donor_visible": e.donor_visible,
                }
                for e in ledger.evidence.values()
                if e.expense_id == expense_id
            ]
        else:
            vendor = row.get("vendor", "")
            purchase_date = row.get("purchase_date", "")
            category = row.get("category", "")
            description = row.get("description", "")
            currency = row.get("currency", "USD")
            evidence_items = list(row.get("evidence") or [])

        allocation_id = (
            row.get("allocation_id")
            or row.get("proposed_allocation_id")
            or ctx.facts.get("default_allocation_id")
        )

        # 2) Evidence
        ev_out = step_evidence(
            ctx,
            expense_id=expense_id,
            evidence_items=evidence_items,
            evidence_flags=evidence_flags,
            sufficient_kinds=policy.evidence.sufficient_kinds,
            require_donor_visible=policy.evidence.require_donor_visible,
            agents=agents,
            current=WorkflowState.NORMALIZED,
        )
        proposals.extend(ev_out.proposals)
        validations.extend(ev_out.validations)
        sufficiency = ev_out.sufficiency or EvidenceSufficiency.MISSING
        if ev_out.step.next_state != WorkflowState.CLASSIFICATION_PENDING:
            workflow = ev_out.step.next_state
            packets.append(
                FinanceReviewPacket(
                    packet_id=_new_id("pkt"),
                    tenant_id=tenant_id,
                    expense_id=expense_id,
                    vendor=vendor,
                    amount=str(amount or ""),
                    currency=currency,
                    purchase_date=purchase_date,
                    category=category,
                    description=description,
                    proposed_allocation_id=allocation_id,
                    evidence_sufficiency=sufficiency.value,
                    evidence_summaries=[str(e.get("summary", "")) for e in evidence_items],
                    classifier_confidence=None,
                    warnings=ev_out.proposals[0].warnings if ev_out.proposals else [],
                    contradictions=ev_out.proposals[0].contradictions if ev_out.proposals else [],
                    workflow_state=workflow.value,
                    policy_version=ctx.policy_version,
                )
            )
            continue

        # 3) Classify + allocate
        class_out = step_classify(
            ctx,
            expense_id=expense_id,
            allocation_id=allocation_id,
            amount=amount,
            evidence_refs=[str(e.get("id")) for e in evidence_items if e.get("id")],
            agents=agents,
            current=WorkflowState.CLASSIFICATION_PENDING,
        )
        proposals.extend(class_out.proposals)
        validations.extend(class_out.validations)
        if class_out.step.next_state != WorkflowState.REVIEW_PENDING:
            workflow = class_out.step.next_state
            continue

        for executable in class_out.step.commands_to_execute:
            executor.execute(executable.command)

        class_prop = class_out.proposals[0]
        # 4) Review packet + L3 wait
        review_out = step_review(
            ctx,
            expense_id=expense_id,
            vendor=vendor,
            amount=amount,
            currency=currency,
            purchase_date=purchase_date,
            category=category,
            description=description,
            allocation_id=allocation_id,
            evidence_sufficiency=sufficiency.value,
            evidence_summaries=[str(e.get("summary", "")) for e in evidence_items],
            confidence=class_prop.confidence,
            warnings=list(class_prop.warnings)
            + list(ev_out.proposals[0].warnings if ev_out.proposals else []),
            contradictions=list(class_prop.contradictions),
            agents=agents,
            current=WorkflowState.CLASSIFICATION_PENDING,
        )
        proposals.extend(review_out.proposals)
        validations.extend(review_out.validations)
        packet = review_out.packet
        if packet is None:
            workflow = review_out.step.next_state
            continue
        packets.append(packet)
        workflow = WorkflowState.REVIEW_PENDING
        review_prop = review_out.proposals[0]
        review_v = review_out.validations[0]

        if not review_v.ok or not approve:
            continue

        if human_approver_id.startswith("agent:"):
            raise AuthorityError("human_approver_id must not be an agent identity")

        l3_cmd = review_prop.proposed_commands[0]
        approval = ApprovalReceipt(
            approval_id=_new_id("appr"),
            tenant_id=tenant_id,
            proposal_id=review_prop.proposal_id,
            command_idempotency_key=l3_cmd.idempotency_key,
            decision="APPROVE" if approve else "REJECT",
            approver_id=human_approver_id,
            approver_role=human_approver_role,
            approved_at=utc_now_iso(),
            rationale="fixture vertical slice approval",
            policy_version=ctx.policy_version,
        )
        approvals.append(approval)

        approve_payload = {**l3_cmd.payload, "approved_by": human_approver_id}
        exec_cmd = AgentCommand(
            command_type=l3_cmd.command_type,
            tenant_id=l3_cmd.tenant_id,
            payload=approve_payload,
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            idempotency_key=l3_cmd.idempotency_key,
            expires_at=l3_cmd.expires_at,
        )
        exec_receipt = executor.execute(
            exec_cmd,
            approval=approval,
            agent_name=agents.review.name,
            proposal=review_prop,
        )
        if exec_receipt.status == "SUCCEEDED":
            workflow = WorkflowState.LEDGER_COMMITTED
            packet.workflow_state = workflow.value

        for spec in publish_specs or []:
            if spec.get("expense_id") not in (expense_id, None, "*"):
                if spec.get("expense_id") != expense_id:
                    continue
            pub_payload = {
                "donor_id": spec["donor_id"],
                "donation_id": spec["donation_id"],
                "expense_id": expense_id,
                "allocation_id": spec.get("allocation_id") or allocation_id,
                "attribution_method": spec["attribution_method"],
                "attributed_amount": spec["attributed_amount"],
                "created_at": spec.get("created_at"),
                "actor": spec.get("actor") or human_approver_id,
            }
            pub_cmd = AgentCommand(
                command_type="publish_use_of_funds_receipt",
                tenant_id=tenant_id,
                payload=pub_payload,
                required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
                idempotency_key=f"publish:{expense_id}:{spec['donation_id']}",
            )
            pub_approval = ApprovalReceipt(
                approval_id=_new_id("appr"),
                tenant_id=tenant_id,
                proposal_id=review_prop.proposal_id,
                command_idempotency_key=pub_cmd.idempotency_key,
                decision="APPROVE",
                approver_id=human_approver_id,
                approver_role="communications_approver",
                approved_at=utc_now_iso(),
                rationale="publish UOF after finance approval",
                policy_version=ctx.policy_version,
            )
            approvals.append(pub_approval)
            pub_exec = executor.execute(
                pub_cmd, approval=pub_approval, agent_name=agents.review.name
            )
            if pub_exec.status == "SUCCEEDED" and not simulation:
                rid = pub_exec.output_refs[0]
                rec = ledger.receipts[rid]
                receipts.append(rec)
                preview = receipt_to_public(rec)
                assert_public_safe(preview)
                public_previews.append(preview)
                workflow = WorkflowState.PUBLISHED

                if send_email:
                    email_prev = compose_email_from_uof(rec)
                    assert_preview_matches_receipt(email_prev, rec)
                    executor.register_preview(email_prev)
                    email_previews.append(email_prev)
                    send_out = step_compose_send(
                        ctx,
                        preview_dict=email_prev.to_dict(),
                        agents=agents,
                        current=WorkflowState.PUBLISHED,
                    )
                    proposals.extend(send_out.proposals)
                    validations.extend(send_out.validations)
                    if (
                        send_out.step.next_state != WorkflowState.NOTIFICATION_PENDING
                        or not send_out.proposals
                        or not send_out.proposals[0].proposed_commands
                    ):
                        workflow = WorkflowState.NOTIFICATION_PENDING
                        continue
                    workflow = WorkflowState.NOTIFICATION_PENDING
                    compose_prop = send_out.proposals[0]
                    send_cmd = compose_prop.proposed_commands[0]
                    if send_approver.startswith("agent:"):
                        raise AuthorityError(
                            "communications approver must not be an agent identity"
                        )
                    send_approval = ApprovalReceipt(
                        approval_id=_new_id("appr"),
                        tenant_id=tenant_id,
                        proposal_id=compose_prop.proposal_id,
                        command_idempotency_key=send_cmd.idempotency_key,
                        decision="APPROVE",
                        approver_id=send_approver,
                        approver_role="communications_approver",
                        approved_at=utc_now_iso(),
                        rationale="independent send approval for UOF email",
                        policy_version=ctx.policy_version,
                    )
                    approvals.append(send_approval)
                    send_exec = executor.execute(
                        send_cmd,
                        approval=send_approval,
                        agent_name=agents.composer.name,
                        proposal=compose_prop,
                    )
                    if send_exec.status == "SUCCEEDED":
                        delivery_refs.append(
                            {
                                "receipt_id": rec.receipt_id,
                                "preview_id": email_prev.preview_id,
                                "intent_id": send_exec.output_refs[0]
                                if send_exec.output_refs
                                else None,
                                "delivery_id": send_exec.output_refs[1]
                                if len(send_exec.output_refs) > 1
                                else None,
                                "status": "DELIVERED",
                            }
                        )
                        workflow = WorkflowState.DELIVERED

    run = build_run_receipt(
        run_id=_new_id("run"),
        tenant_id=tenant_id,
        workflow="expense_to_receipt",
        agent="orchestrator",
        agent_version="0.5.0",
        policy_version=ctx.policy_version,
        prompt_version=None,
        input_refs=["expense_batch"],
        input_payload=expense_rows,
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executor.receipts,
        started_at=started,
        status=AgentRunStatus.SIMULATED if simulation else None,
    )
    return ExpenseSliceResult(
        workflow_state=workflow,
        packets=packets,
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executor.receipts,
        receipts=receipts,
        run_receipt=run,
        public_previews=public_previews,
        email_previews=email_previews,
        delivery_refs=delivery_refs,
    )


def _blocked_result(
    tenant_id: str,
    started: str,
    proposals: list[AgentProposal],
    validations: list[ValidationResult],
    approvals: list[ApprovalReceipt],
    executor: CommandExecutor,
    packets: list[FinanceReviewPacket],
    receipts: list[UseOfFundsReceipt],
) -> ExpenseSliceResult:
    run = build_run_receipt(
        run_id=_new_id("run"),
        tenant_id=tenant_id,
        workflow="expense_to_receipt",
        agent="orchestrator",
        agent_version="0.5.0",
        policy_version="v1.0",
        prompt_version=None,
        input_refs=["expense_batch"],
        input_payload={},
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executor.receipts,
        started_at=started,
        status=AgentRunStatus.BLOCKED,
    )
    return ExpenseSliceResult(
        workflow_state=WorkflowState.BLOCKED,
        packets=packets,
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executor.receipts,
        receipts=receipts,
        run_receipt=run,
        email_previews=[],
        delivery_refs=[],
    )
