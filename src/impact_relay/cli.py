"""CLI entry path for pilot, public export, digests, and aggregate reconciliation.

Usage:
  impact-relay-pilot
  impact-relay-pilot --write-public data/use-of-funds-public.json
  impact-relay-pilot --write-digests data/impact-digests-public.json
  impact-relay-pilot --reconcile-from fixtures/reconcile_aggregate_v1.json \\
      --write-impact-state data/impact-state.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.digest import build_public_digests, load_events_fixture, write_public_digests
from impact_relay.pilot import receipts_to_jsonable, run_pilot
from impact_relay.public_export import build_public_export
from impact_relay.reconcile import reconcile_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Impact Relay pilot — receipts, public export, digests, aggregate reconcile"
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Path to pilot ledger fixture JSON",
    )
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="Approve expenses but do not mark RECONCILED in the ledger pilot",
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
        "--write-digests",
        type=Path,
        default=None,
        help="Write privacy-safe impact event digests JSON for GitHub Pages",
    )
    parser.add_argument(
        "--events-fixture",
        type=Path,
        default=None,
        help="Events fixture for digests (default: fixtures/impact_events_pilot.json)",
    )
    parser.add_argument(
        "--reconcile-from",
        type=Path,
        default=None,
        help="Aggregate-only reconciliation fixture (no donor lists)",
    )
    parser.add_argument(
        "--write-impact-state",
        type=Path,
        default=None,
        help="Impact-state path for aggregate reconciliation write",
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Print only the public use-of-funds payload to stdout",
    )
    parser.add_argument(
        "--digests-only",
        action="store_true",
        help="Print only the public digests payload to stdout",
    )
    args = parser.parse_args(argv)

    impact_state = None
    if args.reconcile_from is not None:
        target = args.write_impact_state or Path("data/impact-state.json")
        impact_state = reconcile_file(args.reconcile_from, target, write=True)
    elif args.write_impact_state is not None:
        # Allow explicit state path with default aggregate fixture.
        impact_state = reconcile_file(None, args.write_impact_state, write=True)

    events_doc = (
        load_events_fixture(args.events_fixture)
        if args.events_fixture is not None
        else None
    )
    digests = build_public_digests(events_doc)

    if args.write_digests:
        write_public_digests(args.write_digests, digests)

    if args.digests_only:
        json.dump(digests, sys.stdout, indent=2)
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
        "digests": {
            "written": str(args.write_digests) if args.write_digests else None,
            "summary": digests["summary"],
        },
        "impact_state": {
            "reconciled": impact_state is not None,
            "raisedPublic": None
            if impact_state is None
            else impact_state.get("campaign", {}).get("raisedPublic"),
        },
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
