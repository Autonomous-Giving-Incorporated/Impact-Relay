"""WorkflowRuntime — start, signal, advance (PR-M3 memory path)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from impact_relay.agents.authority import AuthorityError, assert_execution_authorized
from impact_relay.agents.base import AgentContext, CommandExecutor
from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.types import (
    ApprovalReceipt,
    ExecutionReceipt,
    WorkflowState,
    to_jsonable,
    utc_now_iso,
)
from impact_relay.policy import TenantPolicy, default_policy
from impact_relay.workflows.commands import build_executable_command
from impact_relay.workflows.exceptions import (
    WorkflowNotFoundError,
    WorkflowStateError,
    classify_error,
)
from impact_relay.workflows.expense_to_receipt import (
    HandlerBundle,
    step_classify,
    step_compose_send,
    step_evidence,
    step_intake,
    step_review,
)
from impact_relay.workflows.machine import HUMAN_GATE_STATES, default_run_status
from impact_relay.workflows.ports import Clock, ExecutorFactory, LedgerBinding, SystemClock
from impact_relay.workflows.types import (
    AdvanceCommitBundle,
    FrozenProposedCommand,
    SignalConsumeResult,
    SignalType,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowType,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def default_executor_factory(
    ledger_binding: LedgerBinding,
    store: Any = None,
) -> ExecutorFactory:
    """Build executors bound to tenant ledger + optional receipt store.

    ``store`` may be any WorkflowStore (memory or SQL) that implements
    put_execution_receipt / get_execution_receipt.
    """

    def factory(instance: WorkflowInstance) -> CommandExecutor:
        ledger = ledger_binding.for_tenant(instance.tenant_id)
        ws = ledger_binding.workspace(instance.tenant_id)
        ex = LedgerCommandExecutor(
            ledger, simulation=instance.simulation, workspace=ws
        )
        if store is not None:
            ex.receipt_store = store  # type: ignore[attr-defined]
            ex.workflow_id = instance.workflow_id  # type: ignore[attr-defined]
        return ex

    return factory


class WorkflowRuntime:
    def __init__(
        self,
        store: Any,
        ledger_binding: LedgerBinding,
        executor_factory: ExecutorFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.ledger_binding = ledger_binding
        self.clock = clock or SystemClock()
        self.executor_factory = executor_factory or default_executor_factory(
            ledger_binding, store
        )
        self.agents = HandlerBundle()

    def start_expense_to_receipt(
        self,
        *,
        tenant_id: str,
        expense_row: dict[str, Any],
        publish_spec: dict[str, Any] | None = None,
        send_email: bool = False,
        simulation: bool = False,
        policy: TenantPolicy | None = None,
        business_key: str | None = None,
        pre_imported_expense_id: str | None = None,
    ) -> WorkflowInstance:
        """Start one expense workflow. If pre_imported_expense_id set, begin at NORMALIZED."""
        pol = policy or default_policy(tenant_id)
        bk = business_key or str(
            expense_row.get("external_source_id")
            or expense_row.get("id")
            or _new_id("bk")
        )
        now = self.clock.now_iso()
        wid = _new_id("wf")
        ctx_data: dict[str, Any] = {
            "expense_row": expense_row,
            "publish_spec": publish_spec,
            "send_email": send_email,
            "policy": pol.to_dict(),
            "policy_version": pol.version,
            "evidence_flags": {},  # optional; set by façade
        }
        if pre_imported_expense_id:
            state = WorkflowState.NORMALIZED
            ctx_data["expense_id"] = pre_imported_expense_id
        else:
            state = WorkflowState.RECEIVED

        inst = WorkflowInstance(
            workflow_id=wid,
            tenant_id=tenant_id,
            workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
            business_key=bk,
            workflow_state=state,
            run_status=WorkflowRunStatus.PENDING,
            context=ctx_data,
            simulation=simulation,
            next_run_at=now,
            policy_version=pol.version,
            created_at=now,
            updated_at=now,
        )
        self.store.create(inst)
        self.store.append_events(
            tenant_id,
            wid,
            [
                WorkflowEventWrite(
                    event_type=WorkflowEventType.CREATED,
                    payload={"business_key": bk, "state": state.value},
                )
            ],
        )
        return self.store.get(tenant_id, wid)  # type: ignore[return-value]

    def signal_approval(
        self, *, tenant_id: str, workflow_id: str, approval: ApprovalReceipt
    ) -> None:
        if approval.approver_id.startswith("agent:"):
            raise AuthorityError("approver_id must be a human operator identity")
        inst = self.store.get(tenant_id, workflow_id)
        if inst is None:
            raise WorkflowNotFoundError(workflow_id)
        sig = WorkflowSignal(
            signal_id=_new_id("sig"),
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            signal_type=SignalType.APPROVAL,
            payload=to_jsonable(approval),
            created_at=self.clock.now_iso(),
        )
        self.store.enqueue_signal_and_wake(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            signal=sig,
            new_run_status=WorkflowRunStatus.PENDING,
            next_run_at=self.clock.now(),
            clear_lease=True,
        )

    def start_scheduled_digest(
        self,
        *,
        tenant_id: str,
        period_key: str | None = None,
        events_doc: dict[str, Any] | None = None,
        events_path: str | None = None,
        source: str | None = None,
        require_approval: bool = False,
        next_run_at: datetime | str | None = None,
        simulation: bool = False,
        policy: TenantPolicy | None = None,
        business_key: str | None = None,
    ) -> WorkflowInstance:
        """Start scheduled digest job (PR-L2 skeleton).

        ``next_run_at`` controls when the worker may claim (schedule).
        Default: claimable immediately.
        """
        pol = policy or default_policy(tenant_id)
        pk = period_key or self.clock.now_iso()[:10]
        bk = business_key or f"digest:{pk}"
        now = self.clock.now_iso()
        if next_run_at is None:
            nxt = now
        elif isinstance(next_run_at, datetime):
            nxt = next_run_at.replace(microsecond=0).isoformat()
        else:
            nxt = str(next_run_at)
        wid = _new_id("wf_dig")
        ctx_data: dict[str, Any] = {
            "period_key": pk,
            "events_doc": events_doc,
            "events_path": events_path,
            "source": source,
            "require_approval": require_approval,
            "policy": pol.to_dict(),
            "policy_version": pol.version,
        }
        inst = WorkflowInstance(
            workflow_id=wid,
            tenant_id=tenant_id,
            workflow_type=WorkflowType.SCHEDULED_DIGEST,
            business_key=bk,
            workflow_state=WorkflowState.RECEIVED,
            run_status=WorkflowRunStatus.PENDING,
            context=ctx_data,
            simulation=simulation,
            next_run_at=nxt,
            policy_version=pol.version,
            created_at=now,
            updated_at=now,
        )
        self.store.create(inst)
        self.store.append_events(
            tenant_id,
            wid,
            [
                WorkflowEventWrite(
                    event_type=WorkflowEventType.CREATED,
                    payload={
                        "business_key": bk,
                        "period_key": pk,
                        "require_approval": require_approval,
                        "next_run_at": nxt,
                    },
                )
            ],
        )
        return self.store.get(tenant_id, wid)  # type: ignore[return-value]

    def start_correction(
        self,
        *,
        tenant_id: str,
        expense_id: str,
        kind: str = "REVERSE",
        reason: str,
        replacement: dict[str, Any] | None = None,
        splits: list[Any] | None = None,
        simulation: bool = False,
        policy: TenantPolicy | None = None,
        business_key: str | None = None,
    ) -> WorkflowInstance:
        """Start reverse/supersede correction workflow (PR-L1, K15)."""
        pol = policy or default_policy(tenant_id)
        kind_u = kind.upper()
        if kind_u not in ("REVERSE", "SUPERSEDE"):
            raise WorkflowStateError(f"unknown correction kind: {kind}")
        bk = business_key or f"corr:{kind_u.lower()}:{expense_id}"
        now = self.clock.now_iso()
        wid = _new_id("wf_corr")
        ctx_data: dict[str, Any] = {
            "correction_kind": kind_u,
            "expense_id": expense_id,
            "reason": reason,
            "replacement": replacement,
            "splits": splits,
            "policy": pol.to_dict(),
            "policy_version": pol.version,
        }
        inst = WorkflowInstance(
            workflow_id=wid,
            tenant_id=tenant_id,
            workflow_type=WorkflowType.CORRECTION,
            business_key=bk,
            workflow_state=WorkflowState.RECEIVED,
            run_status=WorkflowRunStatus.PENDING,
            context=ctx_data,
            simulation=simulation,
            next_run_at=now,
            policy_version=pol.version,
            created_at=now,
            updated_at=now,
        )
        self.store.create(inst)
        self.store.append_events(
            tenant_id,
            wid,
            [
                WorkflowEventWrite(
                    event_type=WorkflowEventType.CREATED,
                    payload={
                        "business_key": bk,
                        "kind": kind_u,
                        "expense_id": expense_id,
                    },
                )
            ],
        )
        return self.store.get(tenant_id, wid)  # type: ignore[return-value]

    def advance_once(self, instance: WorkflowInstance) -> WorkflowInstance:
        """Advance one step; returns updated instance from store."""
        tenant_id = instance.tenant_id
        workflow_id = instance.workflow_id
        inst = self.store.get(tenant_id, workflow_id)
        if inst is None:
            raise WorkflowNotFoundError(workflow_id)

        executor = self.executor_factory(inst)
        ledger = self.ledger_binding.for_tenant(tenant_id)
        pol = default_policy(tenant_id, inst.policy_version)
        if inst.context.get("policy"):
            # use stamped policy confidence if present
            pass
        ctx = AgentContext(
            tenant_id=tenant_id,
            policy_version=inst.policy_version,
            facts={
                "default_allocation_id": next(iter(ledger.allocations), None),
            },
            policy=inst.context.get("policy") or pol.to_dict(),
        )

        # Correction workflow branch (PR-L1)
        if inst.workflow_type == WorkflowType.CORRECTION:
            return self._advance_correction(inst, executor, ctx, ledger)

        # Scheduled digest branch (PR-L2)
        if inst.workflow_type == WorkflowType.SCHEDULED_DIGEST:
            return self._advance_digest(inst, executor, ctx)

        # Human gate: need signal or repark
        if inst.workflow_state in HUMAN_GATE_STATES:
            return self._advance_human_gate(inst, executor, ctx)

        # Auto steps by business state
        if inst.workflow_state == WorkflowState.RECEIVED:
            return self._advance_received(inst, executor, ctx)
        if inst.workflow_state == WorkflowState.NORMALIZED:
            return self._advance_normalized(inst, executor, ctx, ledger)
        if inst.workflow_state == WorkflowState.CLASSIFICATION_PENDING:
            return self._advance_classification(inst, executor, ctx)
        if inst.workflow_state == WorkflowState.LEDGER_COMMITTED:
            return self._advance_after_ledger(inst, executor, ctx)
        if inst.workflow_state == WorkflowState.PUBLISHED:
            return self._advance_published(inst, executor, ctx)
        if inst.workflow_state == WorkflowState.EVIDENCE_PENDING:
            # treat like normalized evidence re-entry
            return self._advance_normalized(inst, executor, ctx, ledger)

        # Terminal or waiting — no-op complete
        if inst.run_status in (
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.FAILED_TERMINAL,
            WorkflowRunStatus.DEAD_LETTER,
            WorkflowRunStatus.CANCELLED,
        ):
            return inst

        # Unknown intermediate: repark pending
        inst.run_status = WorkflowRunStatus.PENDING
        inst.next_run_at = self.clock.now_iso()
        self.store.update_instance(inst)
        return inst

    def run_until_wait_or_terminal(
        self, workflow_id: str, *, tenant_id: str, max_steps: int = 50
    ) -> WorkflowInstance:
        inst = self.store.get(tenant_id, workflow_id)
        if inst is None:
            raise WorkflowNotFoundError(workflow_id)
        for _ in range(max_steps):
            if inst.run_status in (
                WorkflowRunStatus.WAITING_SIGNAL,
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.FAILED_TERMINAL,
                WorkflowRunStatus.DEAD_LETTER,
                WorkflowRunStatus.CANCELLED,
            ):
                break
            if inst.run_status == WorkflowRunStatus.RETRY_SCHEDULED:
                # For in-process pump, treat as claimable immediately
                inst.run_status = WorkflowRunStatus.PENDING
            inst = self.advance_once(inst)
            # refresh
            inst = self.store.get(tenant_id, workflow_id)  # type: ignore[assignment]
            if inst is None:
                break
        return inst  # type: ignore[return-value]

    def list_blocked(self, tenant_id: str) -> list[WorkflowInstance]:
        """Instances needing operator attention (blocked, DLQ, failed, needs info)."""
        from impact_relay.workflows.ops import list_blocked as _list_cases

        cases = _list_cases(self.store, tenant_id)
        out: list[WorkflowInstance] = []
        for c in cases:
            inst = self.store.get(tenant_id, c.workflow_id)
            if inst is not None:
                out.append(inst)
        return out

    def list_operator_cases(
        self, tenant_id: str, *, filters: list[str] | None = None
    ) -> list[dict[str, Any]]:
        from impact_relay.workflows.ops import list_operator_cases as _list

        return [c.to_dict() for c in _list(self.store, tenant_id, filters=filters)]

    def signal_operator(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        signal_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Generic operator signal (APPROVAL payload preferred as ApprovalReceipt dict)."""
        from impact_relay.workflows.ops import approval_from_dict, signal_approval_and_pump
        from impact_relay.workflows.types import SignalType, WorkflowSignal

        st = signal_type.upper()
        if st == "APPROVAL" or "command_idempotency_key" in payload:
            approval = approval_from_dict(payload, tenant_id=tenant_id)
            signal_approval_and_pump(
                self, tenant_id=tenant_id, workflow_id=workflow_id, approval=approval
            )
            return
        # Non-approval operator signals: enqueue + wake only
        sig = WorkflowSignal(
            signal_id=_new_id("sig"),
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            signal_type=SignalType(st) if st in SignalType.__members__ else SignalType.RESUBMIT,
            payload=payload,
            created_at=self.clock.now_iso(),
        )
        self.store.enqueue_signal_and_wake(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            signal=sig,
            new_run_status=WorkflowRunStatus.PENDING,
            next_run_at=self.clock.now(),
            clear_lease=True,
        )

    # ------------------------------------------------------------------
    # Private advance paths
    # ------------------------------------------------------------------

    def _commit(
        self,
        inst: WorkflowInstance,
        *,
        events: list[WorkflowEventWrite] | None = None,
        receipts: list[ExecutionReceipt] | None = None,
        consume: list[tuple[str, SignalConsumeResult]] | None = None,
    ) -> WorkflowInstance:
        inst.touch(self.clock.now_iso())
        bundle = AdvanceCommitBundle(
            tenant_id=inst.tenant_id,
            workflow_id=inst.workflow_id,
            instance=inst,
            events=events or [],
            execution_receipts=receipts or [],
            consume_signals=consume or [],
        )
        self.store.commit_advance(bundle)
        return self.store.get(inst.tenant_id, inst.workflow_id)  # type: ignore[return-value]

    def _execute_list(
        self, executor: CommandExecutor, executables: list[Any]
    ) -> list[ExecutionReceipt]:
        out: list[ExecutionReceipt] = []
        for ex in executables:
            receipt = executor.execute(
                ex.command,
                approval=ex.approval,
                agent_name=ex.agent_name,
                proposal=ex.proposal,
            )
            out.append(receipt)
            # Also push success into store via executor hook if present
            if (
                hasattr(executor, "receipt_store")
                and receipt.status in ("SUCCEEDED", "SIMULATED", "SKIPPED")
                and hasattr(executor, "workflow_id")
            ):
                try:
                    executor.receipt_store.put_execution_receipt(  # type: ignore[attr-defined]
                        receipt, workflow_id=executor.workflow_id  # type: ignore[attr-defined]
                    )
                except Exception:  # noqa: BLE001
                    pass
        return out

    def _advance_received(
        self, inst: WorkflowInstance, executor: CommandExecutor, ctx: AgentContext
    ) -> WorkflowInstance:
        row = inst.context.get("expense_row") or {}
        out = step_intake(ctx, [row], agents=self.agents, current=WorkflowState.RECEIVED)
        receipts = self._execute_list(executor, out.step.commands_to_execute)
        # resolve expense id
        expense_id = None
        if receipts and receipts[0].output_refs:
            expense_id = receipts[0].output_refs[0]
        if expense_id is None and not inst.simulation:
            ledger = self.ledger_binding.for_tenant(inst.tenant_id)
            ext = row.get("external_source_id")
            match = next(
                (e for e in ledger.expenses.values() if e.external_source_id == ext),
                None,
            )
            if match:
                expense_id = match.id
        if expense_id is None:
            expense_id = f"sim_{row.get('external_source_id', 'x')}"

        inst.context["expense_id"] = expense_id
        inst.workflow_state = out.step.next_state
        if out.step.next_state == WorkflowState.BLOCKED:
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
        else:
            inst.workflow_state = WorkflowState.NORMALIZED
            inst.run_status = WorkflowRunStatus.PENDING
            inst.next_run_at = self.clock.now_iso()
        return self._commit(inst, events=out.step.events, receipts=receipts)

    def _advance_normalized(
        self,
        inst: WorkflowInstance,
        executor: CommandExecutor,
        ctx: AgentContext,
        ledger: Any,
    ) -> WorkflowInstance:
        expense_id = inst.context.get("expense_id")
        row = inst.context.get("expense_row") or {}
        if not expense_id:
            inst.workflow_state = WorkflowState.BLOCKED
            inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
            inst.last_error = "missing expense_id"
            return self._commit(inst)

        if not inst.simulation and expense_id in ledger.expenses:
            exp = ledger.expenses[expense_id]
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
            amount = str(exp.amount)
            vendor, purchase_date = exp.vendor, exp.purchase_date
            category, description, currency = (
                exp.category,
                exp.description,
                exp.currency,
            )
        else:
            evidence_items = list(row.get("evidence") or [])
            amount = row.get("amount")
            vendor = row.get("vendor", "")
            purchase_date = row.get("purchase_date", "")
            category = row.get("category", "")
            description = row.get("description", "")
            currency = row.get("currency", "USD")

        inst.context.update(
            {
                "amount": amount,
                "vendor": vendor,
                "purchase_date": purchase_date,
                "category": category,
                "description": description,
                "currency": currency,
                "evidence_items": evidence_items,
            }
        )
        allocation_id = (
            row.get("allocation_id")
            or row.get("proposed_allocation_id")
            or ctx.facts.get("default_allocation_id")
        )
        inst.context["allocation_id"] = allocation_id

        pol = inst.context.get("policy") or {}
        evid = pol.get("evidence") or {}
        evidence_flags = inst.context.get("evidence_flags") or {}
        out = step_evidence(
            ctx,
            expense_id=expense_id,
            evidence_items=evidence_items,
            evidence_flags=evidence_flags if evidence_flags else None,
            sufficient_kinds=tuple(
                evid.get("sufficient_kinds") or ("invoice", "receipt", "accounting_ref")
            ),
            require_donor_visible=bool(evid.get("require_donor_visible", True)),
            agents=self.agents,
            current=WorkflowState.NORMALIZED,
        )
        inst.context["evidence_sufficiency"] = (
            out.sufficiency.value if out.sufficiency else "MISSING"
        )
        if out.step.next_state != WorkflowState.CLASSIFICATION_PENDING:
            inst.workflow_state = out.step.next_state
            inst.run_status = default_run_status(out.step.next_state)
            return self._commit(inst, events=out.step.events)

        # Continue classify in same advance for efficiency
        class_out = step_classify(
            ctx,
            expense_id=expense_id,
            allocation_id=allocation_id,
            amount=amount,
            evidence_refs=[e.get("id") for e in evidence_items if e.get("id")],
            agents=self.agents,
            current=WorkflowState.CLASSIFICATION_PENDING,
        )
        receipts = self._execute_list(executor, class_out.step.commands_to_execute)
        if class_out.step.next_state != WorkflowState.REVIEW_PENDING:
            inst.workflow_state = class_out.step.next_state
            inst.run_status = default_run_status(class_out.step.next_state)
            return self._commit(
                inst, events=out.step.events + class_out.step.events, receipts=receipts
            )

        # Review packet → WAITING_SIGNAL
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
            evidence_sufficiency=inst.context["evidence_sufficiency"],
            evidence_summaries=[e.get("summary", "") for e in evidence_items],
            confidence=class_out.proposals[0].confidence if class_out.proposals else 0.9,
            warnings=list(class_out.proposals[0].warnings) if class_out.proposals else [],
            contradictions=list(class_out.proposals[0].contradictions)
            if class_out.proposals
            else [],
            agents=self.agents,
            current=WorkflowState.CLASSIFICATION_PENDING,
        )
        if review_out.packet:
            inst.context["packet"] = review_out.packet.to_dict()
            inst.context["proposal_id"] = (
                review_out.proposals[0].proposal_id if review_out.proposals else None
            )
        wait = review_out.step.context_patch.get("wait") or review_out.step.wait_payload
        inst.context["wait"] = wait
        inst.wait_descriptor = {
            "signal_type": "APPROVAL",
            "command_idempotency_key": wait.get("command_idempotency_key")
            or (wait.get("frozen_command") or {}).get("idempotency_key"),
            "proposal_id": wait.get("proposal_id"),
        }
        inst.wait_deadline = (
            str(review_out.step.wait_deadline)
            if review_out.step.wait_deadline
            else None
        )
        inst.workflow_state = WorkflowState.REVIEW_PENDING
        inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
        inst.lease_owner = None
        inst.lease_expires_at = None
        return self._commit(
            inst,
            events=out.step.events + class_out.step.events + review_out.step.events,
            receipts=receipts,
        )

    def _advance_classification(
        self, inst: WorkflowInstance, executor: CommandExecutor, ctx: AgentContext
    ) -> WorkflowInstance:
        # Should rarely park here; route through normalized path fields
        return self._advance_normalized(
            inst, executor, ctx, self.ledger_binding.for_tenant(inst.tenant_id)
        )

    def _advance_human_gate(
        self, inst: WorkflowInstance, executor: CommandExecutor, ctx: AgentContext
    ) -> WorkflowInstance:
        signals = self.store.take_unconsumed_signals(inst.tenant_id, inst.workflow_id)
        wait = inst.context.get("wait") or {}
        # K13 late APPROVE: after timeout, wait is cleared and wait_expired set
        if inst.context.get("wait_expired") and not wait:
            for s in signals:
                ar = s.approval_receipt()
                if ar is None:
                    continue
                expired = inst.context.get("expired_wait") or {}
                expired_key = expired.get("command_idempotency_key") or (
                    (expired.get("frozen_command") or {}).get("idempotency_key")
                )
                prior = (inst.wait_descriptor or {}).get(
                    "prior_command_idempotency_key"
                )
                if ar.command_idempotency_key in (
                    expired_key,
                    prior,
                ) or ar.decision == "APPROVE":
                    # Reject late APPROVE on expired frozen key
                    return self._commit(
                        inst,
                        events=[
                            WorkflowEventWrite(
                                event_type=WorkflowEventType.ERROR,
                                payload={
                                    "error": "late_approve_after_timeout",
                                    "key": ar.command_idempotency_key,
                                },
                            )
                        ],
                        consume=[
                            (s.signal_id, SignalConsumeResult.REJECTED_INVALID)
                        ],
                    )
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            inst.lease_owner = None
            inst.lease_expires_at = None
            return self._commit(inst)

        want_key = wait.get("command_idempotency_key") or (
            (wait.get("frozen_command") or {}).get("idempotency_key")
        )
        matching = []
        for s in signals:
            if s.signal_type != SignalType.APPROVAL:
                continue
            ar = s.approval_receipt()
            if ar is None:
                continue
            if want_key and ar.command_idempotency_key != want_key:
                continue
            matching.append((s, ar))

        if not matching:
            # repark — no attempt bump
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            inst.lease_owner = None
            inst.lease_expires_at = None
            return self._commit(inst)

        signal, approval = matching[0]
        frozen_raw = wait.get("frozen_command")
        if not frozen_raw:
            # Invalid wait context
            self.store.mark_signal_consumed(
                inst.tenant_id, signal.signal_id, SignalConsumeResult.REJECTED_INVALID.value
            )
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            return self._commit(
                inst,
                consume=[(signal.signal_id, SignalConsumeResult.REJECTED_INVALID)],
            )

        frozen = FrozenProposedCommand.from_dict(frozen_raw)
        try:
            cmd = build_executable_command(frozen, approval)
            assert_execution_authorized(
                cmd, approval, agent_name=frozen.agent_name
            )
        except AuthorityError as exc:
            inst.last_error = str(exc)
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            return self._commit(
                inst,
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.ERROR,
                        payload={"error": str(exc)},
                    )
                ],
                consume=[(signal.signal_id, SignalConsumeResult.REJECTED_INVALID)],
            )

        if approval.decision == "REJECT":
            inst.workflow_state = WorkflowState.REJECTED
            inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
            return self._commit(
                inst,
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.APPROVAL,
                        payload={"decision": "REJECT"},
                    )
                ],
                consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
            )
        if approval.decision in ("REQUEST_INFORMATION", "EDIT"):
            inst.workflow_state = WorkflowState.NEEDS_INFORMATION
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            return self._commit(
                inst,
                consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
            )

        # APPROVE path
        # Re-register email preview if send
        if cmd.command_type == "send_notification" and isinstance(
            executor, LedgerCommandExecutor
        ):
            preview = inst.context.get("email_preview")
            if preview:
                from impact_relay.agents.notification_composer import EmailPreview

                try:
                    executor.register_preview(EmailPreview(**preview))
                except TypeError:
                    # partial dict
                    pass

        try:
            receipt = executor.execute(
                cmd, approval=approval, agent_name=frozen.agent_name
            )
        except Exception as exc:  # noqa: BLE001
            classified = classify_error(exc)
            if classified.retryable:
                inst.attempt_count += 1
                inst.run_status = WorkflowRunStatus.RETRY_SCHEDULED
                inst.next_run_at = (
                    self.clock.now() + timedelta(seconds=2**inst.attempt_count)
                ).isoformat()
                inst.last_error = str(exc)
                # do not consume signal
                return self._commit(inst)
            inst.last_error = str(exc)
            inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
            return self._commit(
                inst,
                consume=[(signal.signal_id, SignalConsumeResult.FAILED_TERMINAL)],
            )

        if receipt.status == "FAILED":
            classified = classify_error(Exception(receipt.error or "failed"))
            if classified.retryable:
                inst.attempt_count += 1
                inst.run_status = WorkflowRunStatus.RETRY_SCHEDULED
                inst.next_run_at = self.clock.now_iso()
                inst.last_error = receipt.error
                return self._commit(inst)
            inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
            inst.last_error = receipt.error
            return self._commit(
                inst,
                receipts=[],  # never store FAILED
                consume=[(signal.signal_id, SignalConsumeResult.FAILED_TERMINAL)],
            )

        # Success — transition by command type
        if cmd.command_type == "approve_expense":
            inst.workflow_state = WorkflowState.LEDGER_COMMITTED
            inst.run_status = WorkflowRunStatus.PENDING
            inst.next_run_at = self.clock.now_iso()
        elif cmd.command_type in ("reverse_expense", "supersede_expense"):
            inst.workflow_state = WorkflowState.LEDGER_COMMITTED
            inst.run_status = WorkflowRunStatus.PENDING
            inst.next_run_at = self.clock.now_iso()
            inst.context["correction_result"] = {
                "command_type": cmd.command_type,
                "output_refs": list(receipt.output_refs),
                "status": receipt.status,
            }
        elif cmd.command_type == "publish_use_of_funds_receipt":
            inst.workflow_state = WorkflowState.PUBLISHED
            if inst.context.get("send_email"):
                inst.run_status = WorkflowRunStatus.PENDING
                inst.next_run_at = self.clock.now_iso()
            else:
                inst.run_status = WorkflowRunStatus.COMPLETED
        elif cmd.command_type == "send_notification":
            inst.workflow_state = WorkflowState.DELIVERED
            inst.run_status = WorkflowRunStatus.COMPLETED
            inst.context["delivery"] = {
                "output_refs": receipt.output_refs,
                "status": receipt.status,
            }
        else:
            inst.run_status = WorkflowRunStatus.PENDING
            inst.next_run_at = self.clock.now_iso()

        inst.context.pop("wait", None)
        inst.wait_descriptor = None
        inst.wait_deadline = None
        inst.lease_owner = None
        inst.lease_expires_at = None
        return self._commit(
            inst,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.EXECUTION,
                    payload={
                        "command_type": cmd.command_type,
                        "status": receipt.status,
                        "refs": receipt.output_refs,
                    },
                ),
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": inst.workflow_state.value},
                ),
            ],
            receipts=[receipt]
            if receipt.status in ("SUCCEEDED", "SIMULATED", "SKIPPED")
            else [],
            consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
        )

    def _advance_digest(
        self,
        inst: WorkflowInstance,
        executor: CommandExecutor,
        ctx: AgentContext,
    ) -> WorkflowInstance:
        """Scheduled digest (PR-L2): assemble → privacy → optional ack → complete."""
        from impact_relay.workflows.scheduled_digest import (
            step_assemble_and_privacy,
            step_complete_digest,
        )

        if inst.run_status in (
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.FAILED_TERMINAL,
            WorkflowRunStatus.DEAD_LETTER,
            WorkflowRunStatus.CANCELLED,
        ):
            return inst

        if inst.workflow_state == WorkflowState.PUBLICATION_PENDING:
            return self._advance_digest_approval(inst)

        if inst.workflow_state == WorkflowState.RECEIVED:
            out = step_assemble_and_privacy(
                events_doc=inst.context.get("events_doc"),
                events_path=inst.context.get("events_path"),
                source=inst.context.get("source"),
                require_approval=bool(inst.context.get("require_approval")),
                period_key=inst.context.get("period_key"),
                current=WorkflowState.RECEIVED,
            )
            # Fill tenant on frozen ack command
            wait = (out.context_patch or {}).get("wait")
            if wait and isinstance(wait.get("frozen_command"), dict):
                wait["frozen_command"]["tenant_id"] = inst.tenant_id
            inst.context.update(out.context_patch or {})
            if wait:
                inst.context["wait"] = wait
                inst.wait_descriptor = {
                    "signal_type": "APPROVAL",
                    "command_idempotency_key": wait.get("command_idempotency_key"),
                    "digest_ack": True,
                }
            inst.wait_deadline = str(out.wait_deadline) if out.wait_deadline else None
            inst.workflow_state = out.next_state
            inst.run_status = out.run_status
            inst.lease_owner = None
            inst.lease_expires_at = None
            if out.run_status == WorkflowRunStatus.PENDING:
                inst.next_run_at = self.clock.now_iso()
            return self._commit(inst, events=out.events)

        if inst.workflow_state == WorkflowState.PUBLISHED:
            out = step_complete_digest(current=WorkflowState.PUBLISHED)
            inst.workflow_state = out.next_state
            inst.run_status = out.run_status
            return self._commit(inst, events=out.events)

        inst.run_status = WorkflowRunStatus.PENDING
        inst.next_run_at = self.clock.now_iso()
        return self._commit(inst)

    def _advance_digest_approval(self, inst: WorkflowInstance) -> WorkflowInstance:
        """Human ack for public digest publish (no money command)."""
        signals = self.store.take_unconsumed_signals(inst.tenant_id, inst.workflow_id)
        wait = inst.context.get("wait") or {}
        want_key = wait.get("command_idempotency_key")
        matching = []
        for s in signals:
            if s.signal_type != SignalType.APPROVAL:
                continue
            ar = s.approval_receipt()
            if ar is None:
                continue
            if want_key and ar.command_idempotency_key != want_key:
                continue
            matching.append((s, ar))

        if not matching:
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            inst.lease_owner = None
            inst.lease_expires_at = None
            return self._commit(inst)

        signal, approval = matching[0]
        if approval.approver_id.startswith("agent:"):
            inst.last_error = "approver_id must be a human operator identity"
            return self._commit(
                inst,
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.ERROR,
                        payload={"error": "agent_approver_rejected"},
                    )
                ],
                consume=[(signal.signal_id, SignalConsumeResult.REJECTED_INVALID)],
            )
        if approval.decision == "REJECT":
            inst.workflow_state = WorkflowState.REJECTED
            inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
            inst.context.pop("wait", None)
            return self._commit(
                inst,
                consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
            )
        if approval.decision != "APPROVE":
            inst.workflow_state = WorkflowState.NEEDS_INFORMATION
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            return self._commit(
                inst,
                consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
            )

        # APPROVE — publish path without ledger mutation
        inst.workflow_state = WorkflowState.PUBLISHED
        inst.run_status = WorkflowRunStatus.PENDING
        inst.next_run_at = self.clock.now_iso()
        inst.context.pop("wait", None)
        inst.wait_descriptor = None
        inst.wait_deadline = None
        inst.context["digest_approved_by"] = approval.approver_id
        inst.lease_owner = None
        inst.lease_expires_at = None
        return self._commit(
            inst,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.APPROVAL,
                    payload={"decision": "APPROVE", "approver_id": approval.approver_id},
                ),
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": WorkflowState.PUBLISHED.value},
                ),
            ],
            consume=[(signal.signal_id, SignalConsumeResult.ACCEPTED)],
        )

    def _advance_correction(
        self,
        inst: WorkflowInstance,
        executor: CommandExecutor,
        ctx: AgentContext,
        ledger: Any,
    ) -> WorkflowInstance:
        """Correction workflow (PR-L1): propose L3 reverse/supersede → wait → complete."""
        from impact_relay.workflows.corrections import (
            step_after_ledger_correction,
            step_propose_correction,
        )

        if inst.run_status in (
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.FAILED_TERMINAL,
            WorkflowRunStatus.DEAD_LETTER,
            WorkflowRunStatus.CANCELLED,
        ):
            return inst

        if inst.workflow_state in HUMAN_GATE_STATES:
            return self._advance_human_gate(inst, executor, ctx)

        if inst.workflow_state == WorkflowState.RECEIVED:
            kind = str(inst.context.get("correction_kind") or "REVERSE").upper()
            expense_id = inst.context.get("expense_id")
            reason = inst.context.get("reason") or ""
            if not expense_id or not reason:
                inst.workflow_state = WorkflowState.NEEDS_INFORMATION
                inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
                inst.last_error = "correction requires expense_id and reason"
                return self._commit(inst)
            if not inst.simulation and expense_id not in ledger.expenses:
                inst.workflow_state = WorkflowState.BLOCKED
                inst.run_status = WorkflowRunStatus.FAILED_TERMINAL
                inst.last_error = f"expense not found: {expense_id}"
                return self._commit(inst)

            out = step_propose_correction(
                tenant_id=inst.tenant_id,
                kind=kind,  # type: ignore[arg-type]
                expense_id=str(expense_id),
                reason=str(reason),
                replacement=inst.context.get("replacement"),
                splits=inst.context.get("splits"),
                current=WorkflowState.RECEIVED,
            )
            inst.context.update(out.context_patch)
            wait = out.context_patch.get("wait") or out.wait_payload
            if wait:
                inst.context["wait"] = wait
                inst.wait_descriptor = {
                    "signal_type": "APPROVAL",
                    "command_idempotency_key": wait.get("command_idempotency_key")
                    or (wait.get("frozen_command") or {}).get("idempotency_key"),
                    "proposal_id": wait.get("proposal_id"),
                }
            inst.wait_deadline = (
                str(out.wait_deadline) if out.wait_deadline else None
            )
            inst.workflow_state = out.next_state
            inst.run_status = out.run_status
            inst.lease_owner = None
            inst.lease_expires_at = None
            return self._commit(inst, events=out.events)

        if inst.workflow_state == WorkflowState.LEDGER_COMMITTED:
            out = step_after_ledger_correction(current=WorkflowState.LEDGER_COMMITTED)
            inst.workflow_state = out.next_state
            inst.run_status = out.run_status
            return self._commit(inst, events=out.events)

        if inst.workflow_state == WorkflowState.NEEDS_INFORMATION:
            # Operator must resubmit via new start or RESUBMIT signal — repark
            inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
            inst.lease_owner = None
            inst.lease_expires_at = None
            return self._commit(inst)

        # Unknown — repark
        inst.run_status = WorkflowRunStatus.PENDING
        inst.next_run_at = self.clock.now_iso()
        return self._commit(inst)

    def _advance_after_ledger(
        self, inst: WorkflowInstance, executor: CommandExecutor, ctx: AgentContext
    ) -> WorkflowInstance:
        """After LEDGER_COMMITTED: optional publish or complete."""
        # Correction workflows complete via _advance_correction (safety net)
        if inst.workflow_type == WorkflowType.CORRECTION:
            return self._advance_correction(inst, executor, ctx, self.ledger_binding.for_tenant(inst.tenant_id))

        spec = inst.context.get("publish_spec")
        if not spec:
            inst.run_status = WorkflowRunStatus.COMPLETED
            return self._commit(inst)

        expense_id = inst.context.get("expense_id")
        pub_payload = {
            "donor_id": spec["donor_id"],
            "donation_id": spec["donation_id"],
            "expense_id": expense_id,
            "allocation_id": spec.get("allocation_id")
            or inst.context.get("allocation_id"),
            "attribution_method": spec["attribution_method"],
            "attributed_amount": spec["attributed_amount"],
            "created_at": spec.get("created_at"),
            "actor": spec.get("actor") or "finance.operator@fixture",
        }
        from impact_relay.agents.types import AgentCommand, AuthorityLevel

        pub_cmd = AgentCommand(
            command_type="publish_use_of_funds_receipt",
            tenant_id=inst.tenant_id,
            payload=pub_payload,
            required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            idempotency_key=f"publish:{expense_id}:{spec['donation_id']}",
        )
        frozen = FrozenProposedCommand(
            command_type=pub_cmd.command_type,
            tenant_id=pub_cmd.tenant_id,
            payload=dict(pub_cmd.payload),
            idempotency_key=pub_cmd.idempotency_key,
            expires_at=pub_cmd.expires_at,
            required_authority="L3",
            proposal_id=inst.context.get("proposal_id") or _new_id("prop"),
            agent_name="finance_review",
        )
        inst.context["wait"] = {
            "signal_type": "APPROVAL",
            "command_idempotency_key": frozen.idempotency_key,
            "frozen_command": frozen.to_dict(),
            "proposal_id": frozen.proposal_id,
        }
        inst.wait_descriptor = {
            "signal_type": "APPROVAL",
            "command_idempotency_key": frozen.idempotency_key,
        }
        inst.workflow_state = WorkflowState.PUBLICATION_PENDING
        inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
        inst.wait_deadline = (
            self.clock.now() + timedelta(days=7)
        ).isoformat()
        return self._commit(
            inst,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": "PUBLICATION_PENDING", "wait": "APPROVAL"},
                )
            ],
        )

    def _advance_published(
        self, inst: WorkflowInstance, executor: CommandExecutor, ctx: AgentContext
    ) -> WorkflowInstance:
        if not inst.context.get("send_email"):
            inst.run_status = WorkflowRunStatus.COMPLETED
            return self._commit(inst)

        # Need email preview from receipt
        ledger = self.ledger_binding.for_tenant(inst.tenant_id)
        rid = None
        # last published receipt for expense
        expense_id = inst.context.get("expense_id")
        for r in ledger.receipts.values():
            if r.expenditure_expense_id == expense_id:
                rid = r.receipt_id
        if rid is None or rid not in ledger.receipts:
            inst.run_status = WorkflowRunStatus.COMPLETED
            return self._commit(inst)

        from impact_relay.agents.notification_composer import (
            assert_preview_matches_receipt,
            compose_email_from_uof,
        )

        rec = ledger.receipts[rid]
        email_prev = compose_email_from_uof(rec)
        assert_preview_matches_receipt(email_prev, rec)
        inst.context["email_preview"] = email_prev.to_dict()
        if isinstance(executor, LedgerCommandExecutor):
            executor.register_preview(email_prev)

        send_out = step_compose_send(
            ctx,
            preview_dict=email_prev.to_dict(),
            agents=self.agents,
            current=WorkflowState.PUBLISHED,
        )
        wait = send_out.step.context_patch.get("wait") or send_out.step.wait_payload
        inst.context["wait"] = wait
        inst.wait_descriptor = {
            "signal_type": "APPROVAL",
            "command_idempotency_key": wait.get("command_idempotency_key")
            or (wait.get("frozen_command") or {}).get("idempotency_key"),
        }
        inst.workflow_state = WorkflowState.NOTIFICATION_PENDING
        inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
        return self._commit(inst, events=send_out.step.events)
