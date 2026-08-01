"""Fixture loaders and multi-stage pilot runners (HD-IR-001 + phases 2–6)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import Platform, TenantWorkspace
from impact_relay.domain.types import (
    Allocation,
    AssetLifecycle,
    AttributionMethod,
    ConsentRecord,
    Donation,
    Donor,
    EvidenceRecord,
    Expense,
    ExpenseState,
    FundedAsset,
    ImpactEvent,
    ImpactEventState,
    NotificationChannel,
    NotificationPreference,
    Organization,
    Program,
    RestrictionType,
    UseOfFundsReceipt,
)

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "pilot_hd_ir_001.json"
DEFAULT_ALL_PHASES_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "pilot_all_phases.json"
)


def load_fixture(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_FIXTURE
    with fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


def build_ledger_from_fixture(data: dict[str, Any]) -> Ledger:
    """Build a single-org ledger from legacy HD-IR-001 fixture shape."""
    org = data["organization"]
    ledger = Ledger(
        Organization(
            id=org["id"],
            name=org["name"],
            policy_version=org.get("policy_version", "v1.0"),
        )
    )
    _load_donors_allocations_donations_expenses(ledger, data)
    return ledger


def _load_donors_allocations_donations_expenses(
    ledger: Ledger, data: dict[str, Any]
) -> None:
    for d in data.get("donors", []):
        ledger.register_donor(
            Donor(
                id=d["id"],
                organization_id=ledger.organization.id,
                display_name=d["display_name"],
            )
        )

    for a in data.get("allocations", []):
        ledger.register_allocation(
            Allocation(
                id=a["id"],
                organization_id=ledger.organization.id,
                name=a["name"],
                purpose=a.get("purpose", ""),
                restriction_type=RestrictionType(a["restriction_type"]),
            )
        )

    for don in data.get("donations", []):
        ledger.import_donation(
            Donation(
                id=don["id"],
                organization_id=ledger.organization.id,
                donor_id=don["donor_id"],
                amount=Decimal(str(don["amount"])),
                currency=don.get("currency", "USD"),
                cleared=bool(don.get("cleared", True)),
                external_source_id=don["external_source_id"],
                received_at=don["received_at"],
            )
        )
        for da in don.get("allocations", []):
            ledger.assign_donation_allocation(
                donation_id=don["id"],
                allocation_id=da["allocation_id"],
                amount=Decimal(str(da["amount"])),
                donation_allocation_id=da.get("id"),
            )

    for exp in data.get("expenses", []):
        ledger.import_expense(
            Expense(
                id=exp["id"],
                organization_id=ledger.organization.id,
                vendor=exp["vendor"],
                amount=Decimal(str(exp["amount"])),
                currency=exp.get("currency", "USD"),
                purchase_date=exp["purchase_date"],
                category=exp["category"],
                description=exp["description"],
                state=ExpenseState(exp.get("state", "IMPORTED")),
                external_source_id=exp.get("external_source_id"),
            )
        )
        splits = exp.get("allocation_splits") or []
        if splits:
            ledger.allocate_expense_splits(
                expense_id=exp["id"],
                splits=[(s["allocation_id"], Decimal(str(s["amount"]))) for s in splits],
            )
        elif "allocation_id" in exp:
            ledger.allocate_expense(
                expense_id=exp["id"],
                allocation_id=exp["allocation_id"],
                amount=Decimal(str(exp["amount"])),
            )
        for ev in exp.get("evidence", []):
            ledger.attach_evidence(
                EvidenceRecord(
                    id=ev["id"],
                    expense_id=exp["id"],
                    kind=ev.get("kind", "invoice"),
                    summary=ev["summary"],
                    donor_visible=bool(ev.get("donor_visible", True)),
                )
            )


def run_pilot(
    fixture_path: Path | str | None = None,
    *,
    approve: bool = True,
    reconcile: bool = True,
    finance_actor: str = "finance.operator@hackersdojo.example",
) -> tuple[Ledger, list[UseOfFundsReceipt]]:
    """HD-IR-001 path: import → allocate → approve → attribute → publish UOF receipts."""
    data = load_fixture(fixture_path)
    # Support both legacy single-org and multi-org fixtures for UOF-only.
    if "organizations" in data:
        platform, _payload = run_all_phases_pilot(
            fixture_path,
            finance_actor=finance_actor,
            reconcile=reconcile,
        )
        primary_id = data["organizations"][0]["id"]
        ws = platform.get_workspace(primary_id)
        uof = [r for r in ws.ledger.receipts.values() if not r.corrected]
        return ws.ledger, uof

    ledger = build_ledger_from_fixture(data)
    receipts: list[UseOfFundsReceipt] = []
    publish_plan = data.get("publish", [])
    expense_ids = {p["expense_id"] for p in publish_plan} if publish_plan else set(
        ledger.expenses.keys()
    )

    if approve:
        for eid in expense_ids:
            exp = ledger.expenses[eid]
            if exp.state not in (ExpenseState.APPROVED, ExpenseState.RECONCILED):
                ledger.approve_expense(eid, approved_by=finance_actor)
            if reconcile and ledger.expenses[eid].state == ExpenseState.APPROVED:
                ledger.reconcile_expense(eid, actor=finance_actor)

    for step in publish_plan:
        method = AttributionMethod(step["attribution_method"])
        attributed = step.get("attributed_amount")
        ledger.attribute_donor_to_expense(
            donor_id=step["donor_id"],
            donation_id=step["donation_id"],
            expense_id=step["expense_id"],
            allocation_id=step["allocation_id"],
            method=method,
            attributed_amount=Decimal(str(attributed)) if attributed is not None else None,
        )
        receipt = ledger.publish_use_of_funds_receipt(
            expense_id=step["expense_id"],
            donation_id=step["donation_id"],
            allocation_id=step["allocation_id"],
            actor=finance_actor,
            created_at=step.get("created_at"),
        )
        receipts.append(receipt)

    return ledger, receipts


def _populate_workspace_from_org_block(
    ws: TenantWorkspace,
    block: dict[str, Any],
    *,
    finance_actor: str,
    reconcile: bool,
) -> dict[str, Any]:
    """Drive one org through UOF → impact → notify stages. Returns stage artifacts."""
    _load_donors_allocations_donations_expenses(ws.ledger, block)
    ledger = ws.ledger
    stage: dict[str, Any] = {
        "organization_id": ledger.organization.id,
        "use_of_funds_receipts": [],
        "impact_receipts": [],
        "notification_intents": [],
        "notification_deliveries": [],
        "donor_dashboards": {},
    }

    publish_uof = block.get("publish_uof") or block.get("publish") or []
    expense_ids = {p["expense_id"] for p in publish_uof} if publish_uof else set(
        ledger.expenses.keys()
    )
    for eid in expense_ids:
        exp = ledger.expenses[eid]
        if exp.state not in (ExpenseState.APPROVED, ExpenseState.RECONCILED):
            ledger.approve_expense(eid, approved_by=finance_actor)
        if reconcile and ledger.expenses[eid].state == ExpenseState.APPROVED:
            ledger.reconcile_expense(eid, actor=finance_actor)

    for step in publish_uof:
        method = AttributionMethod(step["attribution_method"])
        attributed = step.get("attributed_amount")
        ledger.attribute_donor_to_expense(
            donor_id=step["donor_id"],
            donation_id=step["donation_id"],
            expense_id=step["expense_id"],
            allocation_id=step["allocation_id"],
            method=method,
            attributed_amount=Decimal(str(attributed)) if attributed is not None else None,
        )
        receipt = ledger.publish_use_of_funds_receipt(
            expense_id=step["expense_id"],
            donation_id=step["donation_id"],
            allocation_id=step["allocation_id"],
            actor=finance_actor,
            created_at=step.get("created_at"),
        )
        stage["use_of_funds_receipts"].append(receipt.to_dict())

    impact_svc = ws.impact()
    for p in block.get("programs", []):
        impact_svc.register_program(
            Program(
                id=p["id"],
                organization_id=ledger.organization.id,
                name=p["name"],
                active=bool(p.get("active", True)),
            )
        )
    for a in block.get("funded_assets", []):
        asset = impact_svc.register_funded_asset(
            FundedAsset(
                id=a["id"],
                organization_id=ledger.organization.id,
                name=a["name"],
                expense_id=a["expense_id"],
                allocation_id=a["allocation_id"],
                lifecycle=AssetLifecycle(a.get("lifecycle", "PROCURED")),
            )
        )
        if asset.lifecycle == AssetLifecycle.DEPLOYED:
            impact_svc.deploy_asset(asset.id)

    for ie in block.get("impact_events", []):
        event = ImpactEvent(
            id=ie["id"],
            organization_id=ledger.organization.id,
            program_id=ie["program_id"],
            event_type=ie["event_type"],
            event_date=ie["event_date"],
            participants=int(ie["participants"]),
            state=ImpactEventState(ie.get("state", "SUBMITTED")),
            funded_asset_ids=tuple(ie.get("funded_asset_ids") or ()),
            expense_ids=tuple(ie.get("expense_ids") or ()),
            description=ie.get("description", ""),
        )
        impact_svc.submit_impact_event(event)
        if ie.get("verify", True):
            impact_svc.verify_impact_event(
                ie["id"], verified_by=ie.get("verified_by", finance_actor)
            )
        if ie.get("publish", True):
            impact_receipts = impact_svc.publish_impact_receipts(
                ie["id"],
                actor=finance_actor,
                created_at=ie.get("created_at"),
            )
            stage["impact_receipts"].extend(r.to_dict() for r in impact_receipts)

    notify = ws.notifications()
    for c in block.get("consent", []):
        notify.record_consent(
            ConsentRecord(
                donor_id=c["donor_id"],
                organization_id=ledger.organization.id,
                channel=NotificationChannel(c["channel"]),
                granted=bool(c["granted"]),
                provenance=c.get("provenance", "fixture"),
                recorded_at=c.get("recorded_at", "2026-01-01T00:00:00+00:00"),
            )
        )
    for pref in block.get("preferences", []):
        notify.set_preference(
            NotificationPreference(
                donor_id=pref["donor_id"],
                organization_id=ledger.organization.id,
                channel=NotificationChannel(pref["channel"]),
                enabled=bool(pref.get("enabled", True)),
                topics=tuple(pref.get("topics") or ()),
                cadence=pref.get("cadence", "immediate"),
            )
        )

    notify_cfg = block.get("notify") or {}
    uof_channel = NotificationChannel(notify_cfg.get("uof_channel", "EMAIL"))
    impact_channel = NotificationChannel(notify_cfg.get("impact_channel", "EMAIL"))

    for r in stage["use_of_funds_receipts"]:
        if r.get("corrected"):
            continue
        intent = notify.evaluate_for_use_of_funds(r["receipt_id"], channel=uof_channel)
        # re-fetch status after deliver
        intent = notify.ws.intents[intent.id]

    for ir in stage["impact_receipts"]:
        intent = notify.evaluate_for_impact(ir["receipt_id"], channel=impact_channel)
        intent = notify.ws.intents[intent.id]

    stage["notification_intents"] = notify.intents_as_dicts()
    stage["notification_deliveries"] = notify.deliveries_as_dicts()

    reads = ws.donor_reads()
    for d in block.get("donors", []):
        stage["donor_dashboards"][d["id"]] = reads.donor_dashboard(d["id"])

    return stage


def run_all_phases_pilot(
    fixture_path: Path | str | None = None,
    *,
    finance_actor: str = "finance.operator@hackersdojo.example",
    reconcile: bool = True,
) -> tuple[Platform, dict[str, Any]]:
    """Multi-tenant multi-stage pilot: UOF → impact → notify → donor read.

    Documented library entry for phases 2–6 machine verification.
    """
    path = Path(fixture_path) if fixture_path else DEFAULT_ALL_PHASES_FIXTURE
    data = load_fixture(path)
    platform = Platform()

    if "organizations" not in data:
        # Wrap legacy single-org fixture
        org_block = {
            **data,
            "id": data["organization"]["id"],
            "name": data["organization"]["name"],
            "policy_version": data["organization"].get("policy_version", "v1.0"),
            "publish_uof": data.get("publish", []),
        }
        org_blocks = [org_block]
        org_meta = data["organization"]
        orgs_for_register = [org_meta]
    else:
        org_blocks = data["organizations"]
        orgs_for_register = org_blocks

    stages: list[dict[str, Any]] = []
    for block, meta in zip(org_blocks, orgs_for_register, strict=False):
        org = Organization(
            id=meta["id"] if "id" in meta else block["id"],
            name=meta.get("name", block.get("name", "Org")),
            policy_version=meta.get("policy_version", block.get("policy_version", "v1.0")),
        )
        # org block may embed id/name at top level in multi-org fixture
        if "id" in block:
            org = Organization(
                id=block["id"],
                name=block["name"],
                policy_version=block.get("policy_version", "v1.0"),
            )
        ws = platform.register_organization(org)
        stage = _populate_workspace_from_org_block(
            ws, block, finance_actor=finance_actor, reconcile=reconcile
        )
        stages.append(stage)

    primary = stages[0] if stages else {}
    payload = {
        "meta": data.get("meta", {}),
        "organizations": [s["organization_id"] for s in stages],
        "stages": stages,
        "primary": {
            "organization_id": primary.get("organization_id"),
            "use_of_funds_receipts": primary.get("use_of_funds_receipts", []),
            "impact_receipts": primary.get("impact_receipts", []),
            "notification_intents": primary.get("notification_intents", []),
            "notification_deliveries": primary.get("notification_deliveries", []),
            "donor_dashboard_alice": (primary.get("donor_dashboards") or {}).get(
                "donor_alice"
            ),
        },
    }
    return platform, payload


def receipts_to_jsonable(receipts: list[UseOfFundsReceipt]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in receipts]
