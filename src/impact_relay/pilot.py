"""Load fixture pilot data and run the HD-IR-001 use-of-funds path.

This is the documented library entry path used by the CLI and tests.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.types import (
    Allocation,
    AttributionMethod,
    Donation,
    Donor,
    EvidenceRecord,
    Expense,
    ExpenseState,
    Organization,
    RestrictionType,
    UseOfFundsReceipt,
)

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "pilot_hd_ir_001.json"


def load_fixture(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_FIXTURE
    with fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


def build_ledger_from_fixture(data: dict[str, Any]) -> Ledger:
    org = data["organization"]
    ledger = Ledger(
        Organization(
            id=org["id"],
            name=org["name"],
            policy_version=org.get("policy_version", "v1.0"),
        )
    )

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

    return ledger


def run_pilot(
    fixture_path: Path | str | None = None,
    *,
    approve: bool = True,
    reconcile: bool = True,
    finance_actor: str = "finance.operator@hackersdojo.example",
) -> tuple[Ledger, list[UseOfFundsReceipt]]:
    """Execute the pilot: import → allocate → approve → attribute → publish receipts.

    Returns the ledger and all published use-of-funds receipts.
    """
    data = load_fixture(fixture_path)
    ledger = build_ledger_from_fixture(data)

    receipts: list[UseOfFundsReceipt] = []
    publish_plan = data.get("publish", [])

    # Approve / reconcile each expense referenced in publish plan (or all expenses).
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


def receipts_to_jsonable(receipts: list[UseOfFundsReceipt]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in receipts]
