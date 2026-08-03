"""Deterministic operational health and metrics summaries.

This module is intentionally dependency-free: it turns existing in-process stores,
storage bundles, workflow stores, and ledgers into host/CLI friendly dictionaries.
Production alerting can scrape or forward these summaries without changing domain
behavior.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.storage.sql import StorageBundle
from impact_relay.workflows.ops import instance_to_case
from impact_relay.workflows.types import WorkflowRunStatus


@dataclass(frozen=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_count(fn: Any) -> tuple[bool, int, str]:
    try:
        return True, int(fn()), "ok"
    except Exception as exc:  # noqa: BLE001 - health surfaces must not raise provider details
        return False, 0, exc.__class__.__name__


def summarize_workflows(
    store: Any,
    tenant_id: str,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Summarize workflow status, state, and operator attention buckets."""

    instances = list(store.list(tenant_id, limit=limit))
    status_counts = Counter(inst.run_status.value for inst in instances)
    state_counts = Counter(inst.workflow_state.value for inst in instances)
    bucket_counts = Counter(instance_to_case(inst).bucket for inst in instances)
    attention = sum(
        bucket_counts.get(bucket, 0)
        for bucket in ("dead_letter", "failed", "blocked", "needs_information", "waiting")
    )
    stale_running = [
        inst.workflow_id
        for inst in instances
        if inst.run_status == WorkflowRunStatus.RUNNING and not inst.lease_expires_at
    ]
    return {
        "tenant_id": tenant_id,
        "total": len(instances),
        "by_run_status": dict(sorted(status_counts.items())),
        "by_workflow_state": dict(sorted(state_counts.items())),
        "by_operator_bucket": dict(sorted(bucket_counts.items())),
        "attention_count": attention,
        "stale_running_without_lease": sorted(stale_running),
        "truncated": len(instances) >= limit,
    }


def summarize_outbox(outbox: Any, tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
    """Summarize tenant outbox backlog without claiming or mutating events."""

    events = list(outbox.list_for_tenant(tenant_id, limit=limit))
    topic_counts = Counter(ev.topic for ev in events)
    unpublished = [ev for ev in events if ev.published_at is None]
    published = len(events) - len(unpublished)
    max_attempts = max((ev.attempts for ev in events), default=0)
    return {
        "tenant_id": tenant_id,
        "total": len(events),
        "published": published,
        "unpublished": len(unpublished),
        "by_topic": dict(sorted(topic_counts.items())),
        "max_attempts": max_attempts,
        "truncated": len(events) >= limit,
    }


def summarize_ledger(ledger: Ledger) -> dict[str, Any]:
    """Summarize immutable ledger entity and audit counts."""

    return {
        "organization_id": ledger.organization.id,
        "donors": len(ledger.donors),
        "donations": len(ledger.donations),
        "allocations": len(ledger.allocations),
        "expenses": len(ledger.expenses),
        "expense_allocations": len(ledger.expense_allocations),
        "evidence": len(ledger.evidence),
        "attributions": len(ledger.attributions),
        "receipts": len(ledger.receipts),
        "audit_events": len(ledger.audit_log),
    }


def summarize_storage(bundle: StorageBundle, tenant_id: str) -> dict[str, Any]:
    """Summarize storage backend health for one tenant."""

    checks: list[HealthCheck] = []
    tenant_ok, tenant_count, tenant_detail = _safe_count(
        lambda: len(bundle.tenants.list(limit=500))
    )
    checks.append(HealthCheck("tenants", tenant_ok, tenant_detail))
    outbox_ok, outbox_count, outbox_detail = _safe_count(
        lambda: len(bundle.outbox.list_for_tenant(tenant_id, limit=500))
    )
    checks.append(HealthCheck("outbox", outbox_ok, outbox_detail))
    object_backend = getattr(bundle.objects, "backend", bundle.objects.__class__.__name__)
    checks.append(HealthCheck("objects", bool(object_backend), str(object_backend)))
    return {
        "tenant_id": tenant_id,
        "data_dir": str(bundle.data_dir),
        "database": "postgres" if bundle.is_postgres else "sqlite",
        "object_backend": object_backend,
        "tenant_records": tenant_count,
        "outbox_events": outbox_count,
        "ok": all(check.ok for check in checks),
        "checks": [check.to_dict() for check in checks],
    }


def build_operational_snapshot(
    *,
    tenant_id: str,
    storage: StorageBundle | None = None,
    workflow_store: Any | None = None,
    outbox: Any | None = None,
    ledger: Ledger | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Build one host-facing operational snapshot from available components."""

    components: dict[str, Any] = {}
    ok = True
    if storage is not None:
        storage_summary = summarize_storage(storage, tenant_id)
        components["storage"] = storage_summary
        ok = ok and bool(storage_summary.get("ok"))
        if outbox is None:
            outbox = storage.outbox
    if workflow_store is not None:
        workflow_summary = summarize_workflows(workflow_store, tenant_id, limit=limit)
        components["workflows"] = workflow_summary
        ok = ok and not bool(workflow_summary.get("stale_running_without_lease"))
    if outbox is not None:
        components["outbox"] = summarize_outbox(outbox, tenant_id, limit=limit)
    if ledger is not None:
        components["ledger"] = summarize_ledger(ledger)
    return {
        "snapshot_kind": "impact_relay_operational_snapshot",
        "schema_version": "v1.0",
        "tenant_id": tenant_id,
        "generated_at": _now_iso(),
        "ok": ok,
        "components": components,
    }
