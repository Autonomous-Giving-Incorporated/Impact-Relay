"""CLI entry path for the HD-IR-001 pilot.

Usage:
  impact-relay-pilot
  impact-relay-pilot --fixture fixtures/pilot_hd_ir_001.json
  python -m impact_relay.cli
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.pilot import receipts_to_jsonable, run_pilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HD-IR-001 use-of-funds pilot — import fixture and publish receipts"
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Path to pilot fixture JSON (default: fixtures/pilot_hd_ir_001.json)",
    )
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="Approve expenses but do not mark RECONCILED",
    )
    parser.add_argument(
        "--actor",
        default="finance.operator@hackersdojo.example",
        help="Finance actor id recorded on approvals and receipts",
    )
    args = parser.parse_args(argv)

    ledger, receipts = run_pilot(
        args.fixture,
        approve=True,
        reconcile=not args.no_reconcile,
        finance_actor=args.actor,
    )

    payload = {
        "organization": {
            "id": ledger.organization.id,
            "name": ledger.organization.name,
            "policy_version": ledger.organization.policy_version,
        },
        "receipt_count": len(receipts),
        "receipts": receipts_to_jsonable(receipts),
        "audit_event_count": len(ledger.audit_log),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
