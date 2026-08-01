"""File-backed ledger command log + K17 fold rehydrate (pilot P1).

Easy local durability without PostgreSQL:
  <data_dir>/ledger_commands.jsonl

Rehydrate NEVER re-dispatches commands — only folds result_json.entities.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.types import (
    Allocation,
    Donation,
    DonationAllocation,
    Donor,
    DonorExpenseAttribution,
    EvidenceRecord,
    Expense,
    ExpenseAllocation,
    ExpenseState,
    Organization,
    RestrictionType,
    UseOfFundsReceipt,
    money,
)
from impact_relay.domain.types import AttributionMethod


class LedgerLogError(ValueError):
    """Corrupt or incomplete ledger command log."""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")


def entity_to_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=_json_default))


def snapshot_ledger_entities(ledger: Ledger) -> dict[str, Any]:
    """Full entity maps for fold rehydrate (K17)."""
    return {
        "donors": {k: entity_to_jsonable(v) for k, v in ledger.donors.items()},
        "donations": {k: entity_to_jsonable(v) for k, v in ledger.donations.items()},
        "allocations": {k: entity_to_jsonable(v) for k, v in ledger.allocations.items()},
        "donation_allocations": {
            k: entity_to_jsonable(v) for k, v in ledger.donation_allocations.items()
        },
        "expenses": {k: entity_to_jsonable(v) for k, v in ledger.expenses.items()},
        "expense_allocations": {
            k: entity_to_jsonable(v) for k, v in ledger.expense_allocations.items()
        },
        "evidence": {k: entity_to_jsonable(v) for k, v in ledger.evidence.items()},
        "attributions": {k: entity_to_jsonable(v) for k, v in ledger.attributions.items()},
        "receipts": {k: entity_to_jsonable(v) for k, v in ledger.receipts.items()},
        "receipt_snapshots": dict(ledger._receipt_snapshots),  # noqa: SLF001
        "expense_receipts": {
            k: list(v) for k, v in ledger._expense_receipts.items()  # noqa: SLF001
        },
        "external_index": {
            e.external_source_id: e.id
            for e in ledger.expenses.values()
            if e.external_source_id
        },
        "organization": entity_to_jsonable(ledger.organization),
    }


def build_result_json(
    *,
    command_type: str,
    idempotency_key: str,
    ledger: Ledger,
    output_refs: list[str],
    output_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "command_type": command_type,
        "idempotency_key": idempotency_key,
        "entities": snapshot_ledger_entities(ledger),
        "output_refs": list(output_refs),
        "output_payload": entity_to_jsonable(output_payload),
    }


def _money_field(d: dict[str, Any], key: str) -> Decimal:
    return money(d[key])


def _expense_from_dict(d: dict[str, Any]) -> Expense:
    return Expense(
        id=d["id"],
        organization_id=d["organization_id"],
        vendor=d["vendor"],
        amount=_money_field(d, "amount"),
        currency=d.get("currency", "USD"),
        purchase_date=d["purchase_date"],
        category=d["category"],
        description=d.get("description", ""),
        state=ExpenseState(d["state"] if not isinstance(d["state"], ExpenseState) else d["state"].value),
        external_source_id=d.get("external_source_id"),
        approved_by=d.get("approved_by"),
        reconciled_at=d.get("reconciled_at"),
        reversed_of_id=d.get("reversed_of_id"),
        supersedes_id=d.get("supersedes_id"),
        history_note=d.get("history_note"),
    )


def _receipt_from_dict(d: dict[str, Any]) -> UseOfFundsReceipt:
    return UseOfFundsReceipt(
        receipt_id=d["receipt_id"],
        type=d.get("type", "USE_OF_FUNDS"),
        organization_id=d["organization_id"],
        organization_name=d["organization_name"],
        donation_id=d["donation_id"],
        donor_id=d["donor_id"],
        allocation_id=d["allocation_id"],
        allocation_name=d["allocation_name"],
        restriction_type=d.get("restriction_type", ""),
        expenditure_expense_id=d["expenditure_expense_id"],
        vendor=d["vendor"],
        gross_amount=_money_field(d, "gross_amount"),
        attributed_amount=_money_field(d, "attributed_amount"),
        purchase_date=d["purchase_date"],
        category=d["category"],
        description=d.get("description", ""),
        verification_state=d["verification_state"],
        remaining_designated_balance=_money_field(d, "remaining_designated_balance"),
        attribution_method=d["attribution_method"],
        policy_version=d.get("policy_version", "v1.0"),
        approved_by=d.get("approved_by"),
        currency=d.get("currency", "USD"),
        receipt_hash=d["receipt_hash"],
        created_at=d["created_at"],
        corrected=bool(d.get("corrected", False)),
        corrects_receipt_id=d.get("corrects_receipt_id"),
        correction_kind=d.get("correction_kind"),
        evidence_summary=d.get("evidence_summary"),
        provenance=dict(d.get("provenance") or {}),
    )


def apply_result_json(ledger: Ledger, result: dict[str, Any]) -> None:
    """Fold result_json into ledger. Pure projection — no domain mutation APIs."""
    if not result or "entities" not in result:
        raise LedgerLogError("result_json missing entities")
    entities = result["entities"]

    # Organization (last write wins; must match ledger org)
    org = entities.get("organization")
    if org and org.get("id") and org["id"] != ledger.organization.id:
        raise LedgerLogError(
            f"org mismatch in log: {org.get('id')} vs {ledger.organization.id}"
        )

    for did, raw in (entities.get("donors") or {}).items():
        ledger.donors[did] = Donor(
            id=raw["id"],
            organization_id=raw["organization_id"],
            display_name=raw["display_name"],
        )

    for aid, raw in (entities.get("allocations") or {}).items():
        ledger.allocations[aid] = Allocation(
            id=raw["id"],
            organization_id=raw["organization_id"],
            name=raw["name"],
            purpose=raw.get("purpose", ""),
            restriction_type=RestrictionType(raw["restriction_type"]),
        )

    for did, raw in (entities.get("donations") or {}).items():
        ledger.donations[did] = Donation(
            id=raw["id"],
            organization_id=raw["organization_id"],
            donor_id=raw["donor_id"],
            amount=_money_field(raw, "amount"),
            currency=raw.get("currency", "USD"),
            cleared=bool(raw.get("cleared", True)),
            external_source_id=raw["external_source_id"],
            received_at=raw["received_at"],
        )

    for daid, raw in (entities.get("donation_allocations") or {}).items():
        ledger.donation_allocations[daid] = DonationAllocation(
            id=raw["id"],
            donation_id=raw["donation_id"],
            allocation_id=raw["allocation_id"],
            amount=_money_field(raw, "amount"),
        )

    for eid, raw in (entities.get("expenses") or {}).items():
        ledger.expenses[eid] = _expense_from_dict(raw)

    for eaid, raw in (entities.get("expense_allocations") or {}).items():
        ledger.expense_allocations[eaid] = ExpenseAllocation(
            id=raw["id"],
            expense_id=raw["expense_id"],
            allocation_id=raw["allocation_id"],
            amount=_money_field(raw, "amount"),
        )

    for evid, raw in (entities.get("evidence") or {}).items():
        ledger.evidence[evid] = EvidenceRecord(
            id=raw["id"],
            expense_id=raw["expense_id"],
            kind=raw.get("kind", "invoice"),
            summary=raw.get("summary", ""),
            donor_visible=bool(raw.get("donor_visible", True)),
        )

    for atid, raw in (entities.get("attributions") or {}).items():
        method = raw["method"]
        if not isinstance(method, AttributionMethod):
            method = AttributionMethod(method)
        ledger.attributions[atid] = DonorExpenseAttribution(
            id=raw["id"],
            donor_id=raw["donor_id"],
            donation_id=raw["donation_id"],
            expense_id=raw["expense_id"],
            allocation_id=raw["allocation_id"],
            attributed_amount=_money_field(raw, "attributed_amount"),
            method=method,
            policy_version=raw.get("policy_version", "v1.0"),
            confidence=raw.get("confidence", "policy"),
        )

    for rid, raw in (entities.get("receipts") or {}).items():
        ledger.receipts[rid] = _receipt_from_dict(raw)

    for rid, snap in (entities.get("receipt_snapshots") or {}).items():
        ledger._receipt_snapshots[rid] = snap  # noqa: SLF001

    for eid, rids in (entities.get("expense_receipts") or {}).items():
        ledger._expense_receipts[eid] = list(rids)  # noqa: SLF001


class FileLedgerCommandLog:
    """Append-only JSONL log: one successful money command per line."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seen: set[tuple[str, str]] = set()
        self._load_seen()

    def _load_seen(self) -> None:
        if not self.path.is_file():
            return
        for row in self.iter_rows():
            self._seen.add((row["tenant_id"], row["idempotency_key"]))

    def append(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        command_type: str,
        payload: dict[str, Any],
        result_json: dict[str, Any],
    ) -> None:
        key = (tenant_id, idempotency_key)
        with self._lock:
            if key in self._seen:
                return  # idempotent append
            if "entities" not in result_json:
                raise LedgerLogError("refuse to append result without entities")
            row = {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "command_type": command_type,
                "payload_json": payload,
                "result_json": result_json,
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=_json_default) + "\n")
            self._seen.add(key)

    def iter_rows(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerLogError(f"corrupt log line {line_no}: {exc}") from exc
                if tenant_id and row.get("tenant_id") != tenant_id:
                    continue
                rows.append(row)
        return rows

    def rehydrate(
        self,
        organization: Organization,
        *,
        base_ledger: Ledger | None = None,
    ) -> Ledger:
        """Empty or base ledger + fold all command results in file order."""
        ledger = base_ledger or Ledger(organization)
        if ledger.organization.id != organization.id:
            raise LedgerLogError("base ledger organization mismatch")
        for row in self.iter_rows(tenant_id=organization.id):
            result = row.get("result_json")
            if not result:
                raise LedgerLogError(
                    f"missing result_json for {row.get('idempotency_key')}"
                )
            apply_result_json(ledger, result)
        return ledger
