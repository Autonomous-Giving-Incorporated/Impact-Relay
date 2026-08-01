"""Batch façade over WorkflowRuntime (PR-M3/M6).

Default is ``runtime`` (PR-M6). Set WORKFLOW_SLICE_FACADE=legacy to force the
linear driver. Easy rollback: export WORKFLOW_SLICE_FACADE=legacy.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.base import AgentContext, build_run_receipt
from impact_relay.agents.expense_workflow import (
    ExpenseSliceResult,
    run_expense_approval_slice_legacy as legacy_run_expense_approval_slice,
)
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import (
    AgentProposal,
    AgentRunStatus,
    ApprovalReceipt,
    ExecutionReceipt,
    ValidationResult,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import UseOfFundsReceipt
from impact_relay.policy import TenantPolicy, default_policy
from impact_relay.public_export import receipt_to_public
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.store_memory import InMemoryWorkflowStore

if TYPE_CHECKING:
    from impact_relay.domain.ledger import Ledger


_DEFAULT_FACADE = "runtime"


def facade_mode() -> str:
    """Return active façade mode. Default runtime (PR-M6); override via env."""
    return os.environ.get("WORKFLOW_SLICE_FACADE", _DEFAULT_FACADE).strip().lower()


def run_expense_approval_slice(
    ledger: "Ledger",
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
    """Dispatch to legacy linear driver or memory runtime façade."""
    mode = facade_mode()
    if mode in ("legacy", "", "0", "false", "off"):
        return legacy_run_expense_approval_slice(
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
    return run_expense_approval_slice_via_runtime(
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


def run_expense_approval_slice_via_runtime(
    ledger: "Ledger",
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
    """Runtime path: batch intake once, then one workflow instance per expense."""
    from impact_relay.agents.executor import LedgerCommandExecutor
    from impact_relay.agents.types import AgentCommand, AuthorityLevel
    from impact_relay.workflows.expense_to_receipt import step_intake

    started = utc_now_iso()
    tenant_id = ledger.organization.id
    policy = tenant_policy or default_policy(tenant_id, ledger.organization.policy_version)
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, workspace)
    runtime = WorkflowRuntime(store, binding)

    ctx = AgentContext(
        tenant_id=tenant_id,
        policy_version=policy.version,
        facts={"default_allocation_id": next(iter(ledger.allocations), None)},
        policy=policy.to_dict(),
    )
    # Shared batch intake on the real ledger
    executor = LedgerCommandExecutor(ledger, simulation=simulation, workspace=workspace)
    intake_out = step_intake(ctx, expense_rows)
    proposals: list[AgentProposal] = list(intake_out.proposals)
    validations: list[ValidationResult] = list(intake_out.validations)
    approvals: list[ApprovalReceipt] = []
    executions: list[ExecutionReceipt] = []
    packets: list[Any] = []
    receipts: list[UseOfFundsReceipt] = []
    public_previews: list[dict[str, Any]] = []
    email_previews: list[Any] = []
    delivery_refs: list[dict[str, Any]] = []
    instance_states: list[tuple[str, WorkflowState]] = []

    if intake_out.step.next_state.value == "BLOCKED":
        from impact_relay.agents.expense_workflow import FinanceReviewPacket
        from impact_relay.agents.types import AgentRunStatus as ARS

        run = build_run_receipt(
            run_id=f"run_{started}",
            tenant_id=tenant_id,
            workflow="expense_to_receipt",
            agent="orchestrator",
            agent_version="0.6.0",
            policy_version=policy.version,
            prompt_version=None,
            input_refs=["expense_batch"],
            input_payload=expense_rows,
            proposals=proposals,
            validations=validations,
            approvals=[],
            executions=[],
            started_at=started,
            status=ARS.BLOCKED,
        )
        return ExpenseSliceResult(
            workflow_state=WorkflowState.BLOCKED,
            packets=[],
            proposals=proposals,
            validations=validations,
            approvals=[],
            executions=[],
            receipts=[],
            run_receipt=run,
        )

    for ex in intake_out.step.commands_to_execute:
        executions.append(executor.execute(ex.command))

    # Map external ids → expense ids
    imported: list[tuple[str, dict[str, Any]]] = []
    for i, row in enumerate(expense_rows):
        ext = row.get("external_source_id") or row.get("id")
        if simulation:
            imported.append((f"sim_{ext}", row))
            continue
        match = next(
            (e for e in ledger.expenses.values() if e.external_source_id == ext),
            None,
        )
        if match:
            imported.append((match.id, row))

    send_approver = communications_approver_id or human_approver_id
    publish_specs = publish_specs or []

    for expense_id, row in imported:
        spec = None
        for s in publish_specs:
            if s.get("expense_id") in (expense_id, None, "*") or s.get("expense_id") is None:
                spec = s
                break
            if s.get("expense_id") == expense_id:
                spec = s
                break
        if publish_specs and spec is None and len(publish_specs) == 1:
            spec = publish_specs[0]

        if human_approver_id.startswith("agent:"):
            raise AuthorityError("human_approver_id must not be an agent identity")

        inst = runtime.start_expense_to_receipt(
            tenant_id=tenant_id,
            expense_row=row,
            publish_spec=spec,
            send_email=send_email and bool(spec),
            simulation=simulation,
            policy=policy,
            business_key=str(row.get("external_source_id") or expense_id),
            pre_imported_expense_id=expense_id,
        )
        if evidence_flags:
            inst.context["evidence_flags"] = dict(evidence_flags)
            runtime.store.update_instance(inst)
        inst = runtime.run_until_wait_or_terminal(
            inst.workflow_id, tenant_id=tenant_id
        )

        # Harvest success receipts from store (parity with linear executor.receipts)
        for (tid, _), rec in getattr(store, "_receipts", {}).items():
            if tid == tenant_id and rec not in executions:
                executions.append(rec)

        # Blocked on evidence: synthesize a review packet (legacy parity)
        if inst.workflow_state == WorkflowState.BLOCKED and not inst.context.get("packet"):
            from impact_relay.agents.expense_workflow import FinanceReviewPacket

            packets.append(
                FinanceReviewPacket(
                    packet_id=f"pkt_blocked_{expense_id[:8]}",
                    tenant_id=tenant_id,
                    expense_id=expense_id,
                    vendor=row.get("vendor", ""),
                    amount=str(row.get("amount", "")),
                    currency=row.get("currency", "USD"),
                    purchase_date=row.get("purchase_date", ""),
                    category=row.get("category", ""),
                    description=row.get("description", ""),
                    proposed_allocation_id=row.get("allocation_id"),
                    evidence_sufficiency=inst.context.get(
                        "evidence_sufficiency", "CONTRADICTORY"
                    ),
                    evidence_summaries=[],
                    classifier_confidence=None,
                    warnings=[inst.context.get("evidence_sufficiency", "BLOCKED")],
                    contradictions=["contradictory evidence"]
                    if (evidence_flags or {}).get("contradictory")
                    else [],
                    workflow_state=WorkflowState.BLOCKED.value,
                    policy_version=policy.version,
                )
            )
            instance_states.append((inst.workflow_id, inst.workflow_state))
            continue

        # Synthetic human approvals at gates
        if approve and inst.workflow_state == WorkflowState.REVIEW_PENDING:
            wait = inst.context.get("wait") or {}
            frozen = wait.get("frozen_command") or {}
            key = frozen.get("idempotency_key") or wait.get("command_idempotency_key")
            if key:
                ar = ApprovalReceipt(
                    approval_id=f"appr_{expense_id[:8]}",
                    tenant_id=tenant_id,
                    proposal_id=wait.get("proposal_id") or "prop_facade",
                    command_idempotency_key=key,
                    decision="APPROVE",
                    approver_id=human_approver_id,
                    approver_role=human_approver_role,
                    approved_at=utc_now_iso(),
                    rationale="facade synthetic approval",
                    policy_version=policy.version,
                )
                approvals.append(ar)
                runtime.signal_approval(
                    tenant_id=tenant_id, workflow_id=inst.workflow_id, approval=ar
                )
                inst = runtime.run_until_wait_or_terminal(
                    inst.workflow_id, tenant_id=tenant_id
                )
                for (tid, _), rec in getattr(store, "_receipts", {}).items():
                    if tid == tenant_id and rec not in executions:
                        executions.append(rec)

        if approve and inst.workflow_state == WorkflowState.PUBLICATION_PENDING:
            wait = inst.context.get("wait") or {}
            frozen = wait.get("frozen_command") or {}
            key = frozen.get("idempotency_key") or wait.get("command_idempotency_key")
            if key:
                ar = ApprovalReceipt(
                    approval_id=f"appr_pub_{expense_id[:8]}",
                    tenant_id=tenant_id,
                    proposal_id=wait.get("proposal_id") or "prop_facade",
                    command_idempotency_key=key,
                    decision="APPROVE",
                    approver_id=human_approver_id,
                    approver_role="communications_approver",
                    approved_at=utc_now_iso(),
                    rationale="facade publish approval",
                    policy_version=policy.version,
                )
                approvals.append(ar)
                runtime.signal_approval(
                    tenant_id=tenant_id, workflow_id=inst.workflow_id, approval=ar
                )
                inst = runtime.run_until_wait_or_terminal(
                    inst.workflow_id, tenant_id=tenant_id
                )
                for (tid, _), rec in getattr(store, "_receipts", {}).items():
                    if tid == tenant_id and rec not in executions:
                        executions.append(rec)

        if approve and inst.workflow_state == WorkflowState.NOTIFICATION_PENDING:
            wait = inst.context.get("wait") or {}
            frozen = wait.get("frozen_command") or {}
            key = frozen.get("idempotency_key") or wait.get("command_idempotency_key")
            if key:
                ar = ApprovalReceipt(
                    approval_id=f"appr_send_{expense_id[:8]}",
                    tenant_id=tenant_id,
                    proposal_id=wait.get("proposal_id") or "prop_facade",
                    command_idempotency_key=key,
                    decision="APPROVE",
                    approver_id=send_approver,
                    approver_role="communications_approver",
                    approved_at=utc_now_iso(),
                    rationale="facade send approval",
                    policy_version=policy.version,
                )
                approvals.append(ar)
                runtime.signal_approval(
                    tenant_id=tenant_id, workflow_id=inst.workflow_id, approval=ar
                )
                inst = runtime.run_until_wait_or_terminal(
                    inst.workflow_id, tenant_id=tenant_id
                )
                for (tid, _), rec in getattr(store, "_receipts", {}).items():
                    if tid == tenant_id and rec not in executions:
                        executions.append(rec)

        # Collect packet
        if inst.context.get("packet"):
            from impact_relay.agents.expense_workflow import FinanceReviewPacket

            p = inst.context["packet"]
            packets.append(
                FinanceReviewPacket(
                    packet_id=p.get("packet_id", "pkt"),
                    tenant_id=tenant_id,
                    expense_id=p.get("expense_id", expense_id),
                    vendor=p.get("vendor", ""),
                    amount=p.get("amount", ""),
                    currency=p.get("currency", "USD"),
                    purchase_date=p.get("purchase_date", ""),
                    category=p.get("category", ""),
                    description=p.get("description", ""),
                    proposed_allocation_id=p.get("proposed_allocation_id"),
                    evidence_sufficiency=p.get("evidence_sufficiency", "SUFFICIENT"),
                    evidence_summaries=p.get("evidence_summaries") or [],
                    classifier_confidence=p.get("classifier_confidence"),
                    warnings=p.get("warnings") or [],
                    contradictions=p.get("contradictions") or [],
                    workflow_state=inst.workflow_state.value,
                    policy_version=policy.version,
                )
            )

        # Receipts from ledger after publish
        for r in ledger.receipts.values():
            if r.expenditure_expense_id == expense_id and r not in receipts:
                receipts.append(r)
                public_previews.append(receipt_to_public(r))

        if inst.context.get("email_preview"):
            email_previews.append(inst.context["email_preview"])
        if inst.context.get("delivery") or inst.workflow_state == WorkflowState.DELIVERED:
            delivery = dict(inst.context.get("delivery") or {})
            # Normalize executor status SUCCEEDED → DELIVERED for slice parity
            status = "DELIVERED"
            if inst.workflow_state == WorkflowState.DELIVERED:
                status = "DELIVERED"
            delivery_refs.append(
                {
                    "receipt_id": delivery.get("receipt_id"),
                    "status": status,
                    "output_refs": delivery.get("output_refs"),
                }
            )

        instance_states.append((inst.workflow_id, inst.workflow_state))

    # K18: last instance state
    workflow_state = (
        instance_states[-1][1] if instance_states else WorkflowState.BLOCKED
    )

    run = build_run_receipt(
        run_id=f"run_{started}",
        tenant_id=tenant_id,
        workflow="expense_to_receipt",
        agent="orchestrator",
        agent_version="0.6.0",
        policy_version=policy.version,
        prompt_version=None,
        input_refs=["expense_batch"],
        input_payload=expense_rows,
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executions,
        started_at=started,
        status=AgentRunStatus.SIMULATED if simulation else None,
    )
    result = ExpenseSliceResult(
        workflow_state=workflow_state,
        packets=packets,
        proposals=proposals,
        validations=validations,
        approvals=approvals,
        executions=executions,
        receipts=receipts,
        run_receipt=run,
        public_previews=public_previews,
        email_previews=email_previews,
        delivery_refs=delivery_refs,
    )
    # Attach instance_states for ops (not on original dataclass — set attr)
    result.instance_states = instance_states  # type: ignore[attr-defined]
    return result
