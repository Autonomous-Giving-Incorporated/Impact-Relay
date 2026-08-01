"""PR-L2: scheduled digest workflow skeleton."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import ApprovalReceipt, WorkflowState, utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.workflows.ops import signal_approval_and_pump
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.scheduled_digest import assemble_digests
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import WorkflowRunStatus, WorkflowType
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "impact_events_pilot.json"


def _rt():
    data = load_fixture()
    ledger = build_ledger_from_fixture(data)
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    return WorkflowRuntime(store, binding), store, ledger


def test_assemble_digests_privacy_ok() -> None:
    digests = assemble_digests(events_path=FIXTURE)
    assert digests["privacy"]["piiAllowed"] is False
    assert digests["privacy"]["donorNamesAllowed"] is False
    assert digests["summary"]["eventCount"] >= 1


def test_assemble_rejects_pii_events() -> None:
    bad = {
        "meta": {"source": "test"},
        "events": [
            {
                "title": "Workshop",
                "class": "workshop",
                "occurredOn": "2026-01-01",
                "attendeeCountPublic": 3,
                "impactSummary": "ok",
                "attendeeNames": ["Alice"],
            }
        ],
    }
    with pytest.raises(Exception):
        assemble_digests(events_doc=bad)


def test_scheduled_digest_auto_complete() -> None:
    rt, store, ledger = _rt()
    tenant = ledger.organization.id
    inst = rt.start_scheduled_digest(
        tenant_id=tenant,
        period_key="2026-08",
        events_path=str(FIXTURE),
        require_approval=False,
    )
    assert inst.workflow_type == WorkflowType.SCHEDULED_DIGEST
    assert inst.business_key == "digest:2026-08"

    worker = WorkflowWorker(rt, WorkerConfig(worker_id="dig-w", poll_interval_seconds=0.0))
    for _ in range(10):
        worker.tick()
        cur = store.get(tenant, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.COMPLETED:
            break
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    assert cur.run_status == WorkflowRunStatus.COMPLETED
    assert cur.workflow_state == WorkflowState.DELIVERED
    assert cur.context.get("privacy_ok") is True
    assert cur.context.get("digests", {}).get("summary", {}).get("eventCount") >= 1


def test_scheduled_digest_require_approval_and_ack() -> None:
    rt, store, ledger = _rt()
    tenant = ledger.organization.id
    inst = rt.start_scheduled_digest(
        tenant_id=tenant,
        period_key="2026-08-ack",
        events_path=str(FIXTURE),
        require_approval=True,
    )
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="dig-a", poll_interval_seconds=0.0))
    for _ in range(5):
        worker.tick()
        cur = store.get(tenant, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.WAITING_SIGNAL:
            break
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    assert cur.workflow_state == WorkflowState.PUBLICATION_PENDING
    assert cur.context.get("digests")  # assembled before wait
    key = cur.context["wait"]["command_idempotency_key"]
    assert key.startswith("ack_digest:")

    with pytest.raises(AuthorityError):
        rt.signal_approval(
            tenant_id=tenant,
            workflow_id=inst.workflow_id,
            approval=ApprovalReceipt(
                approval_id="bad",
                tenant_id=tenant,
                proposal_id="p",
                command_idempotency_key=key,
                decision="APPROVE",
                approver_id="agent:bot",
                approver_role="comms",
                approved_at=utc_now_iso(),
                rationale="nope",
            ),
        )

    approval = ApprovalReceipt(
        approval_id="ap_dig",
        tenant_id=tenant,
        proposal_id="p",
        command_idempotency_key=key,
        decision="APPROVE",
        approver_id="comms@hackersdojo.example",
        approver_role="comms_approver",
        approved_at=utc_now_iso(),
        rationale="publish digests",
    )
    # signal_approval_and_pump uses expense human gate for generic signals;
    # for digests use runtime signal + worker
    rt.signal_approval(
        tenant_id=tenant, workflow_id=inst.workflow_id, approval=approval
    )
    for _ in range(10):
        worker.tick()
        cur = store.get(tenant, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.COMPLETED:
            break
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    assert cur.run_status == WorkflowRunStatus.COMPLETED
    assert cur.workflow_state == WorkflowState.DELIVERED
    assert cur.context.get("digest_approved_by") == "comms@hackersdojo.example"


def test_scheduled_digest_future_next_run_not_claimed_yet() -> None:
    rt, store, ledger = _rt()
    tenant = ledger.organization.id
    future = datetime.now(timezone.utc) + timedelta(days=7)
    inst = rt.start_scheduled_digest(
        tenant_id=tenant,
        period_key="future",
        events_path=str(FIXTURE),
        next_run_at=future,
    )
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="dig-f", poll_interval_seconds=0.0))
    r = worker.tick()
    assert r.claimed == 0
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    assert cur.run_status == WorkflowRunStatus.PENDING
    assert cur.workflow_state == WorkflowState.RECEIVED
