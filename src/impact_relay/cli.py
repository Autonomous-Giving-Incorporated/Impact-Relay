"""CLI entry paths for HD-IR pilots, multi-phase runs, and public Pages exports.

Usage:
  python -m impact_relay
  python -m impact_relay --all-phases
  python -m impact_relay --write-public data/use-of-funds-public.json
  python -m impact_relay --write-digests data/impact-digests-public.json
  python -m impact_relay --reconcile-from fixtures/reconcile_aggregate_v1.json \\
      --write-impact-state data/impact-state.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.digest import build_public_digests, load_events_fixture, write_public_digests
from impact_relay.pilot import receipts_to_jsonable, run_all_phases_pilot, run_pilot
from impact_relay.public_export import build_public_export
from impact_relay.reconcile import reconcile_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Impact Relay pilot — UOF, multi-phase fixtures, public Pages exports"
    )
    parser.add_argument("--fixture", type=Path, default=None, help="Path to fixture JSON")
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
        impact_state = reconcile_file(None, args.write_impact_state, write=True)

    events_doc = (
        load_events_fixture(args.events_fixture) if args.events_fixture is not None else None
    )
    digests = build_public_digests(events_doc)
    if args.write_digests:
        write_public_digests(args.write_digests, digests)
    if args.digests_only:
        json.dump(digests, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.all_phases:
        _platform, payload = run_all_phases_pilot(
            args.fixture,
            finance_actor=args.actor,
            reconcile=not args.no_reconcile,
        )
        if args.write_public or args.public_only:
            ledger, receipts = run_pilot(
                args.fixture if args.fixture else None,
                approve=True,
                reconcile=not args.no_reconcile,
                finance_actor=args.actor,
            )
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
        payload["digests"] = {
            "written": str(args.write_digests) if args.write_digests else None,
            "summary": digests["summary"],
        }
        payload["impact_state"] = {
            "reconciled": impact_state is not None,
            "raisedPublic": None
            if impact_state is None
            else impact_state.get("campaign", {}).get("raisedPublic"),
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
