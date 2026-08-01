"""Tenant registry repository (SQL)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from impact_relay.agents.types import utc_now_iso
from impact_relay.policy import tenant_slug
from impact_relay.storage.ports import TenantRecord

if TYPE_CHECKING:
    from impact_relay.storage.sql import SqlEngine


def _row_to_tenant(row: Any) -> TenantRecord:
    d = dict(row)
    meta_raw = d.get("meta_json") or "{}"
    if isinstance(meta_raw, dict):
        meta = meta_raw
    else:
        meta = json.loads(meta_raw)
    return TenantRecord(
        tenant_id=d["tenant_id"],
        display_name=d["display_name"],
        policy_version=d["policy_version"],
        policy_slug=d["policy_slug"],
        status=d.get("status") or "active",
        template_source=d.get("template_source"),
        created_at=str(d.get("created_at") or ""),
        updated_at=str(d.get("updated_at") or ""),
        meta=meta,
    )


class SqlTenantRepository:
    def __init__(self, engine: SqlEngine) -> None:
        self._engine = engine

    def upsert(self, record: TenantRecord) -> None:
        now = utc_now_iso()
        created = record.created_at or now
        updated = now
        meta = json.dumps(record.meta or {}, sort_keys=True)
        with self._engine.conn() as conn:
            if self._engine.is_postgres:
                self._engine.execute(
                    conn,
                    """
                    INSERT INTO tenants (
                      tenant_id, display_name, policy_version, policy_slug,
                      status, template_source, created_at, updated_at, meta_json
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      display_name=EXCLUDED.display_name,
                      policy_version=EXCLUDED.policy_version,
                      policy_slug=EXCLUDED.policy_slug,
                      status=EXCLUDED.status,
                      template_source=EXCLUDED.template_source,
                      updated_at=EXCLUDED.updated_at,
                      meta_json=EXCLUDED.meta_json
                    """,
                    (
                        record.tenant_id,
                        record.display_name,
                        record.policy_version,
                        record.policy_slug,
                        record.status,
                        record.template_source,
                        created,
                        updated,
                        meta,
                    ),
                )
            else:
                self._engine.execute(
                    conn,
                    """
                    INSERT INTO tenants (
                      tenant_id, display_name, policy_version, policy_slug,
                      status, template_source, created_at, updated_at, meta_json
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(tenant_id) DO UPDATE SET
                      display_name=excluded.display_name,
                      policy_version=excluded.policy_version,
                      policy_slug=excluded.policy_slug,
                      status=excluded.status,
                      template_source=excluded.template_source,
                      updated_at=excluded.updated_at,
                      meta_json=excluded.meta_json
                    """,
                    (
                        record.tenant_id,
                        record.display_name,
                        record.policy_version,
                        record.policy_slug,
                        record.status,
                        record.template_source,
                        created,
                        updated,
                        meta,
                    ),
                )

    def get(self, tenant_id: str) -> TenantRecord | None:
        with self._engine.conn() as conn:
            row = self._engine.fetchone(
                conn, "SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)
            )
            return _row_to_tenant(row) if row else None

    def list(self, *, status: str | None = None, limit: int = 200) -> list[TenantRecord]:
        with self._engine.conn() as conn:
            if status:
                rows = self._engine.fetchall(
                    conn,
                    "SELECT * FROM tenants WHERE status=? ORDER BY tenant_id LIMIT ?",
                    (status, limit),
                )
            else:
                rows = self._engine.fetchall(
                    conn,
                    "SELECT * FROM tenants ORDER BY tenant_id LIMIT ?",
                    (limit,),
                )
            return [_row_to_tenant(r) for r in rows]

    def upsert_from_policy(
        self,
        policy: Any,
        *,
        template_source: str | None = None,
        status: str = "active",
        meta: dict[str, Any] | None = None,
    ) -> TenantRecord:
        rec = TenantRecord(
            tenant_id=policy.tenant_id,
            display_name=policy.display_name or policy.tenant_id,
            policy_version=policy.version,
            policy_slug=tenant_slug(policy.tenant_id),
            status=status,
            template_source=template_source,
            meta=meta or {},
        )
        self.upsert(rec)
        loaded = self.get(policy.tenant_id)
        assert loaded is not None
        return loaded
