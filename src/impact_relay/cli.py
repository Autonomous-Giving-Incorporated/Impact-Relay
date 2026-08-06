"""CLI entry paths for HD-IR pilots, multi-phase runs, and public Pages exports.

Usage:
  python -m impact_relay
  python -m impact_relay --all-phases --digests-from-domain \
      --write-digests data/impact-digests-public.json
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
from impact_relay.every_org import (
    fetch_every_org_as_reconcile_aggregate,
    load_every_org_as_reconcile_aggregate,
    validate_live_aggregate_file,
)
from impact_relay.notion_public import (
    build_public_evidence_document,
    fetch_notion_public_evidence,
    load_notion_public_evidence,
    notion_campaign_targets_patch,
    write_public_evidence,
)
from impact_relay.pilot import receipts_to_jsonable, run_all_phases_pilot, run_pilot
from impact_relay.public_export import build_public_export
from impact_relay.public_impact import build_public_impact_export, write_public_impact
from impact_relay.reconcile import (
    apply_aggregate_reconciliation,
    load_impact_state,
    reconcile_file,
    write_impact_state,
)


def _run_durable(args: argparse.Namespace) -> int:
    """Pilot P1–P3: durable seed / list / approve / status / check / worker."""
    from impact_relay.workflows.durable import (
        DEFAULT_DATA_DIR,
        HOWTO,
        durable_approve,
        durable_list,
        durable_rehydrate_check,
        durable_seed,
        durable_status,
        durable_worker,
    )

    data_dir = args.data_dir or DEFAULT_DATA_DIR
    cmd = args.durable
    if cmd == "help":
        print(HOWTO)
        print(f"\nDefault --data-dir: {DEFAULT_DATA_DIR.resolve()}")
        return 0
    if cmd == "seed":
        out = durable_seed(
            data_dir,
            expense_batch=args.expense_batch,
            fixture_path=args.fixture,
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if cmd == "list":
        out = durable_list(data_dir, filters=args.workflow_filter)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok", True) else 1
    if cmd == "approve":
        out = durable_approve(
            data_dir,
            workflow_id=args.workflow_id,
            approver_id=args.approver_id,
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if cmd == "status":
        out = durable_status(data_dir)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if cmd == "check":
        try:
            out = durable_rehydrate_check(data_dir)
        except FileNotFoundError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if cmd == "worker":
        try:
            out = durable_worker(
                data_dir,
                once=bool(getattr(args, "once", False)),
                max_ticks=getattr(args, "max_ticks", None),
                poll_interval=float(getattr(args, "poll_interval", 1.0) or 1.0),
                worker_id=getattr(args, "worker_id", None),
                force=bool(getattr(args, "force_worker", False)),
            )
        except FileNotFoundError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    print(json.dumps({"error": f"unknown durable cmd: {cmd}"}), file=sys.stderr)
    return 2


def _run_workflow_ops(args: argparse.Namespace) -> int:
    """PR-M5 operator CLI: list / signal / seed / demo."""
    import json as _json

    from impact_relay.workflows.ops import (
        approval_from_dict,
        list_operator_cases,
        load_ops_session,
        save_ops_session,
        seed_session_to_wait,
        signal_approval_and_pump,
    )
    from impact_relay.workflows.runtime import WorkflowRuntime

    op = args.workflow_ops
    session_path = args.workflow_session or Path(".impact-relay-workflow-session.json")

    if op == "seed":
        batch_path = args.expense_batch or Path("fixtures/expense_intake_batch_v1.json")
        with batch_path.open(encoding="utf-8") as f:
            batch = _json.load(f)
        runtime, store, binding, tenant_id, ids = seed_session_to_wait(
            expense_rows=batch.get("expenses") or [],
            fixture_path=args.fixture,
            simulation=args.simulate_agents,
        )
        save_ops_session(session_path, store, binding, tenant_id=tenant_id)
        cases = list_operator_cases(
            store,
            tenant_id,
            filters=[x.strip() for x in args.workflow_filter.split(",") if x.strip()],
        )
        print(
            _json.dumps(
                {
                    "op": "seed",
                    "session": str(session_path),
                    "tenant_id": tenant_id,
                    "started": ids,
                    "cases": [c.to_dict() for c in cases],
                },
                indent=2,
            )
        )
        return 0

    if op == "list":
        if not session_path.is_file():
            print(
                _json.dumps(
                    {
                        "error": "session_not_found",
                        "hint": "Run --workflow-ops seed first",
                        "session": str(session_path),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        store, binding, tenant_id = load_ops_session(session_path)
        cases = list_operator_cases(
            store,
            tenant_id,
            filters=[x.strip() for x in args.workflow_filter.split(",") if x.strip()],
        )
        print(
            _json.dumps(
                {
                    "op": "list",
                    "session": str(session_path),
                    "tenant_id": tenant_id,
                    "count": len(cases),
                    "cases": [c.to_dict() for c in cases],
                },
                indent=2,
            )
        )
        return 0

    if op == "signal":
        if not session_path.is_file():
            print(
                _json.dumps({"error": "session_not_found", "session": str(session_path)}),
                file=sys.stderr,
            )
            return 2
        if not args.workflow_id:
            print(
                _json.dumps({"error": "workflow_id_required"}),
                file=sys.stderr,
            )
            return 2
        store, binding, tenant_id = load_ops_session(session_path)
        runtime = WorkflowRuntime(store, binding)
        inst = store.get(tenant_id, args.workflow_id)
        if inst is None:
            print(
                _json.dumps({"error": "workflow_not_found", "workflow_id": args.workflow_id}),
                file=sys.stderr,
            )
            return 2
        if args.approval_json is not None:
            data = _json.loads(args.approval_json.read_text(encoding="utf-8"))
            approval = approval_from_dict(data, tenant_id=tenant_id)
        else:
            # Auto-build APPROVE from frozen wait key
            wait = inst.context.get("wait") or {}
            frozen = wait.get("frozen_command") or {}
            key = frozen.get("idempotency_key") or wait.get("command_idempotency_key")
            if not key:
                print(
                    _json.dumps(
                        {
                            "error": "no_wait_key",
                            "hint": "Provide --approval-json or ensure workflow is WAITING_SIGNAL",
                        }
                    ),
                    file=sys.stderr,
                )
                return 2
            if str(args.approver_id).startswith("agent:"):
                print(
                    _json.dumps({"error": "approver_must_be_human"}),
                    file=sys.stderr,
                )
                return 2
            approval = approval_from_dict(
                {
                    "tenant_id": tenant_id,
                    "command_idempotency_key": key,
                    "decision": "APPROVE",
                    "approver_id": args.approver_id,
                    "proposal_id": wait.get("proposal_id") or "operator",
                },
                tenant_id=tenant_id,
            )
        updated = signal_approval_and_pump(
            runtime,
            tenant_id=tenant_id,
            workflow_id=args.workflow_id,
            approval=approval,
        )
        save_ops_session(session_path, store, binding, tenant_id=tenant_id)
        print(
            _json.dumps(
                {
                    "op": "signal",
                    "workflow_id": args.workflow_id,
                    "workflow_state": updated.workflow_state.value if updated else None,
                    "run_status": updated.run_status.value if updated else None,
                    "last_error": updated.last_error if updated else None,
                },
                indent=2,
            )
        )
        return 0

    if op == "demo":
        batch_path = args.expense_batch or Path("fixtures/expense_intake_batch_v1.json")
        with batch_path.open(encoding="utf-8") as f:
            batch = _json.load(f)
        runtime, store, binding, tenant_id, ids = seed_session_to_wait(
            expense_rows=batch.get("expenses") or [],
            fixture_path=args.fixture,
            simulation=args.simulate_agents,
        )
        before = list_operator_cases(store, tenant_id, filters=("waiting", "all"))
        results = []
        for wid in ids:
            inst = store.get(tenant_id, wid)
            if inst is None:
                continue
            wait = inst.context.get("wait") or {}
            frozen = wait.get("frozen_command") or {}
            key = frozen.get("idempotency_key") or wait.get("command_idempotency_key")
            if not key:
                results.append({"workflow_id": wid, "skipped": True, "reason": "no_wait"})
                continue
            approval = approval_from_dict(
                {
                    "tenant_id": tenant_id,
                    "command_idempotency_key": key,
                    "decision": "APPROVE",
                    "approver_id": args.approver_id,
                    "proposal_id": wait.get("proposal_id") or "demo",
                },
                tenant_id=tenant_id,
            )
            updated = signal_approval_and_pump(
                runtime, tenant_id=tenant_id, workflow_id=wid, approval=approval
            )
            results.append(
                {
                    "workflow_id": wid,
                    "workflow_state": updated.workflow_state.value if updated else None,
                    "run_status": updated.run_status.value if updated else None,
                }
            )
        save_ops_session(session_path, store, binding, tenant_id=tenant_id)
        after = list_operator_cases(
            store, tenant_id, filters=("waiting", "blocked", "dead_letter", "all")
        )
        print(
            _json.dumps(
                {
                    "op": "demo",
                    "session": str(session_path),
                    "before_cases": [c.to_dict() for c in before],
                    "signal_results": results,
                    "after_cases": [c.to_dict() for c in after],
                },
                indent=2,
            )
        )
        return 0

    print(_json.dumps({"error": f"unknown_ops:{op}"}), file=sys.stderr)
    return 2


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
        help=(
            "Every.org-style aggregate_summary JSON (normalized then reconciled). "
            "Also reads IMPACT_RELAY_EVERY_ORG_AGGREGATE if flag omitted."
        ),
    )
    parser.add_argument(
        "--every-org-aggregate-url",
        default=None,
        help=(
            "HTTPS endpoint returning an aggregate-only Every.org summary. "
            "Also reads IMPACT_RELAY_EVERY_ORG_AGGREGATE_URL."
        ),
    )
    parser.add_argument(
        "--require-observed",
        action="store_true",
        help=(
            "Fail unless raisedSource becomes processor_aggregate / OBSERVED "
            "(rejects pilot/fixture sources)"
        ),
    )
    parser.add_argument(
        "--validate-every-org-aggregate",
        type=Path,
        default=None,
        help=(
            "Dry-run: validate a live Every.org aggregate JSON (no write). "
            "Exit 0 if OBSERVED-ready; exit 2 otherwise."
        ),
    )
    parser.add_argument(
        "--expense-approval-slice",
        action="store_true",
        help=(
            "Run fixture-backed expense→approval vertical slice "
            "(agent contracts + human gate). Prints JSON summary."
        ),
    )
    parser.add_argument(
        "--expense-batch",
        type=Path,
        default=None,
        help="Expense intake batch JSON (default: fixtures/expense_intake_batch_v1.json)",
    )
    parser.add_argument(
        "--simulate-agents",
        action="store_true",
        help="With --expense-approval-slice: simulation mode (no ledger mutation)",
    )
    parser.add_argument(
        "--no-approve",
        action="store_true",
        help="With --expense-approval-slice: stop at REVIEW_PENDING (no human approve)",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help=(
            "With --expense-approval-slice: after UOF publish, compose email preview "
            "and require separate send approval (fixture delivery)"
        ),
    )
    parser.add_argument(
        "--workflow-worker-ticks",
        type=int,
        default=None,
        help=(
            "Run in-process workflow worker for N ticks (PR-M4). "
            "Uses memory store; demo path starts batch then pumps claims."
        ),
    )
    parser.add_argument(
        "--durable",
        choices=["seed", "list", "approve", "status", "check", "worker", "help"],
        default=None,
        help=(
            "Easy durable pilot (SQLite workflows.db + ledger_commands.jsonl; "
            "optional Postgres via IMPACT_RELAY_DATABASE_URL). "
            "seed → list → approve; worker --once drains PENDING after restart."
        ),
    )
    parser.add_argument(
        "--shadow-rehearsal",
        action="store_true",
        help=(
            "Automated synthetic shadow checklist (seed, role denial, approve, "
            "rehydrate, donor API). Does not claim live-cohort sign-off."
        ),
    )
    parser.add_argument(
        "--write-findings",
        type=Path,
        default=None,
        help="With --shadow-rehearsal: append markdown findings to this path",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Durable workspace directory (default: .impact-relay/durable)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --durable worker: run until idle then exit (no env flag needed)",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="With --durable worker: max claim loops",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="With --durable worker: seconds between polls when continuous",
    )
    parser.add_argument(
        "--force-worker",
        action="store_true",
        help="With --durable worker: allow continuous loop without WORKFLOW_WORKER_ENABLED",
    )
    parser.add_argument(
        "--workflow-ops",
        choices=["list", "signal", "seed", "demo"],
        default=None,
        help=(
            "PR-M5 operator tools: list waiting/blocked/DLQ cases, signal approval, "
            "seed session to human wait, or full demo (seed+list+approve+pump)."
        ),
    )
    parser.add_argument(
        "--workflow-session",
        type=Path,
        default=None,
        help="Versioned JSON session path for ops list/signal across CLI invocations",
    )
    parser.add_argument(
        "--workflow-filter",
        default="waiting,blocked,dead_letter,needs_information,failed",
        help="Comma filters for --workflow-ops list (or 'all')",
    )
    parser.add_argument(
        "--workflow-id",
        default=None,
        help="Workflow id for --workflow-ops signal",
    )
    parser.add_argument(
        "--approval-json",
        type=Path,
        default=None,
        help="ApprovalReceipt JSON for --workflow-ops signal (or auto from wait key in demo)",
    )
    parser.add_argument(
        "--approver-id",
        default="finance.approver@hackersdojo.example",
        help="Human approver id for demo/auto signal (never agent:*)",
    )
    parser.add_argument(
        "--write-impact-state",
        type=Path,
        default=None,
        help="Impact-state path for aggregate reconciliation write",
    )
    parser.add_argument(
        "--notion-public-evidence",
        type=Path,
        default=None,
        help="Notion-exported public evidence JSON (Form 990 / historical aggregates only)",
    )
    parser.add_argument(
        "--notion-public-evidence-url",
        default=None,
        help=(
            "HTTPS endpoint returning pre-aggregated public evidence JSON. "
            "Also reads IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_URL."
        ),
    )
    parser.add_argument(
        "--write-public-evidence",
        type=Path,
        default=None,
        help="Write Pages public-evidence.json from Notion aggregates",
    )
    parser.add_argument(
        "--write-public-impact",
        type=Path,
        default=None,
        help="Write Pages public-impact.json from domain IMPACT receipts (no donor ids)",
    )
    parser.add_argument(
        "--publish-pages",
        action="store_true",
        help=(
            "One-shot Pages publish: Every.org aggregate → impact-state, Notion public evidence, "
            "domain digests, public IMPACT outcomes, and use-of-funds export"
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

    import os

    # --- Easy durable workspace (pilot P1) ---
    if args.durable is not None:
        return _run_durable(args)

    # --- Synthetic shadow rehearsal (pilot readiness) ---
    if args.shadow_rehearsal:
        from impact_relay.host.rehearsal import append_findings, run_shadow_rehearsal

        data_dir = args.data_dir or Path(".impact-relay/shadow-rehearsal")
        report = run_shadow_rehearsal(
            data_dir,
            expense_batch=args.expense_batch,
        )
        if args.write_findings is not None:
            written = append_findings(args.write_findings, report)
            report = {**report, "findings_path": str(written.resolve())}
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok") else 1

    # --- Operator workflow ops (PR-M5) ---
    if args.workflow_ops is not None:
        return _run_workflow_ops(args)

    # --- Workflow worker demo ticks (PR-M4) ---
    if args.workflow_worker_ticks is not None:
        import copy

        from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
        from impact_relay.domain.tenant import TenantWorkspace
        from impact_relay.pilot import build_ledger_from_fixture, load_fixture
        from impact_relay.workflows.runtime import WorkflowRuntime
        from impact_relay.workflows.store_memory import InMemoryWorkflowStore
        from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker

        batch_path = args.expense_batch or Path("fixtures/expense_intake_batch_v1.json")
        with batch_path.open(encoding="utf-8") as f:
            batch = json.load(f)
        data = copy.deepcopy(load_fixture(args.fixture))
        data["expenses"] = []
        data["publish"] = []
        ledger = build_ledger_from_fixture(data)
        store = InMemoryWorkflowStore()
        binding = InMemoryLedgerBinding()
        binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
        runtime = WorkflowRuntime(store, binding)
        rows = batch.get("expenses") or []
        started_ids: list[str] = []
        for row in rows:
            inst = runtime.start_expense_to_receipt(
                tenant_id=ledger.organization.id,
                expense_row=row,
                simulation=args.simulate_agents,
            )
            started_ids.append(inst.workflow_id)
        worker = WorkflowWorker(
            runtime,
            WorkerConfig(
                worker_id="cli-worker",
                poll_interval_seconds=0.0,
                claim_batch_size=10,
            ),
        )
        ticks = worker.run(max_ticks=max(1, args.workflow_worker_ticks), stop_when_idle=True)
        summary = {
            "started_workflows": started_ids,
            "ticks": [t.to_dict() for t in ticks],
            "instances": [
                {
                    "workflow_id": i.workflow_id,
                    "workflow_state": i.workflow_state.value,
                    "run_status": i.run_status.value,
                    "attempt_count": i.attempt_count,
                    "last_error": i.last_error,
                }
                for i in store.list(ledger.organization.id, limit=100)
            ],
        }
        print(json.dumps(summary, indent=2, default=str))
        return 0

    # --- Dry-run live aggregate validation (C: operator path) ---
    if args.validate_every_org_aggregate is not None:
        try:
            report = validate_live_aggregate_file(
                args.validate_every_org_aggregate,
                require_observed=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "path": str(args.validate_every_org_aggregate),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        print(json.dumps(report, indent=2))
        return 0

    # --- Agent vertical slice (A/B) ---
    if args.expense_approval_slice:
        import copy

        from impact_relay.agents.expense_workflow import run_expense_approval_slice
        from impact_relay.agents.types import to_jsonable
        from impact_relay.pilot import build_ledger_from_fixture, load_fixture

        batch_path = args.expense_batch or Path("fixtures/expense_intake_batch_v1.json")
        with batch_path.open(encoding="utf-8") as f:
            batch = json.load(f)
        data = load_fixture(args.fixture)
        data = copy.deepcopy(data)
        data["expenses"] = []
        data["publish"] = []
        ledger = build_ledger_from_fixture(data)
        result = run_expense_approval_slice(
            ledger,
            expense_rows=batch.get("expenses") or [],
            human_approver_id=args.actor,
            approve=not args.no_approve,
            simulation=args.simulate_agents,
            publish_specs=None
            if args.no_approve or args.simulate_agents
            else [
                {
                    "donor_id": "donor_alice",
                    "donation_id": "don_1000_alice",
                    "allocation_id": "alloc_community_hardware",
                    "attribution_method": "DIRECT_RESTRICTED",
                    "attributed_amount": str((batch.get("expenses") or [{}])[0].get("amount", "0")),
                }
            ],
            send_email=bool(args.send_email and not args.no_approve and not args.simulate_agents),
            communications_approver_id="comms.approver@hackersdojo.example",
        )
        print(json.dumps(to_jsonable(result.to_dict()), indent=2, default=str))
        return 0 if result.workflow_state.value not in ("BLOCKED", "REJECTED") else 1

    if args.every_org_aggregate is None:
        env_agg = os.environ.get("IMPACT_RELAY_EVERY_ORG_AGGREGATE", "").strip()
        if env_agg:
            args.every_org_aggregate = Path(env_agg)
    args.every_org_aggregate_url = (
        args.every_org_aggregate_url
        or os.environ.get("IMPACT_RELAY_EVERY_ORG_AGGREGATE_URL", "").strip()
        or None
    )
    args.notion_public_evidence_url = (
        args.notion_public_evidence_url
        or os.environ.get("IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_URL", "").strip()
        or None
    )
    if args.every_org_aggregate is not None and args.every_org_aggregate_url is not None:
        parser.error("choose either --every-org-aggregate or --every-org-aggregate-url")
    if args.notion_public_evidence is not None and args.notion_public_evidence_url is not None:
        parser.error("choose either --notion-public-evidence or --notion-public-evidence-url")

    if args.publish_pages:
        # Prefer live operator path via env; fall back to pilot fixture for demos.
        if args.every_org_aggregate_url is None:
            args.every_org_aggregate = args.every_org_aggregate or Path(
                "fixtures/every_org_aggregate_v1.json"
            )
        if args.notion_public_evidence_url is None:
            args.notion_public_evidence = args.notion_public_evidence or Path(
                "fixtures/notion_public_evidence_v1.json"
            )
        args.write_impact_state = args.write_impact_state or Path("data/impact-state.json")
        args.write_public = args.write_public or Path("data/use-of-funds-public.json")
        args.write_digests = args.write_digests or Path("data/impact-digests-public.json")
        args.write_public_evidence = args.write_public_evidence or Path("data/public-evidence.json")
        args.write_public_impact = args.write_public_impact or Path("data/public-impact.json")
        args.digests_from_domain = True
        args.merge_fixture_digests = True
        args.all_phases = True

    if args.digests_from_domain:
        args.all_phases = True

    # --- Aggregate reconciliation (Every.org or generic) ---
    impact_state = None
    target_state = args.write_impact_state or Path("data/impact-state.json")
    if args.every_org_aggregate is not None or args.every_org_aggregate_url is not None:
        if args.every_org_aggregate_url is not None:
            aggregate = fetch_every_org_as_reconcile_aggregate(
                args.every_org_aggregate_url,
                bearer_token=os.environ.get("IMPACT_RELAY_EVERY_ORG_AGGREGATE_TOKEN") or None,
            )
        else:
            aggregate = load_every_org_as_reconcile_aggregate(args.every_org_aggregate)
        current = load_impact_state(target_state)
        impact_state = apply_aggregate_reconciliation(current, aggregate)
        if args.require_observed:
            src = impact_state.get("campaign", {}).get("raisedSource")
            if src != "processor_aggregate":
                print(
                    json.dumps(
                        {
                            "error": "require_observed_failed",
                            "raisedSource": src,
                            "raisedClaimLabel": impact_state.get("campaign", {}).get(
                                "raisedClaimLabel"
                            ),
                            "aggregateSource": impact_state.get("campaign", {}).get(
                                "aggregateSource"
                            ),
                            "hint": (
                                "Provide an authorized Every.org aggregate with source like "
                                "every.org/aggregate:hacker-dojo and claimLevel OBSERVED. "
                                "Do not use fixture:// or pilot sources."
                            ),
                        },
                        indent=2,
                    ),
                    file=sys.stderr,
                )
                return 2
        write_impact_state(target_state, impact_state)
    elif args.reconcile_from is not None:
        impact_state = reconcile_file(args.reconcile_from, target_state, write=True)
        if (
            args.require_observed
            and impact_state.get("campaign", {}).get("raisedSource") != "processor_aggregate"
        ):
            print(
                json.dumps(
                    {
                        "error": "require_observed_failed",
                        "raisedSource": impact_state.get("campaign", {}).get("raisedSource"),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
    elif args.write_impact_state is not None and not args.publish_pages:
        impact_state = reconcile_file(None, args.write_impact_state, write=True)

    # --- Notion public evidence (does not invent live raised totals) ---
    public_evidence = None
    if (
        args.notion_public_evidence is not None
        or args.notion_public_evidence_url is not None
        or args.write_public_evidence is not None
    ):
        if args.notion_public_evidence_url is not None:
            notion_src = fetch_notion_public_evidence(
                args.notion_public_evidence_url,
                bearer_token=os.environ.get("IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_TOKEN") or None,
            )
        elif args.notion_public_evidence is not None:
            notion_src = load_notion_public_evidence(args.notion_public_evidence)
        else:
            notion_src = load_notion_public_evidence()
        public_evidence = build_public_evidence_document(notion_src)
        if args.write_public_evidence:
            write_public_evidence(args.write_public_evidence, public_evidence)
        # Align campaign targets from Notion without inventing live raised.
        if impact_state is None and target_state.exists():
            impact_state = load_impact_state(target_state)
        if impact_state is not None:
            patch = notion_campaign_targets_patch(public_evidence)
            impact_state.setdefault("campaign", {}).update(patch)
            note = (
                "Notion Public EvidencePack loaded: Form 990 contribution history and "
                "2012 campaign aggregate are OBSERVED; live SupperHappyFundHouse raised "
                "remains NOT_COMPUTABLE until authorized processor aggregates arrive."
            )
            notifications = impact_state.setdefault("notifications", [])
            notifications[:] = [n for n in notifications if n.get("id") != "notion-public-evidence"]
            notifications.append(
                {
                    "id": "notion-public-evidence",
                    "severity": "info",
                    "title": "Notion public evidence baseline loaded",
                    "body": note,
                    "publishedAt": "2026-08-01T16:00:00Z",
                }
            )
            if args.write_impact_state or args.publish_pages:
                write_impact_state(target_state, impact_state)

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
    if args.digests_from_domain and platform is not None and all_phases_payload is not None:
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
            load_events_fixture(args.events_fixture) if args.events_fixture is not None else None
        )
        digests = build_public_digests(events_doc)

    if args.write_digests:
        write_public_digests(args.write_digests, digests)
    if args.digests_only:
        json.dump(digests, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # --- Use-of-funds public export ---
    if args.all_phases and platform is not None and all_phases_payload is not None:
        primary_id = all_phases_payload.get("primary", {}).get("organization_id")
        ws = platform.get_workspace(primary_id)
        receipts = [r for r in ws.ledger.receipts.values() if not r.corrected]
        public_payload = build_public_export(receipts, source="hd_ir_all_phases_pilot_fixture")
        impact_public = build_public_impact_export(
            list(ws.impact_receipts.values()),
            source="domain_impact_receipts",
        )
        if args.write_public:
            args.write_public.parent.mkdir(parents=True, exist_ok=True)
            args.write_public.write_text(
                json.dumps(public_payload, indent=2) + "\n", encoding="utf-8"
            )
        if args.write_public_impact:
            write_public_impact(args.write_public_impact, impact_public)
        if args.public_only:
            json.dump(public_payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        all_phases_payload["public_export"] = {
            "written": str(args.write_public) if args.write_public else None,
            "summary": public_payload.get("summary"),
        }
        all_phases_payload["public_impact"] = {
            "written": str(args.write_public_impact) if args.write_public_impact else None,
            "summary": impact_public.get("summary"),
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
            "raisedSource": None
            if impact_state is None
            else impact_state.get("campaign", {}).get("raisedSource"),
        }
        all_phases_payload["public_evidence"] = {
            "written": str(args.write_public_evidence) if args.write_public_evidence else None,
            "summary": None if public_evidence is None else public_evidence.get("summary"),
            "liveRaisedState": None
            if public_evidence is None
            else public_evidence.get("campaignTargets", {}).get("liveRaisedState"),
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
