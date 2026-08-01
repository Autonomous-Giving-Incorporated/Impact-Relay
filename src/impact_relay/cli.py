"""CLI entry paths for HD-IR pilots, multi-phase runs, and public Pages exports.

Usage:
  python -m impact_relay
  python -m impact_relay --all-phases --digests-from-domain --write-digests data/impact-digests-public.json
  python -m impact_relay --every-org-aggregate fixtures/every_org_aggregate_v1.json \\
      --write-impact-state data/impact-state.json
  python -m impact_relay --publish-pages
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from impact_relay.digest import (
    build_public_digests,
    digests_from_workspace,
    load_events_fixture,
    write_public_digests,
)
from impact_relay.every_org import load_every_org_as_reconcile_aggregate
from impact_relay.pilot import receipts_to_jsonable, run_all_phases_pilot, run_pilot
from impact_relay.public_export import build_public_export
from impact_relay.reconcile import reconcile_file, write_impact_state, load_impact_state, apply_aggregate_reconciliation


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
        "--digests-from-domain",
        action="store_true",
        help="Build digests from verified domain impact events (implies --all-phases)",
    )
    parser.add_argument(
        "--merge-fixture-digests",
        action="store_true",
        help="When using --digests-from-domain, also merge standalone events fixture",
    )
    parser.add_argument(
        "--reconcile-from",
        type=Path,
        default=None,
        help="Aggregate-only reconciliation fixture (no donor lists)",
    )
    parser.add_argument(
        "--every-org-aggregate",
        type=Path,
        default=None,
        help="Every.org-style aggregate_summary JSON (normalized then reconciled)",
    )
    parser.add_argument(
        "--write-impact-state",
        type=Path,
        default=None,
        help="Impact-state path for aggregate reconciliation write",
    )
    parser.add_argument(
        "--publish-pages",
        action="store_true",
        help=(
            "One-shot Pages publish: Every.org aggregate (default fixture) → impact-state, "
            "domain digests (+ fixture merge), and use-of-funds export"
        ),
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

    if args.publish_pages:
        args.every_org_aggregate = args.every_org_aggregate or Path(
            "fixtures/every_org_aggregate_v1.json"
        )
        args.write_impact_state = args.write_impact_state or Path("data/impact-state.json")
        args.write_public = args.write_public or Path("data/use-of-funds-public.json")
        args.write_digests = args.write_digests or Path("data/impact-digests-public.json")
        args.digests_from_domain = True
        args.merge_fixture_digests = True
        args.all_phases = True

    if args.digests_from_domain:
        args.all_phases = True

    # --- Aggregate reconciliation (Every.org or generic) ---
    impact_state = None
    target_state = args.write_impact_state or Path("data/impact-state.json")
    if args.every_org_aggregate is not None:
        aggregate = load_every_org_as_reconcile_aggregate(args.every_org_aggregate)
        current = load_impact_state(target_state)
        impact_state = apply_aggregate_reconciliation(current, aggregate)
        write_impact_state(target_state, impact_state)
    elif args.reconcile_from is not None:
        impact_state = reconcile_file(args.reconcile_from, target_state, write=True)
    elif args.write_impact_state is not None and not args.publish_pages:
        impact_state = reconcile_file(None, args.write_impact_state, write=True)

    digests = None
    platform = None
    all_phases_payload = None

    if args.all_phases:
        platform, all_phases_payload = run_all_phases_pilot(
            args.fixture,
            finance_actor=args.actor,
            reconcile=not args.no_reconcile,
        )

    # --- Digests ---
    if args.digests_from_domain and platform is not None:
        primary_id = all_phases_payload.get("primary", {}).get("organization_id")
        ws = platform.get_workspace(primary_id)
        extra = None
        if args.merge_fixture_digests or args.events_fixture is not None:
            extra = load_events_fixture(args.events_fixture)
        digests = digests_from_workspace(
            ws,
            source="domain_impact_service+fixture"
            if extra is not None
            else "domain_impact_service",
            extra_events_doc=extra,
        )
    else:
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

    # --- Use-of-funds public export ---
    if args.all_phases and platform is not None:
        primary_id = all_phases_payload.get("primary", {}).get("organization_id")
        ws = platform.get_workspace(primary_id)
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
        all_phases_payload["public_export"] = {
            "written": str(args.write_public) if args.write_public else None,
            "summary": public_payload.get("summary"),
        }
        all_phases_payload["digests"] = {
            "written": str(args.write_digests) if args.write_digests else None,
            "summary": digests["summary"],
            "source": digests.get("source"),
        }
        all_phases_payload["impact_state"] = {
            "reconciled": impact_state is not None,
            "raisedPublic": None
            if impact_state is None
            else impact_state.get("campaign", {}).get("raisedPublic"),
        }
        json.dump(all_phases_payload, sys.stdout, indent=2)
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
            "source": digests.get("source"),
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
