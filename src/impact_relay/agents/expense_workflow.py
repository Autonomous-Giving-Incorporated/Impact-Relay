"""Fixture-backed expense → human approval → ledger → UOF receipt vertical slice.

This is the first v0.5/v0.6 path that wraps the deterministic ledger with
agent proposals and hard human gates. Agents never call Ledger mutation APIs
directly — only LedgerCommandExecutor does, after ApprovalReceipt checks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from impact_relay.agents.authority import AuthorityError, assert_agent_may_propose
from impact_relay.agents.base import AgentContext, CommandExecutor, build_run_receipt
from impact_relay.agents.notification_composer import (
    EmailPreview,
    NotificationComposerAgent,
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
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    AttributionMethod,
    ConsentRecord,
    EvidenceRecord,
    Expense,
    ExpenseState,
    NotificationChannel,
    NotificationPreference,
    UseOfFundsReceipt,
    money,
)
from impact_relay.public_export import receipt_to_public


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _expires(hours: int = 24) -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
    ).isoformat()


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
        if proposal.confidence is not None and proposal.confidence < 0.75:
            return ValidationResult(
                status=ValidationStatus.NEEDS_INFORMATION,
                reasons=[f"low confidence {proposal.confidence}"],
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
                ["contradictory evidence"]
                if state == EvidenceSufficiency.CONTRADICTORY
                else []
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
        donor_visible = [e for e in evidence_items if e.get("donor_visible", True)]
        if not donor_visible:
            return EvidenceSufficiency.PARTIAL
        kinds = {e.get("kind") for e in evidence_items}
        if "invoice" in kinds or "receipt" in kinds or "accounting_ref" in kinds:
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


# ---------------------------------------------------------------------------
# Ledger-backed executor (only mutation path)
# ---------------------------------------------------------------------------


class LedgerCommandExecutor(CommandExecutor):
    """Dispatches approved/reversible commands onto a Ledger instance."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        simulation: bool = False,
        workspace: TenantWorkspace | None = None,
    ) -> None:
        super().__init__(simulation=simulation)
        self.ledger = ledger
        self.workspace = workspace
        # external_source_id -> expense_id for dedup
        self._external_index: dict[str, str] = {
            e.external_source_id: e.id
            for e in ledger.expenses.values()
            if e.external_source_id
        }
        # preview_id -> EmailPreview for send gate
        self.previews: dict[str, EmailPreview] = {}

    def register_preview(self, preview: EmailPreview) -> None:
        self.previews[preview.preview_id] = preview

    def _dispatch(self, command: AgentCommand) -> tuple[list[str], dict[str, Any]]:
        if command.tenant_id != self.ledger.organization.id:
            raise AuthorityError("cross-tenant command rejected")

        if command.command_type == "import_normalized_expense":
            return self._import_normalized(command.payload["expense"])
        if command.command_type == "allocate_expense":
            return self._allocate(command.payload)
        if command.command_type == "approve_expense":
            return self._approve(command.payload)
        if command.command_type == "reject_expense":
            return self._reject(command.payload)
        if command.command_type == "publish_use_of_funds_receipt":
            return self._publish_receipt(command.payload)
        if command.command_type == "send_notification":
            return self._send_notification(command.payload)
        raise NotImplementedError(f"unsupported command_type={command.command_type}")

    def _import_normalized(self, row: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        ext = row["external_source_id"]
        if ext in self._external_index:
            eid = self._external_index[ext]
            return [eid], {"expense_id": eid, "duplicate": True}

        expense_id = row.get("expense_id") or _new_id("exp")
        expense = Expense(
            id=expense_id,
            organization_id=self.ledger.organization.id,
            vendor=row["vendor"],
            amount=money(row["amount"]),
            currency=row.get("currency", "USD"),
            purchase_date=row["purchase_date"],
            category=row.get("category", "UNCLASSIFIED"),
            description=row.get("description", ""),
            state=ExpenseState.IMPORTED,
            external_source_id=ext,
        )
        self.ledger.import_expense(expense)
        for ev in row.get("evidence") or []:
            self.ledger.attach_evidence(
                EvidenceRecord(
                    id=ev.get("id") or _new_id("ev"),
                    expense_id=expense_id,
                    kind=ev.get("kind", "invoice"),
                    summary=ev.get("summary", ""),
                    donor_visible=bool(ev.get("donor_visible", True)),
                )
            )
        self._external_index[ext] = expense_id
        return [expense_id], {"expense_id": expense_id, "duplicate": False}

    def _allocate(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        expense_id = payload["expense_id"]
        allocation_id = payload["allocation_id"]
        amount = payload.get("amount")
        if amount is None:
            amount = self.ledger.expenses[expense_id].amount
        ea = self.ledger.allocate_expense(
            expense_id=expense_id,
            allocation_id=allocation_id,
            amount=amount,
        )
        return [ea.id], {"expense_allocation_id": ea.id, "expense_id": expense_id}

    def _approve(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        expense_id = payload["expense_id"]
        approved_by = payload.get("approved_by")
        if not approved_by:
            raise AuthorityError("approve_expense payload requires approved_by from human")
        updated = self.ledger.approve_expense(expense_id, approved_by=approved_by)
        return [expense_id], {"expense_id": expense_id, "state": updated.state.value}

    def _reject(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        # Soft reject: mark via audit only — domain has no REJECT transition helper;
        # we record intent without inventing ledger API.
        expense_id = payload["expense_id"]
        if expense_id not in self.ledger.expenses:
            raise KeyError(expense_id)
        return [expense_id], {
            "expense_id": expense_id,
            "decision": "REJECT",
            "note": payload.get("rationale", ""),
        }

    def _publish_receipt(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        method = payload["attribution_method"]
        if isinstance(method, str):
            method = AttributionMethod(method)
        actor = payload.get("actor") or payload.get("approved_by")
        if not actor:
            raise AuthorityError("publish_use_of_funds_receipt requires actor")
        # Attribution must exist before a canonical receipt can be published.
        self.ledger.attribute_donor_to_expense(
            donor_id=payload["donor_id"],
            donation_id=payload["donation_id"],
            expense_id=payload["expense_id"],
            allocation_id=payload["allocation_id"],
            method=method,
            attributed_amount=Decimal(str(payload["attributed_amount"])),
        )
        receipt = self.ledger.publish_use_of_funds_receipt(
            expense_id=payload["expense_id"],
            donation_id=payload["donation_id"],
            allocation_id=payload["allocation_id"],
            actor=actor,
            created_at=payload.get("created_at"),
        )
        public = receipt_to_public(receipt)
        assert_public_safe(public)
        return [receipt.receipt_id], {
            "receipt_id": receipt.receipt_id,
            "public": public,
        }

    def _send_notification(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        if self.workspace is None:
            raise AuthorityError("send_notification requires a TenantWorkspace")
        preview_id = payload.get("preview_id")
        preview = self.previews.get(preview_id) if preview_id else None
        if preview is None:
            raise AuthorityError("send_notification requires a registered email preview")
        receipt_id = payload["receipt_id"]
        receipt = self.ledger.receipts.get(receipt_id)
        if receipt is None:
            raise KeyError(f"receipt not found: {receipt_id}")
        assert_preview_matches_receipt(preview, receipt)
        if payload.get("content_hash") != preview.content_hash:
            raise AuthorityError("send payload content_hash does not match registered preview")
        if payload.get("receipt_hash") != receipt.receipt_hash:
            raise AuthorityError("send payload receipt_hash does not match ledger receipt")

        # Fixture consent if not already present (operator path would load CRM consent).
        ns = self.workspace.notifications()
        if not self.workspace.consents.get((receipt.donor_id, NotificationChannel.EMAIL.value)):
            ns.record_consent(
                ConsentRecord(
                    donor_id=receipt.donor_id,
                    organization_id=self.ledger.organization.id,
                    channel=NotificationChannel.EMAIL,
                    granted=True,
                    provenance="fixture://consent/email-v1",
                    recorded_at=utc_now_iso(),
                )
            )
            ns.set_preference(
                NotificationPreference(
                    donor_id=receipt.donor_id,
                    organization_id=self.ledger.organization.id,
                    channel=NotificationChannel.EMAIL,
                    enabled=True,
                    topics=("MONEY_USED", "CORRECTION"),
                )
            )

        intent = ns.evaluate_for_use_of_funds(receipt_id, deliver=True)
        deliveries = [
            d
            for d in self.workspace.deliveries.values()
            if d.intent_id == intent.id
        ]
        delivery = deliveries[-1] if deliveries else None
        refs = [intent.id]
        if delivery:
            refs.append(delivery.id)
        return refs, {
            "intent_id": intent.id,
            "intent_status": intent.status.value,
            "delivery_id": delivery.id if delivery else None,
            "delivery_success": delivery.success if delivery else None,
            "provider_receipt": delivery.provider_receipt if delivery else None,
            "preview_id": preview.preview_id,
        }


# ---------------------------------------------------------------------------
# Orchestrated vertical slice
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
) -> ExpenseSliceResult:
    """Run intake → classify → evidence → review → (optional human approve) → ledger.

    When ``approve`` is False, stops at REVIEW_PENDING with a packet and L3 proposal.
    When ``simulation`` is True, CommandExecutor never mutates the ledger.
    When ``send_email`` is True (after publish), composes an email preview and
    requires a *separate* L3 send approval before fixture delivery.
    """
    started = utc_now_iso()
    tenant_id = ledger.organization.id
    ctx = AgentContext(
        tenant_id=tenant_id,
        policy_version=ledger.organization.policy_version,
        facts={
            "default_allocation_id": next(iter(ledger.allocations), None),
        },
    )
    intake = ExpenseIntakeAgent()
    classifier = AllocationClassifierAgent()
    evidence_agent = EvidenceValidatorAgent()
    review = FinanceReviewAgent()
    composer = NotificationComposerAgent()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    executor = LedgerCommandExecutor(
        ledger, simulation=simulation, workspace=workspace
    )

    proposals: list[AgentProposal] = []
    validations: list[ValidationResult] = []
    approvals: list[ApprovalReceipt] = []
    packets: list[FinanceReviewPacket] = []
    receipts: list[UseOfFundsReceipt] = []
    public_previews: list[dict[str, Any]] = []
    email_previews: list[EmailPreview] = []
    delivery_refs: list[dict[str, Any]] = []
    send_approver = communications_approver_id or human_approver_id

    # 1) Intake batch
    batch_cmd = AgentCommand(
        command_type="ingest_expense_batch",
        tenant_id=tenant_id,
        payload={"expenses": expense_rows, "input_refs": ["fixture_batch"]},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    intake_prop = intake.evaluate(ctx, batch_cmd)
    proposals.append(intake_prop)
    v = intake.validate(ctx, intake_prop)
    validations.append(v)
    if not v.ok:
        return _blocked_result(
            tenant_id, started, proposals, validations, approvals, executor, packets, receipts
        )

    for cmd in intake_prop.proposed_commands:
        executor.execute(cmd)  # L2 import — no human approval

    # Resolve expense ids from ledger (or simulation stubs)
    imported_ids: list[str] = []
    for cmd in intake_prop.proposed_commands:
        row = cmd.payload["expense"]
        ext = row["external_source_id"]
        if simulation:
            # No ledger write; use synthetic id for downstream packet only
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
                {"id": e.id, "kind": e.kind, "summary": e.summary, "donor_visible": e.donor_visible}
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

        # 2) Evidence assessment (L0)
        ev_cmd = AgentCommand(
            command_type="assess_evidence",
            tenant_id=tenant_id,
            payload={
                "expense_id": expense_id,
                "evidence": evidence_items,
                "flags": evidence_flags or {},
            },
            required_authority=AuthorityLevel.L0_OBSERVE,
        )
        # L0 evaluate does not propose; call evaluate with observe command
        ev_prop = evidence_agent.evaluate(ctx, ev_cmd)
        proposals.append(ev_prop)
        ev_v = evidence_agent.validate(ctx, ev_prop)
        validations.append(ev_v)
        sufficiency = EvidenceSufficiency.SUFFICIENT
        if ev_prop.warnings:
            try:
                sufficiency = EvidenceSufficiency(ev_prop.warnings[0])
            except ValueError:
                sufficiency = EvidenceSufficiency.PARTIAL
        if not ev_v.ok:
            workflow = WorkflowState.BLOCKED
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
                    evidence_summaries=[e.get("summary", "") for e in evidence_items],
                    classifier_confidence=None,
                    warnings=ev_prop.warnings,
                    contradictions=ev_prop.contradictions,
                    workflow_state=workflow.value,
                    policy_version=ctx.policy_version,
                )
            )
            continue

        # 3) Classification proposal + apply allocation (L1 propose / L2 apply)
        class_cmd = AgentCommand(
            command_type="classify_expense",
            tenant_id=tenant_id,
            payload={
                "expense_id": expense_id,
                "allocation_id": allocation_id,
                "amount": amount,
                "confidence": 0.92,
                "evidence_refs": [e.get("id") for e in evidence_items if e.get("id")],
            },
            required_authority=AuthorityLevel.L1_PROPOSE,
        )
        class_prop = classifier.evaluate(ctx, class_cmd)
        proposals.append(class_prop)
        class_v = classifier.validate(ctx, class_prop)
        validations.append(class_v)
        if not class_v.ok:
            workflow = WorkflowState.NEEDS_INFORMATION
            continue

        for cmd in class_prop.proposed_commands:
            # elevate allocate to L2 reversible execution without human gate
            alloc_cmd = AgentCommand(
                command_type=cmd.command_type,
                tenant_id=cmd.tenant_id,
                payload=cmd.payload,
                required_authority=AuthorityLevel.L2_REVERSIBLE,
                idempotency_key=cmd.idempotency_key,
                expires_at=cmd.expires_at,
            )
            executor.execute(alloc_cmd)

        # 4) Finance review packet + L3 approve proposal
        review_cmd = AgentCommand(
            command_type="assemble_review_packet",
            tenant_id=tenant_id,
            payload={
                "expense_id": expense_id,
                "vendor": vendor,
                "amount": amount,
                "currency": currency,
                "purchase_date": purchase_date,
                "category": category,
                "description": description,
                "allocation_id": allocation_id,
                "evidence_sufficiency": sufficiency.value,
                "evidence_summaries": [e.get("summary", "") for e in evidence_items],
                "confidence": class_prop.confidence,
                "warnings": class_prop.warnings + ev_prop.warnings,
                "contradictions": class_prop.contradictions,
            },
            required_authority=AuthorityLevel.L1_PROPOSE,
        )
        review_prop = review.evaluate(ctx, review_cmd)
        proposals.append(review_prop)
        review_v = review.validate(ctx, review_prop)
        validations.append(review_v)

        packet = FinanceReviewPacket(
            packet_id=review_prop.proposed_commands[0].payload.get("packet_id", _new_id("pkt")),
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
            evidence_summaries=[e.get("summary", "") for e in evidence_items],
            classifier_confidence=class_prop.confidence,
            warnings=review_prop.warnings,
            contradictions=review_prop.contradictions,
            workflow_state=WorkflowState.REVIEW_PENDING.value,
            policy_version=ctx.policy_version,
        )
        packets.append(packet)
        workflow = WorkflowState.REVIEW_PENDING

        if not review_v.ok or not approve:
            continue

        # 5) Human approval (cannot be agent:*)
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

        approve_payload = {
            **l3_cmd.payload,
            "approved_by": human_approver_id,
        }
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
            agent_name=review.name,
            proposal=review_prop,
        )
        if exec_receipt.status == "SUCCEEDED":
            workflow = WorkflowState.LEDGER_COMMITTED
            packet.workflow_state = workflow.value

        # 6) Optional UOF publish (also L3)
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
                pub_cmd, approval=pub_approval, agent_name=review.name
            )
            if pub_exec.status == "SUCCEEDED" and not simulation:
                rid = pub_exec.output_refs[0]
                rec = ledger.receipts[rid]
                receipts.append(rec)
                preview = receipt_to_public(rec)
                assert_public_safe(preview)
                public_previews.append(preview)
                workflow = WorkflowState.PUBLISHED

                # 7) Email preview (projection only) + separate L3 send approval
                if send_email:
                    email_prev = compose_email_from_uof(rec)
                    assert_preview_matches_receipt(email_prev, rec)
                    executor.register_preview(email_prev)
                    email_previews.append(email_prev)
                    compose_cmd = AgentCommand(
                        command_type="compose_send_proposal",
                        tenant_id=tenant_id,
                        payload={"preview": email_prev.to_dict()},
                        required_authority=AuthorityLevel.L1_PROPOSE,
                    )
                    compose_prop = composer.evaluate(ctx, compose_cmd)
                    proposals.append(compose_prop)
                    compose_v = composer.validate(ctx, compose_prop)
                    validations.append(compose_v)
                    if not compose_v.ok:
                        workflow = WorkflowState.NOTIFICATION_PENDING
                        continue
                    workflow = WorkflowState.NOTIFICATION_PENDING
                    send_cmd = compose_prop.proposed_commands[0]
                    if send_approver.startswith("agent:"):
                        raise AuthorityError(
                            "communications approver must not be an agent identity"
                        )
                    # Separation of duties preferred: different human when provided.
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
                        agent_name=composer.name,
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
