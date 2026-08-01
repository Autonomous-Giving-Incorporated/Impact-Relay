"""Privacy-safe public export tests for HD-IR-002."""

from __future__ import annotations

import json

from impact_relay.pilot import run_pilot
from impact_relay.public_export import build_public_export, receipt_to_public


def test_public_export_strips_donor_and_operator_identity() -> None:
    _ledger, receipts = run_pilot()
    assert receipts
    public = build_public_export(receipts)
    blob = json.dumps(public)

    assert "donor_alice" not in blob
    assert "Alice" not in blob
    assert "donor_id" not in blob
    assert "donation_reference" not in blob
    assert "finance.operator" not in blob
    assert public["privacy"]["piiAllowed"] is False
    assert public["privacy"]["donorNamesAllowed"] is False
    assert public["summary"]["receiptCount"] == len(receipts)
    assert public["receipts"][0]["allocationName"] == "Community Hardware Fund"
    assert public["receipts"][0]["verificationState"] == "RECONCILED"


def test_receipt_to_public_has_required_transparency_fields() -> None:
    _ledger, receipts = run_pilot()
    row = receipt_to_public(receipts[0])
    for key in (
        "receiptId",
        "allocationName",
        "attributedAmount",
        "verificationState",
        "attributionMethod",
        "receiptHash",
    ):
        assert key in row
    assert "donor_id" not in row
    assert "donation_reference" not in row


def test_cli_write_public(tmp_path) -> None:
    from impact_relay.cli import main

    out = tmp_path / "use-of-funds-public.json"
    code = main(["--write-public", str(out), "--public-only"])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["receiptCount"] >= 1
    assert data["authority"] == "public_aggregate_only"
