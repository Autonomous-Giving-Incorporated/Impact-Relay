"""Ledger entity repository: HD pilot roundtrip + multi-tenant isolation."""

from __future__ import annotations

from pathlib import Path

from impact_relay.domain.types import ExpenseState, Organization
from impact_relay.pilot import run_pilot
from impact_relay.storage import (
    CANONICAL_PILOT_TENANT_ID,
    open_storage,
)
from impact_relay.storage.template import (
    ensure_canonical_hacker_dojo_tenant,
    register_cloned_tenant,
)


def test_hd_pilot_save_load_roundtrip(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "led")
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, receipts = run_pilot()
    assert ledger.organization.id == CANONICAL_PILOT_TENANT_ID
    store.ledger.save_ledger(ledger)

    loaded = store.ledger.load_ledger(tenant_id=CANONICAL_PILOT_TENANT_ID)
    assert loaded is not None
    assert loaded.organization.id == CANONICAL_PILOT_TENANT_ID
    assert set(loaded.expenses.keys()) == set(ledger.expenses.keys())
    assert set(loaded.receipts.keys()) == set(ledger.receipts.keys())
    # Prior receipt hash immutable after load
    rid = receipts[0].receipt_id
    assert loaded.receipts[rid].receipt_hash == receipts[0].receipt_hash
    assert loaded.expenses["exp_soldering_842"].state in (
        ExpenseState.APPROVED,
        ExpenseState.RECONCILED,
    )


def test_list_expenses_and_receipts_for_host_app(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "led2")
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, receipts = run_pilot()
    store.ledger.save_ledger(ledger)

    expenses = store.ledger.list_expenses(CANONICAL_PILOT_TENANT_ID)
    assert any(e["id"] == "exp_soldering_842" for e in expenses)
    exp = store.ledger.get_expense(CANONICAL_PILOT_TENANT_ID, "exp_soldering_842")
    assert exp is not None
    assert exp["organization_id"] == CANONICAL_PILOT_TENANT_ID

    rid = receipts[0].receipt_id
    r = store.ledger.get_receipt(CANONICAL_PILOT_TENANT_ID, rid)
    assert r is not None
    assert r["receipt_id"] == rid
    assert r["receipt_hash"] == receipts[0].receipt_hash
    listed = store.ledger.list_receipts(CANONICAL_PILOT_TENANT_ID)
    assert any(x["receipt_id"] == rid for x in listed)


def test_tenant_isolation_other_nonprofit_empty(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "led3")
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, _ = run_pilot()
    store.ledger.save_ledger(ledger)
    register_cloned_tenant(
        store,
        tenant_id="org_other_makerspace",
        display_name="Other Makerspace",
    )
    # Other tenant has no entities
    assert store.ledger.load_ledger(tenant_id="org_other_makerspace") is None
    assert store.ledger.list_expenses("org_other_makerspace") == []
    assert (
        store.ledger.get_expense("org_other_makerspace", "exp_soldering_842") is None
    )


def test_save_replaces_snapshot(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "led4")
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, _ = run_pilot()
    store.ledger.save_ledger(ledger)
    # Empty-ish org: save after clearing expenses in a fresh ledger won't happen
    # via domain API; re-save same pilot is idempotent
    store.ledger.save_ledger(ledger)
    loaded = store.ledger.load_ledger(
        Organization(
            id=CANONICAL_PILOT_TENANT_ID,
            name="Hacker Dojo",
            policy_version="v1.0",
        )
    )
    assert loaded is not None
    assert "exp_soldering_842" in loaded.expenses
