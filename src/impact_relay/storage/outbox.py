"""Structured event outbox (multi-tenant skeleton)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from impact_relay.agents.types import utc_now_iso
from impact_relay.storage.ports import OutboxEvent

if TYPE_CHECKING:
    from impact_relay.storage.sql import SqlEngine


def _new_id() -> str:
    return f"obx_{uuid.uuid4().hex[:16]}"


def _row_to_event(row: Any) -> OutboxEvent:
    d = dict(row)
    raw = d["payload_json"]
    payload = raw if isinstance(raw, dict) else json.loads(raw)
    return OutboxEvent(
        event_id=d["event_id"],
        tenant_id=d["tenant_id"],
        topic=d["topic"],
        payload=payload,
        created_at=str(d["created_at"]),
        published_at=str(d["published_at"]) if d.get("published_at") else None,
        attempts=int(d.get("attempts") or 0),
    )


class SqlOutboxStore:
    def __init__(self, engine: SqlEngine) -> None:
        self._engine = engine

    def append(
        self,
        *,
        tenant_id: str,
        topic: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> OutboxEvent:
        eid = event_id or _new_id()
        now = utc_now_iso()
        body = json.dumps(payload, sort_keys=True, default=str)
        with self._engine.conn() as conn:
            self._engine.execute(
                conn,
                """
                INSERT INTO outbox_events (
                  event_id, tenant_id, topic, payload_json, created_at, published_at, attempts
                ) VALUES (?,?,?,?,?,NULL,0)
                """,
                (eid, tenant_id, topic, body, now),
            )
        return OutboxEvent(
            event_id=eid,
            tenant_id=tenant_id,
            topic=topic,
            payload=dict(payload),
            created_at=now,
        )

    def claim_unpublished(
        self, *, limit: int = 50, now: datetime | None = None
    ) -> list[OutboxEvent]:
        _ = now  # reserved for lease-based claim later
        with self._engine.conn() as conn:
            rows = self._engine.fetchall(
                conn,
                """
                SELECT * FROM outbox_events
                WHERE published_at IS NULL
                ORDER BY created_at
                LIMIT ?
                """,
                (limit,),
            )
            events = [_row_to_event(r) for r in rows]
            for ev in events:
                self._engine.execute(
                    conn,
                    "UPDATE outbox_events SET attempts=attempts+1 WHERE event_id=?",
                    (ev.event_id,),
                )
            return events

    def mark_published(self, event_id: str, *, published_at: str | None = None) -> None:
        at = published_at or utc_now_iso()
        with self._engine.conn() as conn:
            self._engine.execute(
                conn,
                "UPDATE outbox_events SET published_at=? WHERE event_id=?",
                (at, event_id),
            )

    def list_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[OutboxEvent]:
        with self._engine.conn() as conn:
            rows = self._engine.fetchall(
                conn,
                """
                SELECT * FROM outbox_events
                WHERE tenant_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            )
            return [_row_to_event(r) for r in rows]
