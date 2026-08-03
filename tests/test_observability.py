"""Operational observability summary tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from impact_relay.agents.expense_workflow import run_expense_approval_slice
from impact_relay.agents.types import WorkflowState
from impact_relay.observability import (
    HealthCheck,
    build_operational_snapshot,
    summarize_ledger,
    summarize_outbox,
    summarize_storage,
    summarize_workflows,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.storage.ports import TenantRecord
from impact_relay.storage.sql import StorageBundle
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import WorkflowInstance, WorkflowRunStatus, WorkflowType

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _instance(
    workflow_id: str,
    *,
    state: WorkflowState,
    status: WorkflowRunStatus,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    lease_expires_at: str | None = None,
) -> WorkflowInstance:
    return WorkflowInstance(
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key=f"biz-{workflow_id}",
        workflow_state=state,
        run_status=status,
        lease_expires_at=lease_expires_at,
    )


def _ledger_with_receipt():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    rows = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
                "created_at": "2026-08-12T12:00:00+00:00",
            }
        ],
        send_email=False,
    )
    assert result.receipts
    return ledger


def test_health_check_to_dict() -> None:
    assert HealthCheck("storage", False, "RuntimeError").to_dict() == {
        "name": "storage",
        "ok": False,
        "detail": "RuntimeError",
    }


def test_summarize_workflows_counts_status_state_and_attention() -> None:
    store = InMemoryWorkflowStore()
    for inst in (
        _instance(
            "wf_wait", state=WorkflowState.REVIEW_PENDING, status=WorkflowRunStatus.WAITING_SIGNAL
        ),
        _instance("wf_blocked", state=WorkflowState.BLOCKED, status=WorkflowRunStatus.RUNNING),
        _instance("wf_done", state=WorkflowState.DELIVERED, status=WorkflowRunStatus.COMPLETED),
        _instance(
            "wf_stale", state=WorkflowState.EVIDENCE_PENDING, status=WorkflowRunStatus.RUNNING
        ),
        _instance(
            "wf_other_tenant",
            state=WorkflowState.REVIEW_PENDING,
            status=WorkflowRunStatus.WAITING_SIGNAL,
            tenant_id="org_other",
        ),
    ):
        store.create(inst)

    summary = summarize_workflows(store, CANONICAL_PILOT_TENANT_ID)

    assert summary["total"] == 4
    assert summary["by_run_status"] == {
        "COMPLETED": 1,
        "RUNNING": 2,
        "WAITING_SIGNAL": 1,
    }
    assert summary["by_workflow_state"]["BLOCKED"] == 1
    assert summary["by_operator_bucket"] == {"blocked": 1, "other": 1, "waiting": 1, "active": 1}
    assert summary["attention_count"] == 2
    assert summary["stale_running_without_lease"] == ["wf_blocked", "wf_stale"]
    assert summary["truncated"] is False


def test_summarize_outbox_counts_without_claiming(tmp_path: Path) -> None:
    bundle = StorageBundle(tmp_path / "storage")
    first = bundle.outbox.append(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        topic="receipt.published",
        payload={"receipt_id": "r1"},
    )
    second = bundle.outbox.append(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        topic="notification.requested",
        payload={"intent_id": "n1"},
    )
    bundle.outbox.append(tenant_id="org_other", topic="receipt.published", payload={})
    bundle.outbox.mark_published(first.event_id, published_at="2026-08-01T00:00:00+00:00")

    summary = summarize_outbox(bundle.outbox, CANONICAL_PILOT_TENANT_ID)

    assert summary == {
        "tenant_id": CANONICAL_PILOT_TENANT_ID,
        "total": 2,
        "published": 1,
        "unpublished": 1,
        "by_topic": {"notification.requested": 1, "receipt.published": 1},
        "max_attempts": 0,
        "truncated": False,
    }
    assert second.published_at is None
    assert bundle.outbox.list_for_tenant(CANONICAL_PILOT_TENANT_ID, limit=10)[0].attempts == 0


def test_summarize_storage_reports_backend_and_degraded_checks(tmp_path: Path) -> None:
    bundle = StorageBundle(tmp_path / "storage")
    bundle.tenants.upsert(
        TenantRecord(
            tenant_id=CANONICAL_PILOT_TENANT_ID,
            display_name="Hacker Dojo",
            policy_version="v1.0",
            policy_slug="hacker-dojo",
        )
    )
    bundle.outbox.append(tenant_id=CANONICAL_PILOT_TENANT_ID, topic="x", payload={})

    healthy = summarize_storage(bundle, CANONICAL_PILOT_TENANT_ID)
    assert healthy["ok"] is True
    assert healthy["database"] == "sqlite"
    assert healthy["object_backend"] == "local"
    assert healthy["tenant_records"] == 1
    assert healthy["outbox_events"] == 1
    assert healthy["checks"] == [
        {"name": "tenants", "ok": True, "detail": "ok"},
        {"name": "outbox", "ok": True, "detail": "ok"},
        {"name": "objects", "ok": True, "detail": "local"},
    ]

    class BrokenTenants:
        def list(self, *, limit: int = 500) -> list[Any]:
            raise RuntimeError("database password leaked here")

    bundle.tenants = BrokenTenants()  # type: ignore[assignment]
    degraded = summarize_storage(bundle, CANONICAL_PILOT_TENANT_ID)
    assert degraded["ok"] is False
    assert degraded["checks"][0] == {"name": "tenants", "ok": False, "detail": "RuntimeError"}
    assert "password" not in degraded["checks"][0]["detail"]


def test_summarize_ledger_counts_entities_and_audit_events() -> None:
    ledger = _ledger_with_receipt()
    summary = summarize_ledger(ledger)
    assert summary["organization_id"] == CANONICAL_PILOT_TENANT_ID
    assert summary["donors"] == 2
    assert summary["donations"] == 2
    assert summary["expenses"] >= 1
    assert summary["receipts"] == 1
    assert summary["attributions"] == 1
    assert summary["audit_events"] > 0


def test_build_operational_snapshot_combines_available_components(tmp_path: Path) -> None:
    bundle = StorageBundle(tmp_path / "storage")
    bundle.outbox.append(tenant_id=CANONICAL_PILOT_TENANT_ID, topic="receipt", payload={})
    workflow_store = InMemoryWorkflowStore()
    workflow_store.create(
        _instance(
            "wf_stale", state=WorkflowState.EVIDENCE_PENDING, status=WorkflowRunStatus.RUNNING
        )
    )
    ledger = _ledger_with_receipt()

    snapshot = build_operational_snapshot(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        storage=bundle,
        workflow_store=workflow_store,
        ledger=ledger,
    )

    assert snapshot["snapshot_kind"] == "impact_relay_operational_snapshot"
    assert snapshot["schema_version"] == "v1.0"
    assert snapshot["tenant_id"] == CANONICAL_PILOT_TENANT_ID
    assert snapshot["ok"] is False
    assert set(snapshot["components"]) == {"storage", "workflows", "outbox", "ledger"}
    assert snapshot["components"]["workflows"]["stale_running_without_lease"] == ["wf_stale"]
    assert snapshot["components"]["outbox"]["unpublished"] == 1
    assert snapshot["components"]["ledger"]["receipts"] == 1
