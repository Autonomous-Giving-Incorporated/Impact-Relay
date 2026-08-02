"""Multi-tenant ledger entity repository (SQL).

Persists domain entity maps for host apps (Hacker-Dojo first) while money
mutations still go only through ``LedgerCommandExecutor``. Load/save uses the
same K17 snapshot shape as ``ledger_log`` (fold-only rehydrate).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from impact_relay.agents.types import utc_now_iso
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.ledger_log import apply_result_json, snapshot_ledger_entities
from impact_relay.domain.types import Organization

if TYPE_CHECKING:
    from impact_relay.storage.sql import SqlEngine

# Maps in snapshot_ledger_entities (excluding organization + internal indexes)
_ENTITY_MAPS = (
    "donors",
    "donations",
    "allocations",
    "donation_allocations",
    "expenses",
    "expense_allocations",
    "evidence",
    "attributions",
    "receipts",
)


class LedgerEntityRepository:
    """Tenant-scoped save/load of ledger entity maps."""

    def __init__(self, engine: SqlEngine) -> None:
        self._engine = engine

    def save_ledger(self, ledger: Ledger) -> None:
        """Replace all stored entities for ``ledger.organization.id``."""
        tenant_id = ledger.organization.id
        snap = snapshot_ledger_entities(ledger)
        now = utc_now_iso()
        with self._engine.conn() as conn:
            self._engine.execute(conn, "DELETE FROM ledger_entity WHERE tenant_id=?", (tenant_id,))
            self._engine.execute(conn, "DELETE FROM ledger_meta WHERE tenant_id=?", (tenant_id,))
            for etype in _ENTITY_MAPS:
                mapping = snap.get(etype) or {}
                if not isinstance(mapping, dict):
                    continue
                for eid, body in mapping.items():
                    body_s = json.dumps(body, sort_keys=True, default=str)
                    self._engine.execute(
                        conn,
                        """
                        INSERT INTO ledger_entity (
                          tenant_id, entity_type, entity_id, body_json, updated_at
                        ) VALUES (?,?,?,?,?)
                        """,
                        (tenant_id, etype, str(eid), body_s, now),
                    )
            meta_org = json.dumps(snap.get("organization") or {}, sort_keys=True)
            meta_exp_rcpt = json.dumps(snap.get("expense_receipts") or {}, sort_keys=True)
            meta_snaps = json.dumps(snap.get("receipt_snapshots") or {}, sort_keys=True)
            self._engine.execute(
                conn,
                """
                INSERT INTO ledger_meta (
                  tenant_id, organization_json, expense_receipts_json,
                  receipt_snapshots_json, updated_at
                ) VALUES (?,?,?,?,?)
                """,
                (tenant_id, meta_org, meta_exp_rcpt, meta_snaps, now),
            )

    def load_ledger(
        self,
        organization: Organization | None = None,
        *,
        tenant_id: str | None = None,
    ) -> Ledger | None:
        """Load ledger for tenant. Returns None if no snapshot stored."""
        tid = tenant_id or (organization.id if organization else None)
        if not tid:
            raise ValueError("tenant_id or organization required")
        with self._engine.conn() as conn:
            meta = self._engine.fetchone(
                conn, "SELECT * FROM ledger_meta WHERE tenant_id=?", (tid,)
            )
            if not meta:
                return None
            rows = self._engine.fetchall(
                conn,
                """
                SELECT entity_type, entity_id, body_json
                FROM ledger_entity WHERE tenant_id=?
                """,
                (tid,),
            )
        org_raw = meta["organization_json"]
        org_d = org_raw if isinstance(org_raw, dict) else json.loads(org_raw)
        if organization is not None and organization.id != tid:
            raise ValueError("organization id mismatch")
        org = organization or Organization(
            id=str(org_d.get("id") or tid),
            name=str(org_d.get("name") or tid),
            policy_version=str(org_d.get("policy_version") or "v1.0"),
        )
        entities: dict[str, Any] = {k: {} for k in _ENTITY_MAPS}
        for r in rows:
            d = dict(r)
            et = d["entity_type"]
            eid = d["entity_id"]
            body = d["body_json"]
            if isinstance(body, str):
                body = json.loads(body)
            entities.setdefault(et, {})[eid] = body
        exp_rcpt = meta["expense_receipts_json"]
        snaps = meta["receipt_snapshots_json"]
        entities["expense_receipts"] = (
            exp_rcpt if isinstance(exp_rcpt, dict) else json.loads(exp_rcpt or "{}")
        )
        entities["receipt_snapshots"] = (
            snaps if isinstance(snaps, dict) else json.loads(snaps or "{}")
        )
        entities["organization"] = org_d
        entities["external_index"] = {
            e.get("external_source_id"): e.get("id")
            for e in (entities.get("expenses") or {}).values()
            if isinstance(e, dict) and e.get("external_source_id")
        }
        ledger = Ledger(org)
        apply_result_json(
            ledger,
            {
                "command_type": "ledger_entity_load",
                "idempotency_key": f"load:{tid}",
                "entities": entities,
                "output_refs": [],
                "output_payload": {},
            },
        )
        return ledger

    def list_expenses(
        self, tenant_id: str, *, state: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Query expense bodies for a tenant (host app list views)."""
        with self._engine.conn() as conn:
            rows = self._engine.fetchall(
                conn,
                """
                SELECT entity_id, body_json FROM ledger_entity
                WHERE tenant_id=? AND entity_type='expenses'
                ORDER BY entity_id
                LIMIT ?
                """,
                (tenant_id, max(limit, 1)),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            body = r["body_json"]
            if isinstance(body, str):
                body = json.loads(body)
            if state and body.get("state") != state:
                continue
            out.append(body)
            if len(out) >= limit:
                break
        return out

    def get_expense(self, tenant_id: str, expense_id: str) -> dict[str, Any] | None:
        with self._engine.conn() as conn:
            row = self._engine.fetchone(
                conn,
                """
                SELECT body_json FROM ledger_entity
                WHERE tenant_id=? AND entity_type='expenses' AND entity_id=?
                """,
                (tenant_id, expense_id),
            )
        if not row:
            return None
        body = row["body_json"]
        return body if isinstance(body, dict) else json.loads(body)

    def get_receipt(self, tenant_id: str, receipt_id: str) -> dict[str, Any] | None:
        with self._engine.conn() as conn:
            row = self._engine.fetchone(
                conn,
                """
                SELECT body_json FROM ledger_entity
                WHERE tenant_id=? AND entity_type='receipts' AND entity_id=?
                """,
                (tenant_id, receipt_id),
            )
        if not row:
            return None
        body = row["body_json"]
        return body if isinstance(body, dict) else json.loads(body)

    def list_receipts(self, tenant_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._engine.conn() as conn:
            rows = self._engine.fetchall(
                conn,
                """
                SELECT body_json FROM ledger_entity
                WHERE tenant_id=? AND entity_type='receipts'
                ORDER BY entity_id
                LIMIT ?
                """,
                (tenant_id, limit),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            body = r["body_json"]
            out.append(body if isinstance(body, dict) else json.loads(body))
        return out

    def delete_tenant_ledger(self, tenant_id: str) -> None:
        with self._engine.conn() as conn:
            self._engine.execute(conn, "DELETE FROM ledger_entity WHERE tenant_id=?", (tenant_id,))
            self._engine.execute(conn, "DELETE FROM ledger_meta WHERE tenant_id=?", (tenant_id,))
