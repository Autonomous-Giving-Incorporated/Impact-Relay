"""CLI entry paths for HD-IR pilots, multi-phase runs, and public export.

Usage:
  python -m impact_relay
  python -m impact_relay --all-phases
  python -m impact_relay --all-phases --fixture fixtures/pilot_all_phases.json
  impact-relay-pilot --write-public data/use-of-funds-public.json
  impact-relay-pilot --public-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.pilot import receipts_to_jsonable, run_all_phases_pilot, run_pilot
from impact_relay.public_export import build_public_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Impact Relay pilot — UOF, multi-phase fixtures, optional public export"
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Path to fixture JSON",
    )
    parser.add_argument(
        "--all-phases",
        action="store_true",
        help="Run multi-stage pilot (UOF → impact → notify → donor read, multi-tenant)",
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

    if args.all_phases:
        _platform, payload = run_all_phases_pilot(
            args.fixture,
            finance_actor=args.actor,
            reconcile=not args.no_reconcile,
        )
        # Optional public export from primary UOF receipts when requested
        if args.write_public or args.public_only:
            from impact_relay.domain.types import UseOfFundsReceipt
            from decimal import Decimal

            # Rebuild receipt objects is heavy; export from dicts via pilot ledger path
            ledger, receipts = run_pilot(
                args.fixture if args.fixture else None,
                approve=True,
                reconcile=not args.no_reconcile,
                finance_actor=args.actor,
            )
            # Prefer all-phases primary org ledger receipts
            primary_id = payload.get("primary", {}).get("organization_id")
            if primary_id:
                ws = _platform.get_workspace(primary_id)
                receipts = [r for r in ws.ledger.receipts.values() if not r.corrected]
            public_payload = build_public_export(
                receipts, source="hd_ir_all_phases_pilot_fixture"
            )
            if args.write_public:
                args.write_public.parent.mkdir(parents=True, exist_ok=True)
                args.write_public.write_text(
                    json.dumps(public_payload, indent=2) + "\n", encoding="utf-8"
                )
            if args.public_only:
                json.dump(public_payload, sys.stdout, indent=2)
                sys.stdout.write("\n")
                return 0
            payload["public_export"] = {
                "written": str(args.write_public) if args.write_public else None,
                "summary": public_payload.get("summary"),
            }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

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
