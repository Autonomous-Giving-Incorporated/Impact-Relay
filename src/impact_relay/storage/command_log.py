"""SQL ledger_command_log (K17 fold rows) — multi-tenant.

Complements file-backed ``domain.ledger_log.FileLedgerCommandLog``.
Rehydrate still folds ``result_json`` only (never re-dispatch).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from impact_relay.agents.types import utc_now_iso
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.ledger_log import apply_result_json
from impact_relay.domain.types import Organization

if TYPE_CHECKING:
    from impact_relay.storage.sql import SqlEngine


class SqlLedgerCommandLog:
    def __init__(self, engine: SqlEngine) -> None:
        self._engine = engine

    def append(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        command_type: str,
        payload: dict[str, Any],
        result_json: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        payload_s = json.dumps(payload, sort_keys=True, default=str)
        result_s = json.dumps(result_json, sort_keys=True, default=str)
        with self._engine.conn() as conn:
            if self._engine.is_postgres:
                self._engine.execute(
                    conn,
                    """
                    INSERT INTO ledger_command_log (
                      tenant_id, idempotency_key, command_type,
                      payload_json, result_json, created_at
                    ) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    """,
                    (
                        tenant_id,
                        idempotency_key,
                        command_type,
                        payload_s,
                        result_s,
                        now,
                    ),
                )
            else:
                self._engine.execute(
                    conn,
                    """
                    INSERT OR IGNORE INTO ledger_command_log (
                      tenant_id, idempotency_key, command_type,
                      payload_json, result_json, created_at
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        tenant_id,
                        idempotency_key,
                        command_type,
                        payload_s,
                        result_s,
                        now,
                    ),
                )

    def iter_rows(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._engine.conn() as conn:
            rows = self._engine.fetchall(
                conn,
                """
                SELECT tenant_id, idempotency_key, command_type,
                       payload_json, result_json, created_at, seq
                FROM ledger_command_log
                WHERE tenant_id=?
                ORDER BY seq
                """,
                (tenant_id,),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            pj = d["payload_json"]
            rj = d["result_json"]
            out.append(
                {
                    "tenant_id": d["tenant_id"],
                    "idempotency_key": d["idempotency_key"],
                    "command_type": d["command_type"],
                    "payload": pj if isinstance(pj, dict) else json.loads(pj),
                    "result_json": rj if isinstance(rj, dict) else json.loads(rj),
                    "created_at": str(d["created_at"]),
                    "seq": d["seq"],
                }
            )
        return out

    def rehydrate(
        self,
        organization: Organization,
        *,
        base_ledger: Ledger | None = None,
    ) -> Ledger:
        """K17: fold result_json only — never re-dispatch commands."""
        if base_ledger is None:
            ledger = Ledger(organization)
        else:
            if base_ledger.organization.id != organization.id:
                raise ValueError("base_ledger organization mismatch")
            ledger = base_ledger
        for row in self.iter_rows(organization.id):
            apply_result_json(ledger, row["result_json"])
        return ledger
