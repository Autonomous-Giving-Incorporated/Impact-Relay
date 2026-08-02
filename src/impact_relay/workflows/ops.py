"""Operator listing and signal helpers (PR-M5).

Pilot-demo human gates without OIDC. Works with memory store + optional
session file for multi-invocation CLI.
"""

from __future__ import annotations

import pickle
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import ApprovalReceipt, WorkflowState, utc_now_iso
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import WorkflowInstance, WorkflowRunStatus
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker

# re-export for type checkers
__all__ = [
    "CASE_FILTERS",
    "OperatorCase",
    "approval_from_dict",
    "instance_to_case",
    "list_blocked",
    "list_operator_cases",
    "load_ops_session",
    "save_ops_session",
    "seed_session_to_wait",
    "signal_approval_and_pump",
]

# Operator-visible case buckets
CASE_FILTERS = frozenset(
    {
        "all",
        "waiting",
        "blocked",
        "dead_letter",
        "failed",
        "needs_information",
        "active",
    }
)


@dataclass(frozen=True)
class OperatorCase:
    workflow_id: str
    tenant_id: str
    business_key: str
    workflow_state: str
    run_status: str
    attempt_count: int
    last_error: str | None
    wait_deadline: str | None
    command_idempotency_key: str | None
    bucket: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "business_key": self.business_key,
            "workflow_state": self.workflow_state,
            "run_status": self.run_status,
            "attempt_count": self.attempt_count,
            "last_error": self.last_error,
            "wait_deadline": self.wait_deadline,
            "command_idempotency_key": self.command_idempotency_key,
            "bucket": self.bucket,
        }


def _bucket(inst: WorkflowInstance) -> str:
    if inst.run_status == WorkflowRunStatus.DEAD_LETTER:
        return "dead_letter"
    if inst.run_status == WorkflowRunStatus.FAILED_TERMINAL:
        return "failed"
    if inst.workflow_state == WorkflowState.BLOCKED:
        return "blocked"
    if inst.workflow_state == WorkflowState.NEEDS_INFORMATION:
        return "needs_information"
    if inst.run_status == WorkflowRunStatus.WAITING_SIGNAL:
        return "waiting"
    if inst.run_status in (
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.RETRY_SCHEDULED,
    ):
        return "active"
    return "other"


def _wait_key(inst: WorkflowInstance) -> str | None:
    wait = inst.context.get("wait") or {}
    if wait.get("command_idempotency_key"):
        return str(wait["command_idempotency_key"])
    frozen = wait.get("frozen_command") or {}
    if frozen.get("idempotency_key"):
        return str(frozen["idempotency_key"])
    desc = inst.wait_descriptor or {}
    return desc.get("command_idempotency_key") or desc.get("prior_command_idempotency_key")


def instance_to_case(inst: WorkflowInstance) -> OperatorCase:
    return OperatorCase(
        workflow_id=inst.workflow_id,
        tenant_id=inst.tenant_id,
        business_key=inst.business_key,
        workflow_state=inst.workflow_state.value,
        run_status=inst.run_status.value,
        attempt_count=inst.attempt_count,
        last_error=inst.last_error,
        wait_deadline=inst.wait_deadline,
        command_idempotency_key=_wait_key(inst),
        bucket=_bucket(inst),
    )


def list_operator_cases(
    store: Any,
    tenant_id: str,
    *,
    filters: Iterable[str] | None = None,
    limit: int = 200,
) -> list[OperatorCase]:
    """List operator-visible cases.

    Default filters: waiting, blocked, dead_letter, needs_information, failed.
    """
    raw = [
        f.strip().lower()
        for f in (filters or ("waiting", "blocked", "dead_letter", "needs_information", "failed"))
    ]
    if "all" in raw:
        # Include completed / cancelled ("other") so status overviews are complete.
        want: set[str] = set(CASE_FILTERS - {"all"}) | {"other"}
    else:
        want = set(raw) & CASE_FILTERS
        if not want:
            want = {"waiting", "blocked", "dead_letter"}

    cases: list[OperatorCase] = []
    for inst in store.list(tenant_id, limit=max(limit, 500)):
        case = instance_to_case(inst)
        if case.bucket in want or ("active" in want and case.bucket == "active"):
            cases.append(case)
        if len(cases) >= limit:
            break
    # Prefer operational urgency first
    order = {
        "dead_letter": 0,
        "failed": 1,
        "blocked": 2,
        "needs_information": 3,
        "waiting": 4,
        "active": 5,
        "other": 6,
    }
    cases.sort(key=lambda c: (order.get(c.bucket, 9), c.workflow_id))
    return cases


def list_blocked(store: Any, tenant_id: str) -> list[OperatorCase]:
    return list_operator_cases(
        store, tenant_id, filters=("blocked", "dead_letter", "needs_information", "failed")
    )


def approval_from_dict(data: dict[str, Any], *, tenant_id: str | None = None) -> ApprovalReceipt:
    """Build ApprovalReceipt from operator JSON (schema-aligned)."""
    tid = str(data.get("tenant_id") or tenant_id or "")
    if not tid:
        raise ValueError("approval JSON requires tenant_id")
    return ApprovalReceipt(
        approval_id=str(data.get("approval_id") or f"op_{utc_now_iso()}"),
        tenant_id=tid,
        proposal_id=str(data.get("proposal_id") or "operator"),
        command_idempotency_key=str(data["command_idempotency_key"]),
        decision=str(data.get("decision") or "APPROVE"),
        approver_id=str(data["approver_id"]),
        approver_role=str(data.get("approver_role") or "finance_approver"),
        approved_at=str(data.get("approved_at") or utc_now_iso()),
        rationale=str(data.get("rationale") or "operator CLI approval"),
        policy_version=str(data.get("policy_version") or "v1.0"),
    )


def signal_approval_and_pump(
    runtime: WorkflowRuntime,
    *,
    tenant_id: str,
    workflow_id: str,
    approval: ApprovalReceipt,
    worker_ticks: int = 20,
) -> WorkflowInstance:
    """Signal human approval then claim/advance until wait or terminal."""
    runtime.signal_approval(tenant_id=tenant_id, workflow_id=workflow_id, approval=approval)
    worker = WorkflowWorker(
        runtime,
        WorkerConfig(worker_id="ops-signal", poll_interval_seconds=0.0),
    )
    for _ in range(max(1, worker_ticks)):
        worker.tick()
        inst = runtime.store.get(tenant_id, workflow_id)
        if inst is None:
            break
        if inst.run_status in (
            WorkflowRunStatus.WAITING_SIGNAL,
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.FAILED_TERMINAL,
            WorkflowRunStatus.DEAD_LETTER,
            WorkflowRunStatus.CANCELLED,
        ):
            # If still waiting for *another* gate, stop so operator can re-list
            if inst.run_status == WorkflowRunStatus.WAITING_SIGNAL:
                break
            if inst.run_status in (
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.FAILED_TERMINAL,
                WorkflowRunStatus.DEAD_LETTER,
                WorkflowRunStatus.CANCELLED,
            ):
                break
        if (
            inst.workflow_state
            in (
                WorkflowState.LEDGER_COMMITTED,
                WorkflowState.PUBLICATION_PENDING,
                WorkflowState.PUBLISHED,
                WorkflowState.NOTIFICATION_PENDING,
                WorkflowState.DELIVERED,
            )
            and inst.run_status != WorkflowRunStatus.PENDING
        ):
            if inst.run_status != WorkflowRunStatus.RUNNING:
                # continue pumping pending auto steps
                pass
    return runtime.store.get(tenant_id, workflow_id)


# ---------------------------------------------------------------------------
# Session persistence (local pilot only)
# ---------------------------------------------------------------------------


def save_ops_session(
    path: Path | str,
    store: InMemoryWorkflowStore,
    binding: InMemoryLedgerBinding,
    *,
    tenant_id: str,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "tenant_id": tenant_id,
        "store": store,
        "binding": binding,
    }
    with p.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_ops_session(
    path: Path | str,
) -> tuple[InMemoryWorkflowStore, InMemoryLedgerBinding, str]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"workflow session not found: {p}")
    with p.open("rb") as f:
        payload = pickle.load(f)
    store = payload["store"]
    binding = payload["binding"]
    tenant_id = str(payload["tenant_id"])
    if not isinstance(store, InMemoryWorkflowStore):
        raise TypeError("session store type mismatch")
    if not isinstance(binding, InMemoryLedgerBinding):
        raise TypeError("session binding type mismatch")
    return store, binding, tenant_id


def seed_session_to_wait(
    *,
    expense_rows: list[dict[str, Any]],
    fixture_path: Path | str | None = None,
    simulation: bool = False,
    worker_ticks: int = 15,
) -> tuple[WorkflowRuntime, InMemoryWorkflowStore, InMemoryLedgerBinding, str, list[str]]:
    """Start expense workflows and pump until human wait (or terminal)."""
    import copy

    from impact_relay.domain.tenant import TenantWorkspace
    from impact_relay.pilot import build_ledger_from_fixture, load_fixture

    data = copy.deepcopy(load_fixture(fixture_path))
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    runtime = WorkflowRuntime(store, binding)
    tenant_id = ledger.organization.id
    ids: list[str] = []
    for row in expense_rows:
        inst = runtime.start_expense_to_receipt(
            tenant_id=tenant_id,
            expense_row=row,
            simulation=simulation,
        )
        ids.append(inst.workflow_id)
    worker = WorkflowWorker(runtime, WorkerConfig(worker_id="ops-seed", poll_interval_seconds=0.0))
    for _ in range(worker_ticks):
        r = worker.tick()
        if r.claimed == 0:
            break
    return runtime, store, binding, tenant_id, ids
