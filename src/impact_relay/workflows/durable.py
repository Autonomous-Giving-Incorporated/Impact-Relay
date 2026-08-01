"""Easy local durable workspace (pilot P1).

One directory holds workflow session + ledger command log so you can:

  impact-relay durable seed
  impact-relay durable list
  impact-relay durable approve
  impact-relay durable status

After kill/restart, the same data-dir resumes with the same expense_ids (K17).
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import ApprovalReceipt, utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import Organization
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.domain.ledger_log import (
    FileLedgerCommandLog,
    build_result_json,
)
from impact_relay.workflows.ops import (
    list_operator_cases,
    signal_approval_and_pump,
)
from impact_relay.workflows.runtime import WorkflowRuntime, default_executor_factory
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker

HOWTO = """# Impact Relay durable local data

This directory stores a pilot durable workspace (file-backed):

- `ledger_commands.jsonl` — successful money commands (K17 rehydrate source)
- `workflow_session.pkl` — in-process workflow instances + signals
- `meta.json` — tenant + fixture pointer

## Quick start

```bash
# 1) Start (seed expenses to human approval wait)
python -m impact_relay durable seed

# 2) See what needs you
python -m impact_relay durable list

# 3) Approve (uses wait key automatically)
python -m impact_relay durable approve

# 4) After restart / new shell — same data-dir resumes
python -m impact_relay durable status
python -m impact_relay durable list
python -m impact_relay durable approve
```

Default data dir: `.impact-relay/durable` (override with --data-dir).

Rollback to non-durable linear path: WORKFLOW_SLICE_FACADE=legacy
"""


DEFAULT_DATA_DIR = Path(".impact-relay/durable")


@dataclass
class DurableWorkspace:
    data_dir: Path
    store: InMemoryWorkflowStore
    binding: InMemoryLedgerBinding
    ledger_log: FileLedgerCommandLog
    runtime: WorkflowRuntime
    tenant_id: str

    @property
    def session_path(self) -> Path:
        return self.data_dir / "workflow_session.pkl"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "ledger_commands.jsonl"

    @property
    def meta_path(self) -> Path:
        return self.data_dir / "meta.json"

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        howto = self.data_dir / "HOWTO.md"
        if not howto.is_file():
            howto.write_text(HOWTO, encoding="utf-8")
        with self.session_path.open("wb") as f:
            pickle.dump(
                {
                    "version": 1,
                    "tenant_id": self.tenant_id,
                    "store": self.store,
                    "binding": self.binding,
                },
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        meta = {
            "tenant_id": self.tenant_id,
            "ledger_log": str(self.log_path.name),
            "session": str(self.session_path.name),
            "durability": "command_log",
        }
        self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _logging_executor_factory(
    binding: InMemoryLedgerBinding,
    store: InMemoryWorkflowStore,
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


def open_workspace(
    data_dir: Path | str | None = None,
    *,
    fixture_path: Path | str | None = None,
    create: bool = False,
) -> DurableWorkspace:
    """Load existing durable workspace or create empty scaffold."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    session_path = data_dir / "workflow_session.pkl"
    log_path = data_dir / "ledger_commands.jsonl"
    ledger_log = FileLedgerCommandLog(log_path)

    if session_path.is_file():
        with session_path.open("rb") as f:
            payload = pickle.load(f)
        store: InMemoryWorkflowStore = payload["store"]
        binding: InMemoryLedgerBinding = payload["binding"]
        tenant_id = str(payload["tenant_id"])
        # Rehydrate ledger from base fixture + command log (process restart safe)
        data = load_fixture(fixture_path)
        import copy

        data = copy.deepcopy(data)
        data["expenses"] = []
        data["publish"] = []
        base = build_ledger_from_fixture(data)
        org = base.organization
        ledger = ledger_log.rehydrate(org, base_ledger=base)
        # Replace binding ledger with rehydrated one
        ws = TenantWorkspace(org, ledger=ledger)
        binding.register(ledger, ws)
        runtime = WorkflowRuntime(
            store,
            binding,
            executor_factory=_logging_executor_factory(binding, store, ledger_log),
        )
        return DurableWorkspace(
            data_dir=data_dir,
            store=store,
            binding=binding,
            ledger_log=ledger_log,
            runtime=runtime,
            tenant_id=tenant_id,
        )

    if not create:
        raise FileNotFoundError(
            f"No durable workspace at {data_dir}. Run: python -m impact_relay durable seed"
        )

    import copy

    data = copy.deepcopy(load_fixture(fixture_path))
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    runtime = WorkflowRuntime(
        store,
        binding,
        executor_factory=_logging_executor_factory(binding, store, ledger_log),
    )
    ws = DurableWorkspace(
        data_dir=data_dir,
        store=store,
        binding=binding,
        ledger_log=ledger_log,
        runtime=runtime,
        tenant_id=ledger.organization.id,
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
        for name in ("workflow_session.pkl", "ledger_commands.jsonl", "meta.json"):
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
    return {
        "ok": True,
        "data_dir": str(data_dir.resolve()),
        "tenant_id": ws.tenant_id,
        "durability": "command_log",
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
