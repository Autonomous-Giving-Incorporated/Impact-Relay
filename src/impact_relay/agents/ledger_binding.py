"""T1 in-memory ledger binding (PR-M3). T2 command_log lands in PR-P1."""

from __future__ import annotations

from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import Organization


class InMemoryLedgerBinding:
    """Process-local ledgers; durability_mode=none (K11 T1)."""

    def __init__(self) -> None:
        self._ledgers: dict[str, Ledger] = {}
        self._workspaces: dict[str, TenantWorkspace] = {}

    def register(self, ledger: Ledger, workspace: TenantWorkspace | None = None) -> None:
        tid = ledger.organization.id
        self._ledgers[tid] = ledger
        if workspace is not None:
            self._workspaces[tid] = workspace
        elif tid not in self._workspaces:
            self._workspaces[tid] = TenantWorkspace(
                ledger.organization, ledger=ledger
            )

    def for_tenant(self, tenant_id: str) -> Ledger:
        if tenant_id not in self._ledgers:
            # Empty ledger for tenant (tests may register first)
            org = Organization(id=tenant_id, name=tenant_id)
            self._ledgers[tenant_id] = Ledger(org)
        return self._ledgers[tenant_id]

    def workspace(self, tenant_id: str) -> TenantWorkspace | None:
        if tenant_id in self._workspaces:
            return self._workspaces[tenant_id]
        ledger = self.for_tenant(tenant_id)
        ws = TenantWorkspace(ledger.organization, ledger=ledger)
        self._workspaces[tenant_id] = ws
        return ws

    def rehydrate(self, tenant_id: str) -> Ledger:
        return self.for_tenant(tenant_id)

    def append_command_result(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        command_type: str,
        payload: dict[str, Any],
        result_json: dict[str, Any],
    ) -> None:
        return None  # T1 no-op

    def durability_mode(self) -> str:
        return "none"
