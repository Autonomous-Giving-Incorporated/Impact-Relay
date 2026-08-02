"""Screen-ready JSON for host UI (finance review + donor receipts).

Used by the Hacker-Dojo app (and other nonprofit hosts) to render consoles
without reimplementing ledger/workflow logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impact_relay.auth.principal import Principal
from impact_relay.auth.rbac import (
    Permission,
    assert_permission,
)
from impact_relay.host.session import HostSession, open_host_session
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID
from impact_relay.workflows.durable import open_workspace


@dataclass
class FinanceConsole:
    """Finance review queue — waiting L3 gates + approve."""

    session: HostSession

    def _gate_list(self) -> None:
        if self.session.principal is None:
            return
        assert_permission(
            self.session.principal,
            Permission.WORKFLOW_LIST,
            tenant_id=self.session.tenant_id,
        )

    def metrics(self) -> dict[str, Any]:
        self._gate_list()
        status = self.session.status()
        waiting = self.session.list_waiting(filters="waiting")
        blocked = self.session.list_waiting(filters="blocked,dead_letter,needs_information,failed")
        return {
            "tenant_id": self.session.tenant_id,
            "data_dir": str(self.session.data_dir),
            "waiting_count": waiting.get("count", 0) if waiting.get("ok", True) else 0,
            "attention_count": blocked.get("count", 0) if blocked.get("ok", True) else 0,
            "ledger_commands": status.get("ledger_commands"),
            "entity_snapshot": status.get("entity_snapshot"),
            "expenses_in_ledger": len(status.get("expenses") or {}),
            "principal": self.session.principal.to_dict() if self.session.principal else None,
        }

    def queue(
        self, *, filters: str = "waiting,blocked,dead_letter,needs_information,failed"
    ) -> dict[str, Any]:
        self._gate_list()
        listed = self.session.list_waiting(filters=filters)
        if listed.get("ok") is False:
            return listed
        cases = []
        for c in listed.get("cases") or []:
            cases.append(self._enrich_case(c))
        return {
            "ok": True,
            "tenant_id": self.session.tenant_id,
            "count": len(cases),
            "cases": cases,
        }

    def _enrich_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Attach packet summary from live workspace when available."""
        out = dict(case)
        try:
            ws = open_workspace(self.session.data_dir)
            inst = ws.store.get(self.session.tenant_id, case["workflow_id"])
            if inst is None:
                return out
            ctx = inst.context or {}
            packet = ctx.get("packet") or {}
            out["packet_summary"] = {
                "vendor": packet.get("vendor") or ctx.get("vendor"),
                "amount": packet.get("amount") or ctx.get("amount"),
                "currency": packet.get("currency") or ctx.get("currency") or "USD",
                "category": packet.get("category") or ctx.get("category"),
                "description": packet.get("description") or ctx.get("description"),
                "expense_id": ctx.get("expense_id") or packet.get("expense_id"),
                "evidence_sufficiency": ctx.get("evidence_sufficiency")
                or packet.get("evidence_sufficiency"),
            }
            out["wait_deadline"] = inst.wait_deadline
            out["workflow_type"] = (
                inst.workflow_type.value
                if hasattr(inst.workflow_type, "value")
                else str(inst.workflow_type)
            )
        except FileNotFoundError:
            pass
        return out

    def case_detail(self, workflow_id: str) -> dict[str, Any]:
        self._gate_list()
        try:
            ws = open_workspace(self.session.data_dir)
        except FileNotFoundError as exc:
            return {"ok": False, "error": "no_workspace", "message": str(exc)}
        inst = ws.store.get(self.session.tenant_id, workflow_id)
        if inst is None:
            return {"ok": False, "error": "not_found", "workflow_id": workflow_id}
        case = {
            "workflow_id": inst.workflow_id,
            "tenant_id": inst.tenant_id,
            "business_key": inst.business_key,
            "workflow_state": inst.workflow_state.value,
            "run_status": inst.run_status.value,
            "context": {
                k: v
                for k, v in (inst.context or {}).items()
                if k
                not in (
                    "policy",  # large; omit from detail default
                )
            },
            "wait_descriptor": inst.wait_descriptor,
            "wait_deadline": inst.wait_deadline,
            "last_error": inst.last_error,
            "events": [
                {
                    "seq": e.seq,
                    "event_type": e.event_type.value
                    if hasattr(e.event_type, "value")
                    else str(e.event_type),
                    "payload": e.payload,
                    "at": e.at,
                }
                for e in ws.store.list_events(self.session.tenant_id, workflow_id)
            ],
        }
        return {"ok": True, "case": self._enrich_case(case)}

    def approve(
        self,
        workflow_id: str,
        *,
        proposer_id: str | None = None,
        approver_id: str | None = None,
    ) -> dict[str, Any]:
        return self.session.approve(
            workflow_id=workflow_id,
            approver_id=approver_id,
            proposer_id=proposer_id,
        )

    def seed(self, **kwargs: Any) -> dict[str, Any]:
        return self.session.seed(**kwargs)


@dataclass
class DonorConsole:
    """Donor timeline / receipt screens."""

    session: HostSession
    donor_id: str

    def _api(self):
        return self.session.donor_api()

    def dashboard(self) -> dict[str, Any]:
        return self._api().dashboard(self.donor_id, principal=self.session.principal)

    def timeline(self) -> list[dict[str, Any]]:
        return self._api().fund_timeline(self.donor_id, principal=self.session.principal)

    def balances(self) -> list[dict[str, Any]]:
        return self._api().allocation_balances(self.donor_id, principal=self.session.principal)

    def receipts(self) -> list[dict[str, Any]]:
        return self._api().list_receipts(self.donor_id, principal=self.session.principal)

    def receipt_detail(self, receipt_id: str) -> dict[str, Any]:
        return self._api().get_receipt(self.donor_id, receipt_id, principal=self.session.principal)


def open_finance_console(
    data_dir: Path | str | None = None,
    *,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    principal: Principal | None = None,
    require_principal_for_approve: bool = False,
) -> FinanceConsole:
    session = open_host_session(
        data_dir,
        tenant_id=tenant_id,
        principal=principal,
        require_principal_for_approve=require_principal_for_approve,
    )
    return FinanceConsole(session=session)


def open_donor_console(
    donor_id: str,
    data_dir: Path | str | None = None,
    *,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    principal: Principal | None = None,
) -> DonorConsole:
    session = open_host_session(data_dir, tenant_id=tenant_id, principal=principal)
    return DonorConsole(session=session, donor_id=donor_id)
