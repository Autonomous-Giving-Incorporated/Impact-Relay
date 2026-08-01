"""CLI entry path for the HD-IR pilot and public export.

Usage:
  impact-relay-pilot
  impact-relay-pilot --fixture fixtures/pilot_hd_ir_001.json
  impact-relay-pilot --write-public data/use-of-funds-public.json
  python -m impact_relay.cli
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.pilot import receipts_to_jsonable, run_pilot
from impact_relay.public_export import build_public_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Impact Relay pilot — import fixture, publish receipts, optional public export"
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
        help="Finance actor id recorded on approvals and receipts (not public)",
    )
    parser.add_argument(
        "--write-public",
        type=Path,
        default=None,
        help="Write privacy-safe public use-of-funds JSON for GitHub Pages",
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Print only the public export payload to stdout",
    )
    args = parser.parse_args(argv)

    ledger, receipts = run_pilot(
        args.fixture,
        approve=True,
        reconcile=not args.no_reconcile,
        finance_actor=args.actor,
    )

    public_payload = build_public_export(
        receipts,
        source="hd_ir_001_pilot_fixture",
    )

    if args.write_public:
        args.write_public.parent.mkdir(parents=True, exist_ok=True)
        args.write_public.write_text(
            json.dumps(public_payload, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.public_only:
        json.dump(public_payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    payload = {
        "organization": {
            "id": ledger.organization.id,
            "name": ledger.organization.name,
            "policy_version": ledger.organization.policy_version,
        },
        "receipt_count": len(receipts),
        "receipts": receipts_to_jsonable(receipts),
        "audit_event_count": len(ledger.audit_log),
        "public_export": {
            "written": str(args.write_public) if args.write_public else None,
            "summary": public_payload["summary"],
        },
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
