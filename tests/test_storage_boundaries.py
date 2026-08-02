"""P1 storage: multi-tenant ports, HD canonical, template clone, isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from impact_relay.domain.ledger_log import build_result_json, snapshot_ledger_entities
from impact_relay.domain.types import ExpenseState
from impact_relay.pilot import run_pilot
from impact_relay.storage import (
    CANONICAL_PILOT_TENANT_ID,
    open_storage,
)
from impact_relay.storage.objects import ObjectStorageError
from impact_relay.storage.template import (
    CANONICAL_POLICY_SLUG,
    clone_tenant_from_hacker_dojo,
    ensure_canonical_hacker_dojo_tenant,
    register_cloned_tenant,
)


def test_canonical_ids() -> None:
    assert CANONICAL_PILOT_TENANT_ID == "org_hacker_dojo"
    assert CANONICAL_POLICY_SLUG == "hacker-dojo"


def test_open_storage_sqlite_and_register_hd(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "st")
    rec = ensure_canonical_hacker_dojo_tenant(store)
    assert rec.tenant_id == CANONICAL_PILOT_TENANT_ID
    assert rec.display_name == "Hacker Dojo"
    assert rec.policy_slug == "hacker-dojo"
    again = ensure_canonical_hacker_dojo_tenant(store)
    assert again.tenant_id == rec.tenant_id
    listed = store.tenants.list()
    assert any(t.tenant_id == CANONICAL_PILOT_TENANT_ID for t in listed)


def test_clone_other_nonprofit_isolated(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "st2")
    ensure_canonical_hacker_dojo_tenant(store)
    policy, rec = register_cloned_tenant(
        store,
        tenant_id="org_other_makerspace",
        display_name="Other Makerspace",
    )
    assert policy.tenant_id == "org_other_makerspace"
    assert policy.display_name == "Other Makerspace"
    # Same L3 set as HD template (shared platform rules)
    assert "reverse_expense" in policy.authority.l3_command_types
    assert "approve_expense" in policy.authority.l3_command_types
    assert rec.template_source == CANONICAL_PILOT_TENANT_ID

    hd = store.tenants.get(CANONICAL_PILOT_TENANT_ID)
    other = store.tenants.get("org_other_makerspace")
    assert hd is not None and other is not None
    assert hd.tenant_id != other.tenant_id


def test_clone_policy_does_not_mutate_hd() -> None:
    other = clone_tenant_from_hacker_dojo(tenant_id="org_x", display_name="X")
    hd = clone_tenant_from_hacker_dojo(tenant_id=CANONICAL_PILOT_TENANT_ID, display_name="ignored")
    assert other.tenant_id == "org_x"
    assert hd.tenant_id == CANONICAL_PILOT_TENANT_ID
    assert hd.display_name == "Hacker Dojo"


def test_object_storage_tenant_isolation(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "st3")
    store.objects.put(
        CANONICAL_PILOT_TENANT_ID,
        "evidence/inv-1.pdf",
        b"%PDF-fake",
        content_type="application/pdf",
    )
    assert store.objects.get(CANONICAL_PILOT_TENANT_ID, "evidence/inv-1.pdf") == b"%PDF-fake"
    # Other tenant cannot read HD object by same key path in their namespace
    assert store.objects.get("org_other_makerspace", "evidence/inv-1.pdf") is None
    with pytest.raises(ObjectStorageError):
        store.objects.put(CANONICAL_PILOT_TENANT_ID, "../escape", b"x")
    with pytest.raises(ObjectStorageError):
        store.objects.put("bad/tenant", "k", b"x")


def test_sql_command_log_rehydrate_hd_expense(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "st4")
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, _receipts = run_pilot()
    assert ledger.organization.id == CANONICAL_PILOT_TENANT_ID
    snap = snapshot_ledger_entities(ledger)
    result = build_result_json(
        command_type="approve_expense",
        idempotency_key="approve:exp_soldering_842:test",
        ledger=ledger,
        output_refs=["exp_soldering_842"],
        output_payload={},
    )
    # fold uses entities from full snapshot
    result["entities"] = snap
    store.command_log.append(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        idempotency_key="approve:exp_soldering_842:test",
        command_type="approve_expense",
        payload={"expense_id": "exp_soldering_842"},
        result_json=result,
    )
    import copy

    from impact_relay.pilot import build_ledger_from_fixture, load_fixture

    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    empty = build_ledger_from_fixture(data)
    rebuilt = store.command_log.rehydrate(empty.organization, base_ledger=empty)
    assert "exp_soldering_842" in rebuilt.expenses
    assert rebuilt.expenses["exp_soldering_842"].state in (
        ExpenseState.APPROVED,
        ExpenseState.RECONCILED,
    )


def test_outbox_append_claim_publish_tenant_scoped(tmp_path: Path) -> None:
    store = open_storage(tmp_path / "st5")
    ensure_canonical_hacker_dojo_tenant(store)
    ev = store.outbox.append(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        topic="receipt.published",
        payload={"receipt_id": "uof_1"},
    )
    store.outbox.append(
        tenant_id="org_other_makerspace",
        topic="receipt.published",
        payload={"receipt_id": "uof_other"},
    )
    batch = store.outbox.claim_unpublished(limit=10)
    assert len(batch) >= 2
    store.outbox.mark_published(ev.event_id)
    hd_only = store.outbox.list_for_tenant(CANONICAL_PILOT_TENANT_ID)
    assert all(e.tenant_id == CANONICAL_PILOT_TENANT_ID for e in hd_only)
    assert any(e.event_id == ev.event_id and e.published_at for e in hd_only)


def test_postgres_placeholder_rewrite_skips_quoted_literals() -> None:
    """A blanket ?->%s replace would corrupt a literal containing a question mark."""
    from impact_relay.storage.sql import to_postgres_placeholders as convert

    assert convert("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
    assert convert("SELECT 1") == "SELECT 1"
    # ? inside a literal must survive untouched
    assert (
        convert("SELECT * FROM t WHERE note='why?' AND a=?")
        == "SELECT * FROM t WHERE note='why?' AND a=%s"
    )
    # '' is an escaped quote and does not end the literal
    assert convert("SELECT 'it''s ok?', ?") == "SELECT 'it''s ok?', %s"
