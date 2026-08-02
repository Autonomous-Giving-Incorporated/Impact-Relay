"""Storage protocol interfaces (P1 storage boundaries).

All methods that touch durable data are tenant-scoped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TenantRecord:
    """Registered nonprofit / organization using Impact Relay."""

    tenant_id: str
    display_name: str
    policy_version: str
    policy_slug: str
    status: str = "active"  # active | suspended
    template_source: str | None = None  # e.g. org_hacker_dojo when cloned
    created_at: str = ""
    updated_at: str = ""
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "policy_version": self.policy_version,
            "policy_slug": self.policy_slug,
            "status": self.status,
            "template_source": self.template_source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "meta": dict(self.meta or {}),
        }


@runtime_checkable
class TenantRepository(Protocol):
    def upsert(self, record: TenantRecord) -> None: ...

    def get(self, tenant_id: str) -> TenantRecord | None: ...

    def list(self, *, status: str | None = None, limit: int = 200) -> list[TenantRecord]: ...

    def upsert_from_policy(
        self,
        policy: Any,
        *,
        template_source: str | None = None,
        status: str = "active",
        meta: dict[str, Any] | None = None,
    ) -> TenantRecord: ...


@runtime_checkable
class ObjectStorage(Protocol):
    """Evidence / receipt binary or JSON objects (tenant-scoped keys)."""

    def put(
        self,
        tenant_id: str,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        meta: dict[str, str] | None = None,
    ) -> str:
        """Store object; return opaque storage_id / path. Key must not contain '..'."""
        ...

    def get(self, tenant_id: str, key: str) -> bytes | None: ...

    def exists(self, tenant_id: str, key: str) -> bool: ...

    def delete(self, tenant_id: str, key: str) -> bool: ...


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    tenant_id: str
    topic: str
    payload: dict[str, Any]
    created_at: str
    published_at: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "topic": self.topic,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "published_at": self.published_at,
            "attempts": self.attempts,
        }


@runtime_checkable
class OutboxStore(Protocol):
    def append(
        self,
        *,
        tenant_id: str,
        topic: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> OutboxEvent: ...

    def claim_unpublished(
        self, *, limit: int = 50, now: datetime | None = None
    ) -> list[OutboxEvent]: ...

    def mark_published(self, event_id: str, *, published_at: str | None = None) -> None: ...

    def list_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[OutboxEvent]: ...
