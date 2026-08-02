"""Workflow store and binding ports (PR-M1).

Implementations:
- store_memory.py (M3) — process-local
- store_sql.py (P2) — SQLite default, Postgres via DSN + SKIP LOCKED claim
- LedgerBinding T1/T2 (P1 ledger_log + durable CLI)

This module defines Protocol interfaces only.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from impact_relay.agents.types import ExecutionReceipt
from impact_relay.workflows.types import (
    AdvanceCommitBundle,
    WorkflowEvent,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowType,
)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC preferred."""
        ...

    def now_iso(self) -> str: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


@runtime_checkable
class WorkflowStore(Protocol):
    def create(self, instance: WorkflowInstance) -> None: ...

    def get(self, tenant_id: str, workflow_id: str) -> WorkflowInstance | None: ...

    def get_by_business_key(
        self, tenant_id: str, workflow_type: WorkflowType | str, business_key: str
    ) -> WorkflowInstance | None: ...

    def list(
        self,
        tenant_id: str,
        *,
        workflow_state: list[str] | None = None,
        run_status: list[str] | None = None,
        limit: int = 100,
    ) -> list[WorkflowInstance]: ...

    def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_ttl: timedelta,
    ) -> builtins.list[WorkflowInstance]:
        """Claim PENDING | RETRY_SCHEDULED | expired RUNNING. Never WAITING_SIGNAL."""
        ...

    def update_instance(self, instance: WorkflowInstance) -> None: ...

    def append_events(
        self,
        tenant_id: str,
        workflow_id: str,
        events: builtins.list[WorkflowEventWrite] | builtins.list[WorkflowEvent],
    ) -> None: ...

    def list_events(self, tenant_id: str, workflow_id: str) -> builtins.list[WorkflowEvent]: ...

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
        """Atomic: insert signal + set run_status PENDING + next_run_at=now (K5)."""
        ...

    def take_unconsumed_signals(
        self, tenant_id: str, workflow_id: str
    ) -> builtins.list[WorkflowSignal]: ...

    def mark_signal_consumed(self, tenant_id: str, signal_id: str, result: str) -> None: ...

    def put_execution_receipt(self, receipt: ExecutionReceipt, *, workflow_id: str) -> None:
        """Store success/sim/skip only. Raise if status is FAILED."""
        ...

    def get_execution_receipt(
        self, tenant_id: str, idempotency_key: str
    ) -> ExecutionReceipt | None: ...

    def commit_advance(self, bundle: AdvanceCommitBundle) -> None:
        """Atomic: receipts + events + instance + signal consume (+ optional ledger log)."""
        ...


@runtime_checkable
class LedgerBinding(Protocol):
    """Tenant-scoped ledger access + T2 durability (K11/K17).

    T1: in-process ledger only; append_command_result no-op.
    T2: rehydrate folds result_json; never re-dispatch.
    """

    def for_tenant(self, tenant_id: str) -> Any:
        """Return live Ledger for this process (rehydrated first in T2)."""
        ...

    def workspace(self, tenant_id: str) -> Any | None:
        """Notification/consent workspace bound to the same ledger, if any."""
        ...

    def rehydrate(self, tenant_id: str) -> Any:
        """
        Build or restore Ledger for tenant.
        T1: return existing process ledger.
        T2 command_log: empty Ledger + fold result_json in seq order (K17).
        """
        ...

    def append_command_result(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        command_type: str,
        payload: dict[str, Any],
        result_json: dict[str, Any],
    ) -> None:
        """T2: persist log row. T1: no-op."""
        ...

    def durability_mode(self) -> str:
        """none | command_log | snapshot | repos"""
        ...


# Factory: instance → CommandExecutor (K8 simulation is instance-scoped)
ExecutorFactory = Callable[[WorkflowInstance], Any]


class SystemClock:
    """Default Clock implementation (stdlib)."""

    def now(self) -> datetime:

        return datetime.now(UTC)

    def now_iso(self) -> str:
        return self.now().replace(microsecond=0).isoformat()


class UuidIdGenerator:
    """Default IdGenerator."""

    def new_id(self, prefix: str) -> str:
        import uuid

        return f"{prefix}_{uuid.uuid4().hex[:12]}"
