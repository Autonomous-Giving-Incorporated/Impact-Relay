"""Email preview + independent send approval + fixture delivery."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.expense_workflow import (
    LedgerCommandExecutor,
    run_expense_approval_slice,
)
from impact_relay.agents.notification_composer import (
    assert_preview_matches_receipt,
    compose_email_from_uof,
)
from impact_relay.agents.types import (
    AgentCommand,
    ApprovalReceipt,
    AuthorityLevel,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _ledger_without_expenses():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def _batch_rows() -> list[dict]:
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]


def _publish_spec() -> list[dict]:
    return [
        {
            "donor_id": "donor_alice",
            "donation_id": "don_1000_alice",
            "allocation_id": "alloc_community_hardware",
            "attribution_method": "DIRECT_RESTRICTED",
            "attributed_amount": "720.00",
            "created_at": "2026-08-12T12:00:00+00:00",
        }
    ]


def test_email_preview_is_receipt_projection() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_spec(),
        send_email=False,
    )
    rec = result.receipts[0]
    preview = compose_email_from_uof(rec)
    assert_preview_matches_receipt(preview, rec)
    assert "720.00" in preview.body_text
    assert rec.vendor in preview.body_text
    assert rec.receipt_hash[:12] in preview.body_text
    # Composer must not invent a different amount
    assert preview.facts["attributed_amount"] == f"{rec.attributed_amount:.2f}"


def test_tampered_preview_rejected() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_spec(),
    )
    rec = result.receipts[0]
    preview = compose_email_from_uof(rec)
    # Mutate facts off-band
    bad = preview.to_dict()
    bad["facts"] = {**preview.facts, "attributed_amount": "99999.00"}
    from impact_relay.agents.notification_composer import EmailPreview

    tampered = EmailPreview(**{k: bad[k] for k in EmailPreview.__dataclass_fields__})
    with pytest.raises(ValueError, match="facts do not match"):
        assert_preview_matches_receipt(tampered, rec)


def test_full_slice_with_email_delivery() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        communications_approver_id="comms.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_spec(),
        send_email=True,
    )
    assert result.workflow_state == WorkflowState.DELIVERED
    assert result.email_previews
    assert result.delivery_refs
    assert result.delivery_refs[0]["status"] == "DELIVERED"
    # Two L3 approvals: finance publish path + send
    roles = {a.approver_role for a in result.approvals}
    assert "finance_approver" in roles or any(
        a.approver_id == "finance.approver@hackersdojo.example" for a in result.approvals
    )
    assert any(a.approver_role == "communications_approver" for a in result.approvals)
    send_execs = [e for e in result.executions if e.command_type == "send_notification"]
    assert send_execs and send_execs[0].status == "SUCCEEDED"
    assert send_execs[0].approval_id is not None


def test_send_without_approval_fails() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_spec(),
        send_email=False,
    )
    rec = result.receipts[0]
    preview = compose_email_from_uof(rec)
    ws = TenantWorkspace(ledger.organization, ledger=ledger)
    ex = LedgerCommandExecutor(ledger, workspace=ws)
    ex.register_preview(preview)
    with pytest.raises(AuthorityError, match="requires human"):
        ex.execute(
            AgentCommand(
                command_type="send_notification",
                tenant_id=ledger.organization.id,
                payload={
                    "preview_id": preview.preview_id,
                    "receipt_id": rec.receipt_id,
                    "content_hash": preview.content_hash,
                    "receipt_hash": rec.receipt_hash,
                    "channel": "EMAIL",
                },
                required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            )
        )


def test_send_requires_matching_content_hash() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_spec(),
    )
    rec = result.receipts[0]
    preview = compose_email_from_uof(rec)
    ws = TenantWorkspace(ledger.organization, ledger=ledger)
    ex = LedgerCommandExecutor(ledger, workspace=ws)
    ex.register_preview(preview)
    cmd = AgentCommand(
        command_type="send_notification",
        tenant_id=ledger.organization.id,
        payload={
            "preview_id": preview.preview_id,
            "receipt_id": rec.receipt_id,
            "content_hash": "deadbeef",
            "receipt_hash": rec.receipt_hash,
            "channel": "EMAIL",
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
    )
    approval = ApprovalReceipt(
        approval_id="a1",
        tenant_id=ledger.organization.id,
        proposal_id="p1",
        command_idempotency_key=cmd.idempotency_key,
        decision="APPROVE",
        approver_id="comms@example.org",
        approver_role="communications_approver",
        approved_at=utc_now_iso(),
    )
    receipt = ex.execute(cmd, approval=approval, agent_name="notification_composer")
    assert receipt.status == "FAILED"
    assert "content_hash" in (receipt.error or "")
