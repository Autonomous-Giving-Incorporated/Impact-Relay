"""Workflow worker claim loop (PR-M4 + pilot P3).

In-process: tick / run against any WorkflowStore.
Durable pilot entrypoint: ``python -m impact_relay.workflows.worker``
or ``python -m impact_relay --durable worker --once``.

Claim + retry/DLQ + approval timeout sweeper. SQL store when data-dir is set.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from impact_relay.workflows.exceptions import classify_error
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.types import (
    RetryPolicy,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    worker_id: str = field(default_factory=lambda: f"worker_{uuid.uuid4().hex[:8]}")
    lease_ttl: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    claim_batch_size: int = 10
    max_attempts: int = 5
    poll_interval_seconds: float = 0.0  # 0 for tests; 1.0 for long-running
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    run_sweeper: bool = True


@dataclass
class TickResult:
    claimed: int = 0
    advanced: int = 0
    dead_lettered: int = 0
    timed_out: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimed": self.claimed,
            "advanced": self.advanced,
            "dead_lettered": self.dead_lettered,
            "timed_out": self.timed_out,
            "errors": list(self.errors),
        }


class WorkflowWorker:
    """Single-threaded claim-and-advance worker (memory or SQL store)."""

    def __init__(
        self,
        runtime: WorkflowRuntime,
        config: WorkerConfig | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config or WorkerConfig()
        self.store = runtime.store

    def tick(self, *, now: datetime | None = None) -> TickResult:
        """One poll: claim batch → advance each → optional timeout sweep."""
        now = now or datetime.now(timezone.utc)
        result = TickResult()
        t0 = time.perf_counter()

        claimed = self.store.claim(
            worker_id=self.config.worker_id,
            limit=self.config.claim_batch_size,
            now=now,
            lease_ttl=self.config.lease_ttl,
        )
        result.claimed = len(claimed)

        for inst in claimed:
            try:
                self._process_one(inst, result)
            except Exception as exc:  # noqa: BLE001
                msg = f"{inst.workflow_id}: {exc}"
                result.errors.append(msg)
                logger.exception("worker tick failed for %s", inst.workflow_id)
                self._handle_process_error(inst, exc, result)

        if self.config.run_sweeper and hasattr(self.store, "sweep_approval_timeouts"):
            timed = self.store.sweep_approval_timeouts(now=now)
            result.timed_out = len(timed)
            for wid in timed:
                logger.info(
                    "workflow.approval_timeout workflow_id=%s",
                    wid,
                )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "workflow.worker.tick worker_id=%s claimed=%s advanced=%s "
            "dead_lettered=%s timed_out=%s errors=%s elapsed_ms=%s",
            self.config.worker_id,
            result.claimed,
            result.advanced,
            result.dead_lettered,
            result.timed_out,
            len(result.errors),
            elapsed_ms,
        )
        return result

    def run(
        self,
        *,
        max_ticks: int | None = None,
        stop_when_idle: bool = False,
    ) -> list[TickResult]:
        """Run worker loop. max_ticks=None runs forever (use carefully)."""
        results: list[TickResult] = []
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            tick_result = self.tick()
            results.append(tick_result)
            ticks += 1
            if stop_when_idle and tick_result.claimed == 0 and tick_result.timed_out == 0:
                break
            if self.config.poll_interval_seconds > 0 and (
                max_ticks is None or ticks < max_ticks
            ):
                time.sleep(self.config.poll_interval_seconds)
        return results

    def _process_one(self, inst: WorkflowInstance, result: TickResult) -> None:
        # Dead-letter if attempts already exhausted before advance
        if inst.attempt_count >= self.config.max_attempts:
            self._dead_letter(inst, "max_attempts_exceeded")
            result.dead_lettered += 1
            return

        before_status = inst.run_status
        before_attempts = inst.attempt_count
        updated = self.runtime.advance_once(inst)
        result.advanced += 1

        # After advance, check for retry exhaustion
        refreshed = self.store.get(updated.tenant_id, updated.workflow_id)
        if refreshed is None:
            return
        if (
            refreshed.run_status == WorkflowRunStatus.RETRY_SCHEDULED
            and refreshed.attempt_count >= self.config.max_attempts
        ):
            self._dead_letter(refreshed, "max_attempts_exceeded_after_retry")
            result.dead_lettered += 1
            return

        # Apply backoff on RETRY_SCHEDULED if runtime used a coarse delay
        if refreshed.run_status == WorkflowRunStatus.RETRY_SCHEDULED:
            delay = self.config.retry_policy.delay_for_attempt(
                max(1, refreshed.attempt_count)
            )
            if self.config.retry_policy.jitter:
                delay = delay * (0.5 + random.random())
            nxt = datetime.now(timezone.utc) + timedelta(seconds=delay)
            refreshed.next_run_at = nxt.replace(microsecond=0).isoformat()
            self.store.update_instance(refreshed)

        _ = before_status, before_attempts  # reserved for future metrics

    def _handle_process_error(
        self, inst: WorkflowInstance, exc: BaseException, result: TickResult
    ) -> None:
        classified = classify_error(exc)
        current = self.store.get(inst.tenant_id, inst.workflow_id) or inst
        current.attempt_count += 1
        current.last_error = str(exc)
        if not classified.retryable or current.attempt_count >= self.config.max_attempts:
            self._dead_letter(current, f"worker_error:{classified.reason}")
            result.dead_lettered += 1
            return
        current.run_status = WorkflowRunStatus.RETRY_SCHEDULED
        delay = self.config.retry_policy.delay_for_attempt(current.attempt_count)
        nxt = datetime.now(timezone.utc) + timedelta(seconds=delay)
        current.next_run_at = nxt.replace(microsecond=0).isoformat()
        current.lease_owner = None
        current.lease_expires_at = None
        self.store.update_instance(current)

    def _dead_letter(self, inst: WorkflowInstance, reason: str) -> None:
        inst.run_status = WorkflowRunStatus.DEAD_LETTER
        inst.last_error = reason
        inst.lease_owner = None
        inst.lease_expires_at = None
        # Preserve workflow_state (business cursor) per design
        inst.touch()
        self.store.update_instance(inst)
        try:
            self.store.append_events(
                inst.tenant_id,
                inst.workflow_id,
                [
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.DEAD_LETTERED,
                        payload={"reason": reason, "attempts": inst.attempt_count},
                    )
                ],
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to append DEAD_LETTERED event for %s", inst.workflow_id)
        logger.warning(
            "workflow.dead_letter workflow_id=%s reason=%s attempts=%s",
            inst.workflow_id,
            reason,
            inst.attempt_count,
        )


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m impact_relay.workflows.worker --data-dir DIR --once``."""
    parser = argparse.ArgumentParser(
        prog="python -m impact_relay.workflows.worker",
        description=(
            "Durable workflow worker (pilot P3). Opens a durable data-dir, "
            "rehydrates the ledger command log (K17), then claim/advance."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Durable workspace (default: .impact-relay/durable)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run until idle (or --max-ticks), then exit (no WORKFLOW_WORKER_ENABLED needed)",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="Cap number of poll loops (implies finite run)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between polls when not idle (default 1.0; 0 for tests)",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="Lease owner id (default: durable-worker_<random>)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow continuous loop without WORKFLOW_WORKER_ENABLED=1",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    from impact_relay.workflows.durable import durable_worker

    try:
        out = durable_worker(
            args.data_dir,
            once=args.once,
            max_ticks=args.max_ticks,
            poll_interval=args.poll_interval,
            worker_id=args.worker_id,
            force=args.force,
        )
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        from impact_relay.workflows.guards import DurabilityGuardError

        if isinstance(exc, DurabilityGuardError):
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        raise
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
