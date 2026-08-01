"""Host application session — durable pilot + entity queries in one place."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impact_relay.policy import load_tenant_policy
from impact_relay.storage import open_storage
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    ensure_canonical_hacker_dojo_tenant,
    register_cloned_tenant,
)
from impact_relay.workflows.durable import (
    DEFAULT_DATA_DIR,
    durable_approve,
    durable_list,
    durable_rehydrate_check,
    durable_seed,
    durable_status,
    durable_worker,
    open_workspace,
)


@dataclass
class HostSession:
    """Easy façade for a nonprofit host app (Hacker-Dojo is the reference).

    Does not own money mutation logic — delegates to durable workflows and
    storage. Safe defaults for local SQLite pilot data-dirs.
    """

    data_dir: Path
    tenant_id: str
    display_name: str = ""

    def __enter__(self) -> HostSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    # ------------------------------------------------------------------
    # Policy / identity
    # ------------------------------------------------------------------

    def policy(self, version: str = "v1.0") -> Any:
        """Load versioned tenant policy pack."""
        return load_tenant_policy(self.tenant_id, version)

    def ensure_registered(self) -> dict[str, Any]:
        """Ensure tenant row exists in storage registry (idempotent)."""
        store = open_storage(self.data_dir)
        if self.tenant_id == CANONICAL_PILOT_TENANT_ID:
            rec = ensure_canonical_hacker_dojo_tenant(store)
        else:
            _, rec = register_cloned_tenant(
                store,
                tenant_id=self.tenant_id,
                display_name=self.display_name or self.tenant_id,
            )
        return rec.to_dict()

    # ------------------------------------------------------------------
    # Durable pilot ops (seed → list → approve → worker)
    # ------------------------------------------------------------------

    def seed(
        self,
        *,
        expense_batch: Path | str | None = None,
        fixture_path: Path | str | None = None,
    ) -> dict[str, Any]:
        return durable_seed(
            self.data_dir,
            expense_batch=expense_batch,
            fixture_path=fixture_path,
        )

    def list_waiting(
        self,
        *,
        filters: str = "waiting,blocked,dead_letter,needs_information,failed",
    ) -> dict[str, Any]:
        return durable_list(self.data_dir, filters=filters)

    def approve(
        self,
        *,
        workflow_id: str | None = None,
        approver_id: str = "finance.approver@hackersdojo.example",
    ) -> dict[str, Any]:
        if approver_id.startswith("agent:"):
            return {"ok": False, "error": "approver_must_be_human"}
        return durable_approve(
            self.data_dir, workflow_id=workflow_id, approver_id=approver_id
        )

    def worker_once(self, *, max_ticks: int = 50) -> dict[str, Any]:
        return durable_worker(self.data_dir, once=True, max_ticks=max_ticks)

    def status(self) -> dict[str, Any]:
        return durable_status(self.data_dir)

    def check_rehydrate(self) -> dict[str, Any]:
        return durable_rehydrate_check(self.data_dir)

    # ------------------------------------------------------------------
    # Host queries (entity snapshot — no command-log replay)
    # ------------------------------------------------------------------

    def list_expenses(
        self, *, state: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        store = open_storage(self.data_dir)
        return store.ledger.list_expenses(
            self.tenant_id, state=state, limit=limit
        )

    def get_expense(self, expense_id: str) -> dict[str, Any] | None:
        store = open_storage(self.data_dir)
        return store.ledger.get_expense(self.tenant_id, expense_id)

    def list_receipts(self, *, limit: int = 200) -> list[dict[str, Any]]:
        store = open_storage(self.data_dir)
        return store.ledger.list_receipts(self.tenant_id, limit=limit)

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        store = open_storage(self.data_dir)
        return store.ledger.get_receipt(self.tenant_id, receipt_id)

    def open_workspace(self, *, create: bool = False) -> Any:
        """Advanced: full DurableWorkspace (workflows + binding + storage)."""
        return open_workspace(self.data_dir, create=create)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.data_dir.resolve()),
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "canonical_pilot": self.tenant_id == CANONICAL_PILOT_TENANT_ID,
        }


def open_host_session(
    data_dir: Path | str | None = None,
    *,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    display_name: str = "",
    ensure_registered: bool = True,
) -> HostSession:
    """Open a host session for any tenant (defaults to Hacker Dojo pilot)."""
    path = Path(data_dir or DEFAULT_DATA_DIR)
    session = HostSession(
        data_dir=path,
        tenant_id=tenant_id,
        display_name=display_name
        or ("Hacker Dojo" if tenant_id == CANONICAL_PILOT_TENANT_ID else tenant_id),
    )
    if ensure_registered:
        path.mkdir(parents=True, exist_ok=True)
        session.ensure_registered()
    return session
