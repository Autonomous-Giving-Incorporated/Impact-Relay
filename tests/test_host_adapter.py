"""Host adapter: Hacker Dojo canonical session + nonprofit clone pattern."""

from __future__ import annotations

from pathlib import Path

from impact_relay.host import (
    CANONICAL_PILOT_TENANT_ID,
    HostSession,
    open_hacker_dojo_session,
    open_host_session,
)
from impact_relay.host.hacker_dojo import hacker_dojo_identity
from impact_relay.domain.types import ExpenseState


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def test_hacker_dojo_identity_constants() -> None:
    ident = hacker_dojo_identity()
    assert ident["tenant_id"] == "org_hacker_dojo"
    assert ident["policy_slug"] == "hacker-dojo"
    assert CANONICAL_PILOT_TENANT_ID == "org_hacker_dojo"


def test_hd_session_seed_approve_list_expenses(tmp_path: Path) -> None:
    data_dir = tmp_path / "hd"
    with open_hacker_dojo_session(data_dir) as session:
        assert session.tenant_id == CANONICAL_PILOT_TENANT_ID
        assert session.to_dict()["canonical_pilot"] is True
        pol = session.policy()
        assert pol.tenant_id == CANONICAL_PILOT_TENANT_ID

        seed = session.seed(expense_batch=BATCH)
        assert seed["ok"]
        assert seed["waiting"]

        waiting = session.list_waiting()
        assert waiting["count"] >= 1
        wid = waiting["cases"][0]["workflow_id"]

        approved = session.approve(
            workflow_id=wid,
            approver_id="finance@hackersdojo.org",
        )
        assert approved["ok"]
        assert approved["expense_state"] == ExpenseState.APPROVED.value

        expenses = session.list_expenses()
        assert any(e["id"] == approved["expense_id"] for e in expenses)
        exp = session.get_expense(approved["expense_id"])
        assert exp is not None
        assert exp["state"] == ExpenseState.APPROVED.value

        status = session.status()
        assert status["tenant_id"] == CANONICAL_PILOT_TENANT_ID
        assert status.get("entity_snapshot", {}).get("expenses", 0) >= 1

        check = session.check_rehydrate()
        assert check["ok"]


def test_other_nonprofit_session_is_isolated(tmp_path: Path) -> None:
    hd_dir = tmp_path / "hd"
    other_dir = tmp_path / "other"

    with open_hacker_dojo_session(hd_dir) as hd:
        hd.seed(expense_batch=BATCH)
        hd_expenses = hd.list_expenses()
        assert hd_expenses

    with open_host_session(
        other_dir,
        tenant_id="org_other_makerspace",
        display_name="Other Makerspace",
    ) as other:
        assert other.tenant_id == "org_other_makerspace"
        assert other.to_dict()["canonical_pilot"] is False
        # Different data-dir → no HD expenses leak
        assert other.list_expenses() == []
        reg = other.ensure_registered()
        assert reg["tenant_id"] == "org_other_makerspace"
        assert reg.get("template_source") == CANONICAL_PILOT_TENANT_ID


def test_agent_approver_rejected_via_host(tmp_path: Path) -> None:
    session = open_hacker_dojo_session(tmp_path / "hd2")
    session.seed(expense_batch=BATCH)
    out = session.approve(approver_id="agent:bot")
    assert out["ok"] is False
    assert out["error"] == "approver_must_be_human"
