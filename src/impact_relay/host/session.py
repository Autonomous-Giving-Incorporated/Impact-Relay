"""Host application session — durable pilot + entity queries in one place."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from impact_relay.auth.principal import Principal
from impact_relay.auth.rbac import (
    AuthorizationError,
    Permission,
    assert_permission,
    assert_separation_of_duties,
)
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

    Bind a ``Principal`` (from OIDC or fixture) with ``with_principal`` so
    approve/list honor RBAC.
    """

    data_dir: Path
    tenant_id: str
    display_name: str = ""
    principal: Principal | None = None
    # When True, approve requires a bound principal (production host mode).
    require_principal_for_approve: bool = False
    _last_proposer_id: str | None = field(default=None, repr=False)

    def __enter__(self) -> HostSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    # ------------------------------------------------------------------
    # Policy / identity
    # ------------------------------------------------------------------

    def with_principal(self, principal: Principal) -> HostSession:
        """Return a session copy bound to an authenticated principal (OIDC or fixture)."""
        if principal.tenant_id != self.tenant_id:
            raise AuthorizationError(
                f"principal tenant {principal.tenant_id!r} != session {self.tenant_id!r}"
            )
        return HostSession(
            data_dir=self.data_dir,
            tenant_id=self.tenant_id,
            display_name=self.display_name,
            principal=principal,
            require_principal_for_approve=self.require_principal_for_approve,
            _last_proposer_id=self._last_proposer_id,
        )

    def require_principal(self) -> Principal:
        if self.principal is None:
            raise AuthorizationError(
                "no principal bound — host must call with_principal() after OIDC login"
            )
        return self.principal

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

    def _gate(self, permission: Permission) -> dict[str, Any] | None:
        """If a principal is bound, enforce permission; otherwise skip (CLI pilot)."""
        if self.principal is None:
            return None
        try:
            assert_permission(self.principal, permission, tenant_id=self.tenant_id)
        except AuthorizationError as exc:
            return {"ok": False, "error": "forbidden", "message": str(exc)}
        return None

    # ------------------------------------------------------------------
    # Durable pilot ops (seed → list → approve → worker)
    # ------------------------------------------------------------------

    def seed(
        self,
        *,
        expense_batch: Path | str | None = None,
        fixture_path: Path | str | None = None,
    ) -> dict[str, Any]:
        # When principal bound: tenant_admin or finance_approver may seed pilot data
        if self.principal is not None:
            from impact_relay.auth.roles import permissions_for_roles

            perms = permissions_for_roles(self.principal.roles)
            if (
                Permission.WORKFLOW_SEED not in perms
                and Permission.TENANT_ADMIN not in perms
                and Permission.WORKFLOW_APPROVE_EXPENSE not in perms
            ):
                return {
                    "ok": False,
                    "error": "forbidden",
                    "message": f"{self.principal.email!r} cannot seed workflows",
                }
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
        err = self._gate(Permission.WORKFLOW_LIST)
        if err:
            return err
        return durable_list(self.data_dir, filters=filters)

    def approve(
        self,
        *,
        workflow_id: str | None = None,
        approver_id: str | None = None,
        proposer_id: str | None = None,
    ) -> dict[str, Any]:
        """Approve waiting expense. Uses principal.approver_id when bound."""
        if self.require_principal_for_approve and self.principal is None:
            return {
                "ok": False,
                "error": "principal_required",
                "message": "bind Principal via with_principal() before approve",
            }
        if self.principal is not None:
            err = self._gate(Permission.WORKFLOW_APPROVE_EXPENSE)
            if err:
                return err
            try:
                assert_separation_of_duties(
                    self.principal,
                    action="approve_expense",
                    proposer_id=proposer_id or self._last_proposer_id,
                )
            except AuthorizationError as exc:
                return {
                    "ok": False,
                    "error": "separation_of_duties",
                    "message": str(exc),
                }
            actor = self.principal.approver_id
        else:
            actor = approver_id or "finance.approver@hackersdojo.example"

        if actor.startswith("agent:"):
            return {"ok": False, "error": "approver_must_be_human"}
        return durable_approve(self.data_dir, workflow_id=workflow_id, approver_id=actor)

    def worker_once(self, *, max_ticks: int = 50) -> dict[str, Any]:
        return durable_worker(self.data_dir, once=True, max_ticks=max_ticks)

    def status(self) -> dict[str, Any]:
        return durable_status(self.data_dir)

    def check_rehydrate(self) -> dict[str, Any]:
        return durable_rehydrate_check(self.data_dir)

    # ------------------------------------------------------------------
    # Host queries (entity snapshot — no command-log replay)
    # ------------------------------------------------------------------

    def list_expenses(self, *, state: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        err = self._gate(Permission.EXPENSE_READ)
        if err:
            raise AuthorizationError(err["message"])
        store = open_storage(self.data_dir)
        return store.ledger.list_expenses(self.tenant_id, state=state, limit=limit)

    def get_expense(self, expense_id: str) -> dict[str, Any] | None:
        err = self._gate(Permission.EXPENSE_READ)
        if err:
            raise AuthorizationError(err["message"])
        store = open_storage(self.data_dir)
        return store.ledger.get_expense(self.tenant_id, expense_id)

    def list_receipts(self, *, limit: int = 200) -> list[dict[str, Any]]:
        err = self._gate(Permission.RECEIPT_READ)
        if err:
            raise AuthorizationError(err["message"])
        store = open_storage(self.data_dir)
        return store.ledger.list_receipts(self.tenant_id, limit=limit)

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        err = self._gate(Permission.RECEIPT_READ)
        if err:
            raise AuthorizationError(err["message"])
        store = open_storage(self.data_dir)
        return store.ledger.get_receipt(self.tenant_id, receipt_id)

    def open_workspace(self, *, create: bool = False) -> Any:
        """Advanced: full DurableWorkspace (workflows + binding + storage)."""
        return open_workspace(self.data_dir, create=create)

    def donor_api(self) -> Any:
        """Donor experience API bound to the in-process workspace for this data-dir.

        Loads ledger from entity snapshot when present, else rehydrates command log.
        """
        from impact_relay.domain.tenant import TenantWorkspace
        from impact_relay.donor import open_donor_api

        ws_store = open_workspace(self.data_dir, create=False)
        ledger = ws_store.binding.for_tenant(self.tenant_id)
        # Prefer entity snapshot if available
        if ws_store.storage is not None:
            snap = ws_store.storage.ledger.load_ledger(tenant_id=self.tenant_id)
            if snap is not None:
                ledger = snap
        tw = TenantWorkspace(ledger.organization, ledger=ledger)
        return open_donor_api(tw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.data_dir.resolve()),
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "canonical_pilot": self.tenant_id == CANONICAL_PILOT_TENANT_ID,
            "principal": self.principal.to_dict() if self.principal else None,
            "require_principal_for_approve": self.require_principal_for_approve,
        }


def open_host_session(
    data_dir: Path | str | None = None,
    *,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    display_name: str = "",
    ensure_registered: bool = True,
    require_principal_for_approve: bool = False,
    principal: Principal | None = None,
) -> HostSession:
    """Open a host session for any tenant (defaults to Hacker Dojo pilot)."""
    path = Path(data_dir or DEFAULT_DATA_DIR)
    session = HostSession(
        data_dir=path,
        tenant_id=tenant_id,
        display_name=display_name
        or ("Hacker Dojo" if tenant_id == CANONICAL_PILOT_TENANT_ID else tenant_id),
        principal=principal,
        require_principal_for_approve=require_principal_for_approve,
    )
    if ensure_registered:
        path.mkdir(parents=True, exist_ok=True)
        session.ensure_registered()
    return session
