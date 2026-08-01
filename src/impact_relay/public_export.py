"""Export privacy-safe public use-of-funds summaries.

Strips donor ids, donation references, operator emails, and any personal
identifiers from ledger receipts before publication on GitHub Pages.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from impact_relay.domain.types import UseOfFundsReceipt


def _money(value: Decimal | str) -> str:
    return f"{Decimal(str(value)):.2f}"


def receipt_to_public(receipt: UseOfFundsReceipt) -> dict[str, Any]:
    """Project a domain receipt into a public-safe document.

    Public receipt ids are derived from the content hash so re-running the
    pilot produces a stable Pages artifact without exposing internal random ids.
    """
    public_id = f"pub_{receipt.receipt_hash[:12]}"
    return {
        "receiptId": public_id,
        "organizationName": receipt.organization_name,
        "allocationName": receipt.allocation_name,
        "restrictionType": receipt.restriction_type,
        "category": receipt.category,
        "description": receipt.description,
        "vendor": receipt.vendor,
        "currency": receipt.currency,
        "grossAmount": _money(receipt.gross_amount),
        "attributedAmount": _money(receipt.attributed_amount),
        "purchaseDate": receipt.purchase_date,
        "verificationState": receipt.verification_state,
        "attributionMethod": receipt.attribution_method,
        "remainingDesignatedBalance": _money(receipt.remaining_designated_balance),
        "evidenceSummary": receipt.evidence_summary,
        "receiptHash": receipt.receipt_hash,
        "createdAt": receipt.created_at,
        "corrected": receipt.corrected,
        "correctionKind": receipt.correction_kind,
    }


def build_public_export(
    receipts: list[UseOfFundsReceipt],
    *,
    source: str = "hd_ir_001_pilot_fixture",
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Build the public Pages document from verified receipts."""
    public_receipts = [receipt_to_public(r) for r in receipts]
    total = sum((Decimal(r["attributedAmount"]) for r in public_receipts), Decimal("0"))
    currency = public_receipts[0]["currency"] if public_receipts else "USD"

    # Fail closed: never allow raw donor keys into the export payload.
    forbidden = ("donor_id", "donorId", "donation_reference", "donationReference", "approved_by")
    blob = str(public_receipts)
    for key in forbidden:
        if key in blob:
            raise ValueError(f"public export contains forbidden key residue: {key}")

    return {
        "version": "1.0.0",
        "updatedAt": updated_at or date.today().isoformat(),
        "source": source,
        "authority": "public_aggregate_only",
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "donorNamesAllowed": False,
            "individualDonorAttributionAllowed": False,
            "operatorIdentityAllowed": False,
        },
        "summary": {
            "receiptCount": len(public_receipts),
            "totalAttributed": _money(total),
            "currency": currency,
        },
        "receipts": public_receipts,
    }
