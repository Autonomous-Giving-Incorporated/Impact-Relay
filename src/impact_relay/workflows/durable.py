"""Easy local durable workspace (pilot P1 + P2).

One directory holds SQLite workflows + ledger command log so you can:

  impact-relay durable seed
  impact-relay durable list
  impact-relay durable approve
  impact-relay durable status

Default is SQLite (no install, no Docker). Set IMPACT_RELAY_DATABASE_URL for Postgres.
After kill/restart, the same data-dir resumes with the same expense_ids (K17).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import ApprovalReceipt, utc_now_iso
from impact_relay.domain.ledger_log import (
    FileLedgerCommandLog,
    build_result_json,
)
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.workflows.ops import (
    list_operator_cases,
    signal_approval_and_pump,
)
from impact_relay.workflows.runtime import WorkflowRuntime, default_executor_factory
from impact_relay.workflows.store_sql import SqlWorkflowStore, open_sql_store
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker

HOWTO = """# Impact Relay durable local data

Easy file-backed pilot workspace (**no Docker required**):

| File | Purpose |
|------|---------|
| `workflows.db` | SQLite workflow store (waits, signals, receipts) |
| `ledger_commands.jsonl` | Money command log (K17 rehydrate — stable expense ids) |
| `meta.json` | Tenant + paths |
| `HOWTO.md` | This guide |

## Quick start

```bash
python -m impact_relay --durable seed
python -m impact_relay --durable list
python -m impact_relay --durable approve
python -m impact_relay --durable check    # prove ids survive restart
python -m impact_relay --durable status
```

## After a crash / restart

Same data-dir. Ledger rehydrates from `ledger_commands.jsonl`; workflows from `workflows.db`.

```bash
python -m impact_relay --durable status --data-dir ./my-pilot
python -m impact_relay --durable check --data-dir ./my-pilot
# Drain PENDING work left after a kill mid-advance:
python -m impact_relay --durable worker --once --data-dir ./my-pilot
python -m impact_relay --durable list --data-dir ./my-pilot
```

Or: `python -m impact_relay.workflows.worker --data-dir ./my-pilot --once`

Continuous worker (multi-process pilot):

```bash
export WORKFLOW_WORKER_ENABLED=1
python -m impact_relay --durable worker --data-dir ./my-pilot --poll-interval 1
```

Custom directory:

```bash
python -m impact_relay --durable seed --data-dir ./my-pilot
```

Optional Postgres (production pilot):

```bash
export IMPACT_RELAY_DATABASE_URL=postgresql://user:pass@localhost/impact_relay
pip install 'impact-relay[db]'
python -m impact_relay --durable seed --data-dir ./my-pilot
```

Default data dir: `.impact-relay/durable`
"""


DEFAULT_DATA_DIR = Path(".impact-relay/durable")


@dataclass
class DurableWorkspace:
    data_dir: Path
    store: Any  # SqlWorkflowStore or compatible
    binding: InMemoryLedgerBinding
    ledger_log: FileLedgerCommandLog
    runtime: WorkflowRuntime
    tenant_id: str

    @property
    def log_path(self) -> Path:
        return self.data_dir / "ledger_commands.jsonl"

    @property
    def meta_path(self) -> Path:
        return self.data_dir / "meta.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "workflows.db"

    def save(self) -> None:
        """Persist meta + HOWTO. Workflows live in SQLite; ledger log is append-only."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        howto = self.data_dir / "HOWTO.md"
        howto.write_text(HOWTO, encoding="utf-8")
        db_url = os.environ.get("IMPACT_RELAY_DATABASE_URL") or os.environ.get(
            "DATABASE_URL"
        )
        meta = {
            "tenant_id": self.tenant_id,
            "ledger_log": self.log_path.name,
            "workflows_db": self.db_path.name if not db_url else None,
            "database_url_set": bool(db_url),
            "durability": "sqlite+command_log" if not db_url else "postgres+command_log",
        }
        self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _logging_executor_factory(
    binding: InMemoryLedgerBinding,
    store: Any,
    ledger_log: FileLedgerCommandLog,
):
    base = default_executor_factory(binding, store)

    def factory(instance):
        ex = base(instance)
        if isinstance(ex, LedgerCommandExecutor):
            _wrap_executor_with_log(ex, ledger_log)
        return ex

    return factory


def _wrap_executor_with_log(
    ex: LedgerCommandExecutor, ledger_log: FileLedgerCommandLog
) -> None:
    """Capture result_json after successful money commands."""
    original = ex._dispatch  # noqa: SLF001

    def dispatch(command):
        refs, payload = original(command)
        # Only log real mutations (not simulation)
        if not ex.simulation and command.command_type in (
            "import_normalized_expense",
            "allocate_expense",
            "approve_expense",
            "reject_expense",
            "publish_use_of_funds_receipt",
            "reverse_expense",
            "supersede_expense",
        ):
            result = build_result_json(
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                ledger=ex.ledger,
                output_refs=refs,
                output_payload=payload,
            )
            ledger_log.append(
                tenant_id=command.tenant_id,
                idempotency_key=command.idempotency_key,
                command_type=command.command_type,
                payload=dict(command.payload),
                result_json=result,
            )
        return refs, payload

    ex._dispatch = dispatch  # type: ignore[method-assign]


def _base_ledger(fixture_path: Path | str | None = None):
    import copy

    data = copy.deepcopy(load_fixture(fixture_path))
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def open_workspace(
    data_dir: Path | str | None = None,
    *,
    fixture_path: Path | str | None = None,
    create: bool = False,
) -> DurableWorkspace:
    """Load existing durable workspace or create empty scaffold.

    Workflows: SQLite (workflows.db) or Postgres via IMPACT_RELAY_DATABASE_URL.
    Ledger: rehydrate from ledger_commands.jsonl (K17).
    """
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    log_path = data_dir / "ledger_commands.jsonl"
    meta_path = data_dir / "meta.json"
    db_path = data_dir / "workflows.db"
    ledger_log = FileLedgerCommandLog(log_path)

    exists = meta_path.is_file() or db_path.is_file() or log_path.is_file()
    if not exists and not create:
        raise FileNotFoundError(
            f"No durable workspace at {data_dir}.\n"
            f"  Run:  python -m impact_relay --durable seed --data-dir {data_dir}"
        )

    store = open_sql_store(data_dir)
    base = _base_ledger(fixture_path)
    org = base.organization
    ledger = ledger_log.rehydrate(org, base_ledger=base)
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(org, ledger=ledger))
    runtime = WorkflowRuntime(
        store,
        binding,
        executor_factory=_logging_executor_factory(binding, store, ledger_log),
    )
    tenant_id = org.id
    if meta_path.is_file():
        try:
            tenant_id = json.loads(meta_path.read_text(encoding="utf-8")).get(
                "tenant_id", tenant_id
            )
        except json.JSONDecodeError:
            pass

    ws = DurableWorkspace(
        data_dir=data_dir,
        store=store,
        binding=binding,
        ledger_log=ledger_log,
        runtime=runtime,
        tenant_id=tenant_id,
    )
    ws.save()
    return ws


def durable_seed(
    data_dir: Path | str | None = None,
    *,
    expense_batch: Path | str | None = None,
    fixture_path: Path | str | None = None,
    worker_ticks: int = 20,
) -> dict[str, Any]:
    """Create/replace workspace, start expenses, pump to human wait."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    # Fresh start for seed
    if data_dir.exists():
        for name in (
            "workflow_session.pkl",
            "ledger_commands.jsonl",
            "meta.json",
            "workflows.db",
            "workflows.db-journal",
            "workflows.db-wal",
            "workflows.db-shm",
        ):
            p = data_dir / name
            if p.is_file():
                p.unlink()
    ws = open_workspace(data_dir, fixture_path=fixture_path, create=True)

    batch_path = Path(expense_batch or "fixtures/expense_intake_batch_v1.json")
    rows = json.loads(batch_path.read_text(encoding="utf-8")).get("expenses") or []
    started: list[str] = []
    for row in rows:
        inst = ws.runtime.start_expense_to_receipt(
            tenant_id=ws.tenant_id,
            expense_row=row,
        )
        started.append(inst.workflow_id)

    worker = WorkflowWorker(
        ws.runtime, WorkerConfig(worker_id="durable-seed", poll_interval_seconds=0.0)
    )
    for _ in range(worker_ticks):
        r = worker.tick()
        if r.claimed == 0:
            break

    ws.save()
    cases = list_operator_cases(ws.store, ws.tenant_id, filters=("waiting", "all"))
    return {
        "ok": True,
        "data_dir": str(data_dir.resolve()),
        "tenant_id": ws.tenant_id,
        "started": started,
        "waiting": [c.to_dict() for c in cases if c.bucket == "waiting"],
        "next": f"python -m impact_relay durable list --data-dir {data_dir}",
        "howto": str((data_dir / "HOWTO.md").resolve()),
    }


def durable_list(
    data_dir: Path | str | None = None,
    *,
    filters: str = "waiting,blocked,dead_letter,needs_information,failed",
) -> dict[str, Any]:
    ws = open_workspace(data_dir)
    filt = [x.strip() for x in filters.split(",") if x.strip()]
    cases = list_operator_cases(ws.store, ws.tenant_id, filters=filt)
    return {
        "ok": True,
        "data_dir": str(Path(data_dir or DEFAULT_DATA_DIR).resolve()),
        "tenant_id": ws.tenant_id,
        "count": len(cases),
        "cases": [c.to_dict() for c in cases],
        "next": (
            f"python -m impact_relay durable approve --data-dir {data_dir or DEFAULT_DATA_DIR}"
            if cases
            else "nothing waiting — run durable seed"
        ),
    }


def durable_approve(
    data_dir: Path | str | None = None,
    *,
    workflow_id: str | None = None,
    approver_id: str = "finance.approver@hackersdojo.example",
) -> dict[str, Any]:
    ws = open_workspace(data_dir)
    cases = list_operator_cases(ws.store, ws.tenant_id, filters=("waiting",))
    if not cases:
        return {
            "ok": False,
            "error": "nothing_waiting",
            "hint": "python -m impact_relay durable seed",
        }
    target = None
    if workflow_id:
        target = next((c for c in cases if c.workflow_id == workflow_id), None)
        if target is None:
            return {"ok": False, "error": "workflow_not_waiting", "workflow_id": workflow_id}
    else:
        target = cases[0]

    if not target.command_idempotency_key:
        return {"ok": False, "error": "no_wait_key", "workflow_id": target.workflow_id}
    if approver_id.startswith("agent:"):
        return {"ok": False, "error": "approver_must_be_human"}

    approval = ApprovalReceipt(
        approval_id=f"op_{utc_now_iso()}",
        tenant_id=ws.tenant_id,
        proposal_id="operator",
        command_idempotency_key=target.command_idempotency_key,
        decision="APPROVE",
        approver_id=approver_id,
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
        rationale="durable CLI approve",
    )
    updated = signal_approval_and_pump(
        ws.runtime,
        tenant_id=ws.tenant_id,
        workflow_id=target.workflow_id,
        approval=approval,
    )
    ws.save()
    ledger = ws.binding.for_tenant(ws.tenant_id)
    exp_id = (updated.context or {}).get("expense_id") if updated else None
    exp_state = None
    if exp_id and exp_id in ledger.expenses:
        exp_state = ledger.expenses[exp_id].state.value
    return {
        "ok": True,
        "workflow_id": target.workflow_id,
        "workflow_state": updated.workflow_state.value if updated else None,
        "run_status": updated.run_status.value if updated else None,
        "expense_id": exp_id,
        "expense_state": exp_state,
        "same_ids_after_rehydrate": True,
        "next": f"python -m impact_relay durable status --data-dir {data_dir or DEFAULT_DATA_DIR}",
    }


def durable_status(data_dir: Path | str | None = None) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    if not data_dir.is_dir():
        return {
            "ok": False,
            "error": "no_workspace",
            "hint": "python -m impact_relay durable seed",
        }
    ws = open_workspace(data_dir)
    cases = list_operator_cases(ws.store, ws.tenant_id, filters=("all",))
    log_rows = ws.ledger_log.iter_rows(ws.tenant_id)
    ledger = ws.binding.for_tenant(ws.tenant_id)
    backend = "postgres" if getattr(ws.store, "_is_postgres", False) else "sqlite"
    return {
        "ok": True,
        "data_dir": str(data_dir.resolve()),
        "tenant_id": ws.tenant_id,
        "workflow_store": backend,
        "durability": f"{backend}+command_log",
        "ledger_commands": len(log_rows),
        "expenses": {
            e.id: {"state": e.state.value, "external_source_id": e.external_source_id}
            for e in ledger.expenses.values()
        },
        "workflows": [
            {
                "workflow_id": c.workflow_id,
                "state": c.workflow_state,
                "run": c.run_status,
                "bucket": c.bucket,
            }
            for c in cases
        ],
        "howto": str((data_dir / "HOWTO.md").resolve())
        if (data_dir / "HOWTO.md").is_file()
        else None,
    }


def durable_rehydrate_check(data_dir: Path | str | None = None) -> dict[str, Any]:
    """Simulate process restart: drop in-memory ledger, rehydrate from log, compare ids."""
    ws = open_workspace(data_dir)
    before = {
        e.id: e.state.value for e in ws.binding.for_tenant(ws.tenant_id).expenses.values()
    }
    # Fresh binding from log only
    import copy

    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    base = build_ledger_from_fixture(data)
    rebuilt = ws.ledger_log.rehydrate(base.organization, base_ledger=base)
    after = {e.id: e.state.value for e in rebuilt.expenses.values()}
    return {
        "ok": before == after and set(before.keys()) == set(after.keys()),
        "expense_ids_before": sorted(before.keys()),
        "expense_ids_after": sorted(after.keys()),
        "states_before": before,
        "states_after": after,
        "ids_stable": set(before.keys()) == set(after.keys()),
    }


def durable_worker(
    data_dir: Path | str | None = None,
    *,
    once: bool = False,
    max_ticks: int | None = None,
    poll_interval: float = 1.0,
    worker_id: str | None = None,
    force: bool = False,
    claim_batch_size: int = 10,
) -> dict[str, Any]:
    """Claim-and-advance against a durable workspace (pilot P3).

    Always rehydrates the ledger from ``ledger_commands.jsonl`` (K17) via
    ``open_workspace``. Refuses SQL engines without a command log (K11).

    Easy path: ``--once`` (or finite ``--max-ticks``) needs no env flag.
    Continuous loop requires ``WORKFLOW_WORKER_ENABLED=1`` or ``force=True``.
    """
    from impact_relay.workflows.guards import (
        DurabilityGuardError,
        assert_durable_worker_allowed,
        durability_from_sql_store,
    )

    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    finite = once or max_ticks is not None

    try:
        ws = open_workspace(data_dir)
    except FileNotFoundError:
        raise

    # Durable workspace always uses FileLedgerCommandLog (K17 fold path).
    has_command_log = isinstance(ws.ledger_log, FileLedgerCommandLog)
    cfg = durability_from_sql_store(
        ws.store,
        has_command_log=has_command_log,
        once=finite,
        force=force,
    )
    try:
        assert_durable_worker_allowed(
            workflow_engine=cfg.workflow_engine,
            ledger_durability=cfg.ledger_durability,
            simulation_only=cfg.simulation_only,
            worker_enabled=cfg.worker_enabled,
            require_enabled=True,
        )
    except DurabilityGuardError as exc:
        return {
            "ok": False,
            "error": "durability_guard",
            "message": str(exc),
            "config": cfg.to_dict(),
            "hint": (
                "python -m impact_relay --durable worker --once --data-dir "
                f"{data_dir}"
            ),
        }

    wid = worker_id or f"durable-worker_{os.getpid()}"
    # Finite runs: no sleep between ticks for snappy CLI; continuous uses poll_interval
    interval = 0.0 if finite else max(0.0, float(poll_interval))
    worker = WorkflowWorker(
        ws.runtime,
        WorkerConfig(
            worker_id=wid,
            claim_batch_size=claim_batch_size,
            poll_interval_seconds=interval,
        ),
    )

    if once and max_ticks is None:
        max_ticks = 50  # safety cap for --once drain
    stop_when_idle = once or finite

    ticks = worker.run(max_ticks=max_ticks, stop_when_idle=stop_when_idle)
    ws.save()
    cases = list_operator_cases(
        ws.store,
        ws.tenant_id,
        filters=("waiting", "blocked", "dead_letter", "active", "all"),
    )
    summary = {
        "claimed": sum(t.claimed for t in ticks),
        "advanced": sum(t.advanced for t in ticks),
        "dead_lettered": sum(t.dead_lettered for t in ticks),
        "timed_out": sum(t.timed_out for t in ticks),
        "tick_count": len(ticks),
    }
    return {
        "ok": True,
        "data_dir": str(data_dir.resolve()),
        "tenant_id": ws.tenant_id,
        "worker_id": wid,
        "config": cfg.to_dict(),
        "summary": summary,
        "ticks": [t.to_dict() for t in ticks],
        "waiting": [c.to_dict() for c in cases if c.bucket == "waiting"],
        "next": (
            f"python -m impact_relay --durable list --data-dir {data_dir}"
            if any(c.bucket == "waiting" for c in cases)
            else f"python -m impact_relay --durable status --data-dir {data_dir}"
        ),
    }
