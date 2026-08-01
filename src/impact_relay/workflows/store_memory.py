"""In-memory WorkflowStore for v0.6 T1 (PR-M3).

Survives in-process only. Claim never returns pure WAITING_SIGNAL.
FAILED execution receipts are never stored in the idempotency index.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from impact_relay.agents.types import ExecutionReceipt, WorkflowState, utc_now_iso
from impact_relay.workflows.exceptions import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowStateError,
)
from impact_relay.workflows.types import (
    CLAIMABLE_RUN_STATUSES,
    AdvanceCommitBundle,
    SignalConsumeResult,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowType,
)

# Human-gate states eligible for K13 approval timeout.
_TIMEOUT_GATE_STATES = frozenset(
    {
        WorkflowState.REVIEW_PENDING,
        WorkflowState.PUBLICATION_PENDING,
        WorkflowState.NOTIFICATION_PENDING,
    }
)


def _parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # Handle trailing Z
    s = value.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


class InMemoryWorkflowStore:
    """Thread-safe process-local store implementing WorkflowStore."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._instances: dict[str, WorkflowInstance] = {}  # workflow_id
        self._by_business: dict[tuple[str, str, str], str] = {}
        self._events: dict[str, list[WorkflowEvent]] = {}
        self._signals: dict[str, list[WorkflowSignal]] = {}  # workflow_id
        # (tenant_id, idempotency_key) -> ExecutionReceipt — success/sim/skip only
        self._receipts: dict[tuple[str, str], ExecutionReceipt] = {}
        self._receipt_workflow: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # WorkflowStore
    # ------------------------------------------------------------------

    def create(self, instance: WorkflowInstance) -> None:
        with self._lock:
            if instance.workflow_id in self._instances:
                raise WorkflowConflictError(
                    f"workflow already exists: {instance.workflow_id}"
                )
            bkey = (
                instance.tenant_id,
                instance.workflow_type.value
                if isinstance(instance.workflow_type, WorkflowType)
                else str(instance.workflow_type),
                instance.business_key,
            )
            if bkey in self._by_business:
                raise WorkflowConflictError(
                    f"business_key already used: {instance.business_key}"
                )
            self._instances[instance.workflow_id] = instance
            self._by_business[bkey] = instance.workflow_id
            self._events.setdefault(instance.workflow_id, [])
            self._signals.setdefault(instance.workflow_id, [])

    def get(self, tenant_id: str, workflow_id: str) -> WorkflowInstance | None:
        with self._lock:
            inst = self._instances.get(workflow_id)
            if inst is None or inst.tenant_id != tenant_id:
                return None
            return inst

    def get_by_business_key(
        self, tenant_id: str, workflow_type: WorkflowType | str, business_key: str
    ) -> WorkflowInstance | None:
        wt = (
            workflow_type.value
            if isinstance(workflow_type, WorkflowType)
            else str(workflow_type)
        )
        with self._lock:
            wid = self._by_business.get((tenant_id, wt, business_key))
            if not wid:
                return None
            return self._instances.get(wid)

    def list(
        self,
        tenant_id: str,
        *,
        workflow_state: list[str] | None = None,
        run_status: list[str] | None = None,
        limit: int = 100,
    ) -> list[WorkflowInstance]:
        with self._lock:
            out: list[WorkflowInstance] = []
            for inst in self._instances.values():
                if inst.tenant_id != tenant_id:
                    continue
                if workflow_state and inst.workflow_state.value not in workflow_state:
                    continue
                if run_status and inst.run_status.value not in run_status:
                    continue
                out.append(inst)
                if len(out) >= limit:
                    break
            return out

    def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_ttl: timedelta,
    ) -> list[WorkflowInstance]:
        """Canonical claim: PENDING | RETRY_SCHEDULED | expired RUNNING. Never WAITING_SIGNAL."""
        with self._lock:
            now_iso = now.replace(microsecond=0).isoformat()
            lease_exp = (now + lease_ttl).replace(microsecond=0).isoformat()
            candidates: list[WorkflowInstance] = []
            for inst in self._instances.values():
                next_run = _parse_iso(inst.next_run_at) or datetime.min.replace(
                    tzinfo=timezone.utc
                )
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)
                now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                if next_run > now_aware:
                    continue
                if inst.run_status in CLAIMABLE_RUN_STATUSES:
                    candidates.append(inst)
                elif inst.run_status == WorkflowRunStatus.RUNNING:
                    exp = _parse_iso(inst.lease_expires_at)
                    if exp is not None and exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp is not None and exp < now_aware:
                        candidates.append(inst)
                # WAITING_SIGNAL and terminals: never
            candidates.sort(key=lambda i: i.next_run_at or "")
            claimed: list[WorkflowInstance] = []
            for inst in candidates[:limit]:
                inst.run_status = WorkflowRunStatus.RUNNING
                inst.lease_owner = worker_id
                inst.lease_expires_at = lease_exp
                inst.touch(now_iso)
                claimed.append(inst)
            return claimed

    def update_instance(self, instance: WorkflowInstance) -> None:
        with self._lock:
            existing = self._instances.get(instance.workflow_id)
            if existing is None or existing.tenant_id != instance.tenant_id:
                raise WorkflowNotFoundError(instance.workflow_id)
            self._instances[instance.workflow_id] = instance

    def append_events(
        self,
        tenant_id: str,
        workflow_id: str,
        events: list[WorkflowEventWrite] | list[WorkflowEvent],
    ) -> None:
        with self._lock:
            inst = self._instances.get(workflow_id)
            if inst is None or inst.tenant_id != tenant_id:
                raise WorkflowNotFoundError(workflow_id)
            store = self._events.setdefault(workflow_id, [])
            for ev in events:
                if isinstance(ev, WorkflowEvent):
                    store.append(ev)
                    inst.event_seq = max(inst.event_seq, ev.seq)
                    continue
                inst.event_seq += 1
                store.append(
                    WorkflowEvent(
                        event_id=f"evt_{workflow_id}_{inst.event_seq}",
                        workflow_id=workflow_id,
                        tenant_id=tenant_id,
                        seq=inst.event_seq,
                        event_type=ev.event_type
                        if isinstance(ev.event_type, WorkflowEventType)
                        else WorkflowEventType(str(ev.event_type)),
                        payload=dict(ev.payload),
                        at=ev.at or utc_now_iso(),
                    )
                )
            inst.touch()

    def list_events(self, tenant_id: str, workflow_id: str) -> list[WorkflowEvent]:
        with self._lock:
            inst = self._instances.get(workflow_id)
            if inst is None or inst.tenant_id != tenant_id:
                return []
            return list(self._events.get(workflow_id, []))

    def enqueue_signal_and_wake(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        signal: WorkflowSignal,
        new_run_status: WorkflowRunStatus,
        next_run_at: datetime | str,
        clear_lease: bool,
    ) -> None:
        with self._lock:
            inst = self._instances.get(workflow_id)
            if inst is None or inst.tenant_id != tenant_id:
                raise WorkflowNotFoundError(workflow_id)
            if inst.run_status not in (
                WorkflowRunStatus.WAITING_SIGNAL,
                WorkflowRunStatus.PENDING,  # re-signal while pending with unconsumed
            ):
                # Allow signal while WAITING or after wake before claim
                if inst.run_status not in (
                    WorkflowRunStatus.WAITING_SIGNAL,
                    WorkflowRunStatus.PENDING,
                    WorkflowRunStatus.RETRY_SCHEDULED,
                ):
                    raise WorkflowStateError(
                        f"workflow not accepting signals in {inst.run_status.value}"
                    )
            self._signals.setdefault(workflow_id, []).append(signal)
            inst.run_status = new_run_status
            if isinstance(next_run_at, datetime):
                inst.next_run_at = next_run_at.replace(microsecond=0).isoformat()
            else:
                inst.next_run_at = str(next_run_at)
            if clear_lease:
                inst.lease_owner = None
                inst.lease_expires_at = None
            inst.touch()

    def take_unconsumed_signals(
        self, tenant_id: str, workflow_id: str
    ) -> list[WorkflowSignal]:
        with self._lock:
            inst = self._instances.get(workflow_id)
            if inst is None or inst.tenant_id != tenant_id:
                return []
            return [s for s in self._signals.get(workflow_id, []) if not s.consumed]

    def mark_signal_consumed(
        self, tenant_id: str, signal_id: str, result: str
    ) -> None:
        with self._lock:
            for signals in self._signals.values():
                for i, s in enumerate(signals):
                    if s.signal_id == signal_id and s.tenant_id == tenant_id:
                        signals[i] = WorkflowSignal(
                            signal_id=s.signal_id,
                            workflow_id=s.workflow_id,
                            tenant_id=s.tenant_id,
                            signal_type=s.signal_type,
                            payload=s.payload,
                            created_at=s.created_at,
                            consumed=True,
                            consume_result=result,
                        )
                        return

    def put_execution_receipt(
        self, receipt: ExecutionReceipt, *, workflow_id: str
    ) -> None:
        if receipt.status not in ("SUCCEEDED", "SIMULATED", "SKIPPED"):
            raise WorkflowStateError(
                f"must not store FAILED receipt for idempotency: {receipt.status}"
            )
        with self._lock:
            key = (receipt.tenant_id, receipt.idempotency_key)
            self._receipts[key] = receipt
            self._receipt_workflow[key] = workflow_id

    def get_execution_receipt(
        self, tenant_id: str, idempotency_key: str
    ) -> ExecutionReceipt | None:
        with self._lock:
            return self._receipts.get((tenant_id, idempotency_key))

    def commit_advance(self, bundle: AdvanceCommitBundle) -> None:
        """Atomic unit: receipts + events + instance + signal consume."""
        with self._lock:
            inst = self._instances.get(bundle.workflow_id)
            if inst is None or inst.tenant_id != bundle.tenant_id:
                raise WorkflowNotFoundError(bundle.workflow_id)

            for receipt in bundle.execution_receipts:
                if receipt.status not in ("SUCCEEDED", "SIMULATED", "SKIPPED"):
                    continue  # never store FAILED
                key = (receipt.tenant_id, receipt.idempotency_key)
                self._receipts[key] = receipt
                self._receipt_workflow[key] = bundle.workflow_id

            store = self._events.setdefault(bundle.workflow_id, [])
            cursor = bundle.instance
            # Continue seq from stored instance history
            if store:
                cursor.event_seq = max(cursor.event_seq, store[-1].seq)
            for ev in bundle.events:
                if isinstance(ev, WorkflowEvent):
                    store.append(ev)
                    cursor.event_seq = max(cursor.event_seq, ev.seq)
                    continue
                cursor.event_seq += 1
                store.append(
                    WorkflowEvent(
                        event_id=f"evt_{bundle.workflow_id}_{cursor.event_seq}",
                        workflow_id=bundle.workflow_id,
                        tenant_id=bundle.tenant_id,
                        seq=cursor.event_seq,
                        event_type=ev.event_type
                        if isinstance(ev.event_type, WorkflowEventType)
                        else WorkflowEventType(str(ev.event_type)),
                        payload=dict(ev.payload),
                        at=ev.at or utc_now_iso(),
                    )
                )

            cursor.touch()
            self._instances[bundle.workflow_id] = cursor

            for signal_id, result in bundle.consume_signals:
                res = (
                    result.value
                    if isinstance(result, SignalConsumeResult)
                    else str(result)
                )
                for i, s in enumerate(self._signals.get(bundle.workflow_id, [])):
                    if s.signal_id == signal_id:
                        self._signals[bundle.workflow_id][i] = WorkflowSignal(
                            signal_id=s.signal_id,
                            workflow_id=s.workflow_id,
                            tenant_id=s.tenant_id,
                            signal_type=s.signal_type,
                            payload=s.payload,
                            created_at=s.created_at,
                            consumed=True,
                            consume_result=res,
                        )

    def sweep_approval_timeouts(self, now: datetime | None = None) -> list[str]:
        """K13: overdue WAITING_SIGNAL human gates → NEEDS_INFORMATION.

        Idempotent: only rows with wait_deadline set and not yet timeout_applied_at.
        Clears wait_deadline so the sweeper never re-fires on the same wait cycle.
        Moves expired wait into context.expired_wait and clears context.wait
        so late APPROVE cannot bind the frozen L3 key.
        Returns list of workflow_ids timed out.
        """
        now = now or datetime.now(timezone.utc)
        now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        now_iso = now_aware.replace(microsecond=0).isoformat()
        timed_out: list[str] = []

        with self._lock:
            for inst in list(self._instances.values()):
                if inst.run_status != WorkflowRunStatus.WAITING_SIGNAL:
                    continue
                if inst.workflow_state not in _TIMEOUT_GATE_STATES:
                    continue
                if not inst.wait_deadline:
                    continue
                if inst.timeout_applied_at:
                    continue  # already swept
                deadline = _parse_iso(inst.wait_deadline)
                if deadline is None:
                    continue
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if deadline >= now_aware:
                    continue

                prior_wait = dict(inst.context.get("wait") or {})
                prior_key = (
                    (inst.wait_descriptor or {}).get("command_idempotency_key")
                    or prior_wait.get("command_idempotency_key")
                    or (prior_wait.get("frozen_command") or {}).get("idempotency_key")
                )
                prior_proposal = (inst.wait_descriptor or {}).get("proposal_id") or prior_wait.get(
                    "proposal_id"
                )

                inst.workflow_state = WorkflowState.NEEDS_INFORMATION
                inst.run_status = WorkflowRunStatus.WAITING_SIGNAL
                inst.last_error = "approval_timeout"
                inst.wait_deadline = None
                inst.timeout_applied_at = now_iso
                inst.wait_descriptor = {
                    "signal_type": "RESUBMIT",
                    "reason": "approval_timeout",
                    "prior_command_idempotency_key": prior_key,
                    "prior_proposal_id": prior_proposal,
                }
                # Clear active wait so late APPROVE cannot match frozen key
                ctx = dict(inst.context)
                if "wait" in ctx:
                    ctx["expired_wait"] = ctx.pop("wait")
                ctx["wait_expired"] = True
                inst.context = ctx
                inst.touch(now_iso)

                # One APPROVAL_TIMEOUT event
                store = self._events.setdefault(inst.workflow_id, [])
                next_seq = (store[-1].seq + 1) if store else (inst.event_seq + 1)
                inst.event_seq = next_seq
                store.append(
                    WorkflowEvent(
                        event_id=f"evt_{inst.workflow_id}_{inst.event_seq}",
                        workflow_id=inst.workflow_id,
                        tenant_id=inst.tenant_id,
                        seq=inst.event_seq,
                        event_type=WorkflowEventType.APPROVAL_TIMEOUT,
                        payload={
                            "reason": "approval_timeout",
                            "prior_command_idempotency_key": prior_key,
                        },
                        at=now_iso,
                    )
                )
                timed_out.append(inst.workflow_id)

        return timed_out
