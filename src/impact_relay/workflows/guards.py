"""Startup durability guards (K11) for pilot workers.

SQL workflow engine must not claim non-simulation money work without a
co-durable ledger (command_log / snapshot / repos).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

WorkflowEngine = Literal["memory", "sqlite", "postgres"]
LedgerDurability = Literal["none", "command_log", "snapshot", "repos"]


class DurabilityGuardError(RuntimeError):
    """Raised when worker config violates K11 or enablement rules."""


@dataclass(frozen=True)
class DurabilityConfig:
    workflow_engine: WorkflowEngine
    ledger_durability: LedgerDurability
    worker_enabled: bool
    simulation_only: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_engine": self.workflow_engine,
            "ledger_durability": self.ledger_durability,
            "worker_enabled": self.worker_enabled,
            "simulation_only": self.simulation_only,
        }


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_worker_enabled(*, once: bool = False, force: bool = False) -> bool:
    """Continuous workers need WORKFLOW_WORKER_ENABLED=1 (or --force).

    ``--once`` / finite ``--max-ticks`` always allowed when durability passes.
    """
    if once or force:
        return True
    return env_flag("WORKFLOW_WORKER_ENABLED", default=False)


def assert_durable_worker_allowed(
    *,
    workflow_engine: WorkflowEngine,
    ledger_durability: LedgerDurability,
    simulation_only: bool = False,
    worker_enabled: bool = True,
    require_enabled: bool = True,
) -> None:
    """Refuse unsafe pilot configurations (K11).

    - Continuous run: worker_enabled must be true (env or --force / --once).
    - postgres/sqlite + non-sim: ledger_durability must not be ``none``.
    - memory + none is allowed only for in-process unit tests (callers skip guard).
    """
    if require_enabled and not worker_enabled:
        raise DurabilityGuardError(
            "Worker not enabled. Use --once for a single poll, or set "
            "WORKFLOW_WORKER_ENABLED=1 (or --force) for a continuous loop."
        )
    if simulation_only:
        return
    if workflow_engine in ("postgres", "sqlite") and ledger_durability == "none":
        raise DurabilityGuardError(
            "K11: refusing SQL workflow worker without durable ledger. "
            "Use a durable data-dir with ledger_commands.jsonl "
            "(python -m impact_relay --durable seed), or simulation-only tenants."
        )
    if workflow_engine == "postgres" and ledger_durability == "none":
        # defensive second check (same condition) for design-doc wording
        raise DurabilityGuardError(
            "K11: WORKFLOW_ENGINE=postgres requires LEDGER_DURABILITY != none"
        )


def durability_from_sql_store(
    store: object,
    *,
    has_command_log: bool,
    once: bool = False,
    force: bool = False,
) -> DurabilityConfig:
    is_pg = bool(getattr(store, "_is_postgres", False))
    engine: WorkflowEngine = "postgres" if is_pg else "sqlite"
    ledger: LedgerDurability = "command_log" if has_command_log else "none"
    return DurabilityConfig(
        workflow_engine=engine,
        ledger_durability=ledger,
        worker_enabled=resolve_worker_enabled(once=once, force=force),
        simulation_only=False,
    )
