"""SQL WorkflowStore — SQLite by default, Postgres when DSN is postgresql://.

Easy local use (no install):
  workflows.db inside --data-dir

Production pilot:
  IMPACT_RELAY_DATABASE_URL=postgresql://...  (optional dep: pip install 'impact-relay[db]')

Claim never returns pure WAITING_SIGNAL. FAILED receipts never stored.
"""

from __future__ import annotations

import builtins
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from impact_relay.agents.types import ExecutionReceipt, WorkflowState, to_jsonable, utc_now_iso
from impact_relay.storage.sql import to_postgres_placeholders
from impact_relay.workflows.exceptions import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowStateError,
)
from impact_relay.workflows.types import (
    AdvanceCommitBundle,
    SignalConsumeResult,
    SignalType,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowType,
)

_TIMEOUT_GATE_STATES = frozenset(
    {
        WorkflowState.REVIEW_PENDING,
        WorkflowState.PUBLICATION_PENDING,
        WorkflowState.NOTIFICATION_PENDING,
    }
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def _parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _j(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, default=str, sort_keys=True)


def _loads(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else {}
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    return json.loads(raw)


class SqlWorkflowStore:
    """Durable WorkflowStore using SQLite (default) or PostgreSQL."""

    def __init__(self, dsn_or_path: str | Path) -> None:
        self._dsn = str(dsn_or_path)
        self._lock = threading.RLock()
        self._is_postgres = self._dsn.startswith("postgresql:") or self._dsn.startswith("postgres:")
        self._is_sqlite = not self._is_postgres
        if self._is_sqlite:
            path = self._dsn
            if path.startswith("sqlite:///"):
                path = path[len("sqlite:///") :]
            self._sqlite_path: Path | None = Path(path)
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._sqlite_path = None
        self.migrate()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        if self._is_sqlite:
            conn = sqlite3.connect(str(self._sqlite_path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL support requires: pip install 'impact-relay[db]'"
                ) from exc
            with psycopg.connect(self._dsn, row_factory=dict_row) as pg_conn:
                try:
                    yield pg_conn
                    pg_conn.commit()
                except Exception:
                    pg_conn.rollback()
                    raise

    def migrate(self) -> None:
        with self._conn() as conn:
            if self._is_sqlite:
                conn.executescript(_SQLITE_SCHEMA)
            else:
                # psycopg executes one statement at a time
                with conn.cursor() as cur:
                    for stmt in _split_sql_statements(_POSTGRES_SCHEMA):
                        cur.execute(stmt)

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    def _row_to_instance(self, row: Any) -> WorkflowInstance:
        d = dict(row)
        wt = d["workflow_type"]
        try:
            wtype = WorkflowType(wt)
        except ValueError:
            wtype = WorkflowType.EXPENSE_TO_RECEIPT
        return WorkflowInstance(
            workflow_id=d["workflow_id"],
            tenant_id=d["tenant_id"],
            workflow_type=wtype,
            business_key=d["business_key"],
            workflow_state=WorkflowState(d["workflow_state"]),
            run_status=WorkflowRunStatus(d["run_status"]),
            context=_loads(d.get("context_json"), {}),
            simulation=bool(d.get("simulation")),
            attempt_count=int(d.get("attempt_count") or 0),
            next_run_at=d.get("next_run_at"),
            wait_deadline=d.get("wait_deadline"),
            wait_descriptor=_loads(d.get("wait_descriptor"), None),
            lease_owner=d.get("lease_owner"),
            lease_expires_at=d.get("lease_expires_at"),
            last_error=d.get("last_error"),
            timeout_applied_at=d.get("timeout_applied_at"),
            created_at=d.get("created_at") or utc_now_iso(),
            updated_at=d.get("updated_at") or utc_now_iso(),
            policy_version=d.get("policy_version") or "v1.0",
            event_seq=int(d.get("event_seq") or 0),
        )

    # ------------------------------------------------------------------
    # WorkflowStore API
    # ------------------------------------------------------------------

    def create(self, instance: WorkflowInstance) -> None:
        with self._lock, self._conn() as conn:
            try:
                self._exec(
                    conn,
                    """
                    INSERT INTO workflows (
                      workflow_id, tenant_id, workflow_type, business_key,
                      workflow_state, run_status, simulation, policy_version,
                      context_json, wait_descriptor, wait_deadline, timeout_applied_at,
                      attempt_count, next_run_at, lease_owner, lease_expires_at,
                      last_error, created_at, updated_at, event_seq
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        instance.workflow_id,
                        instance.tenant_id,
                        instance.workflow_type.value
                        if isinstance(instance.workflow_type, WorkflowType)
                        else str(instance.workflow_type),
                        instance.business_key,
                        instance.workflow_state.value,
                        instance.run_status.value,
                        instance.simulation if self._is_postgres else int(instance.simulation),
                        instance.policy_version,
                        _j(instance.context),
                        _j(instance.wait_descriptor) if instance.wait_descriptor else None,
                        instance.wait_deadline,
                        instance.timeout_applied_at,
                        instance.attempt_count,
                        instance.next_run_at or utc_now_iso(),
                        instance.lease_owner,
                        instance.lease_expires_at,
                        instance.last_error,
                        instance.created_at,
                        instance.updated_at,
                        instance.event_seq,
                    ),
                )
            except Exception as exc:
                msg = str(exc).lower()
                if "unique" in msg or "duplicate" in msg:
                    raise WorkflowConflictError(
                        f"workflow or business_key conflict: {instance.workflow_id}"
                    ) from exc
                raise

    def get(self, tenant_id: str, workflow_id: str) -> WorkflowInstance | None:
        with self._lock, self._conn() as conn:
            row = self._fetchone(
                conn,
                "SELECT * FROM workflows WHERE workflow_id=? AND tenant_id=?",
                (workflow_id, tenant_id),
            )
            return self._row_to_instance(row) if row else None

    def get_by_business_key(
        self, tenant_id: str, workflow_type: WorkflowType | str, business_key: str
    ) -> WorkflowInstance | None:
        wt = workflow_type.value if isinstance(workflow_type, WorkflowType) else str(workflow_type)
        with self._lock, self._conn() as conn:
            row = self._fetchone(
                conn,
                """
                SELECT * FROM workflows
                WHERE tenant_id=? AND workflow_type=? AND business_key=?
                """,
                (tenant_id, wt, business_key),
            )
            return self._row_to_instance(row) if row else None

    def list(
        self,
        tenant_id: str,
        *,
        workflow_state: list[str] | None = None,
        run_status: list[str] | None = None,
        limit: int = 100,
    ) -> list[WorkflowInstance]:
        with self._lock, self._conn() as conn:
            sql = "SELECT * FROM workflows WHERE tenant_id=?"
            params: list[Any] = [tenant_id]
            if workflow_state:
                placeholders = ",".join("?" * len(workflow_state))
                sql += f" AND workflow_state IN ({placeholders})"
                params.extend(workflow_state)
            if run_status:
                placeholders = ",".join("?" * len(run_status))
                sql += f" AND run_status IN ({placeholders})"
                params.extend(run_status)
            sql += " ORDER BY created_at LIMIT ?"
            params.append(limit)
            rows = self._fetchall(conn, sql, tuple(params))
            return [self._row_to_instance(r) for r in rows]

    def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_ttl: timedelta,
    ) -> builtins.list[WorkflowInstance]:
        now_iso = _iso(now) or utc_now_iso()
        lease_exp = _iso(now + lease_ttl)
        with self._lock, self._conn() as conn:
            if self._is_postgres:
                rows = self._fetchall(
                    conn,
                    """
                    SELECT * FROM workflows
                    WHERE next_run_at <= %s
                      AND (
                        run_status IN ('PENDING', 'RETRY_SCHEDULED')
                        OR (run_status = 'RUNNING' AND lease_expires_at < %s)
                      )
                    ORDER BY next_run_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (now_iso, now_iso, limit),
                    postgres=True,
                )
            else:
                # SQLite: transaction exclusive enough for single-writer pilot
                rows = self._fetchall(
                    conn,
                    """
                    SELECT * FROM workflows
                    WHERE next_run_at <= ?
                      AND (
                        run_status IN ('PENDING', 'RETRY_SCHEDULED')
                        OR (run_status = 'RUNNING' AND lease_expires_at < ?)
                      )
                    ORDER BY next_run_at
                    LIMIT ?
                    """,
                    (now_iso, now_iso, limit),
                )
            claimed: list[WorkflowInstance] = []
            for row in rows:
                wid = row["workflow_id"]
                self._exec(
                    conn,
                    """
                    UPDATE workflows SET
                      run_status='RUNNING',
                      lease_owner=?,
                      lease_expires_at=?,
                      updated_at=?
                    WHERE workflow_id=?
                    """,
                    (worker_id, lease_exp, now_iso, wid),
                )
                inst = self._row_to_instance(row)
                inst.run_status = WorkflowRunStatus.RUNNING
                inst.lease_owner = worker_id
                inst.lease_expires_at = lease_exp
                inst.updated_at = now_iso
                claimed.append(inst)
            return claimed

    def update_instance(self, instance: WorkflowInstance) -> None:
        with self._lock, self._conn() as conn:
            cur = self._exec(
                conn,
                """
                UPDATE workflows SET
                  workflow_state=?, run_status=?, context_json=?,
                  wait_descriptor=?, wait_deadline=?, timeout_applied_at=?,
                  attempt_count=?, next_run_at=?, lease_owner=?, lease_expires_at=?,
                  last_error=?, updated_at=?, event_seq=?, policy_version=?,
                  simulation=?
                WHERE workflow_id=? AND tenant_id=?
                """,
                (
                    instance.workflow_state.value,
                    instance.run_status.value,
                    _j(instance.context),
                    _j(instance.wait_descriptor) if instance.wait_descriptor else None,
                    instance.wait_deadline,
                    instance.timeout_applied_at,
                    instance.attempt_count,
                    instance.next_run_at,
                    instance.lease_owner,
                    instance.lease_expires_at,
                    instance.last_error,
                    instance.updated_at or utc_now_iso(),
                    instance.event_seq,
                    instance.policy_version,
                    instance.simulation if self._is_postgres else int(instance.simulation),
                    instance.workflow_id,
                    instance.tenant_id,
                ),
            )
            if self._rowcount(cur) == 0:
                raise WorkflowNotFoundError(instance.workflow_id)

    def append_events(
        self,
        tenant_id: str,
        workflow_id: str,
        events: builtins.list[WorkflowEventWrite] | builtins.list[WorkflowEvent],
    ) -> None:
        with self._lock, self._conn() as conn:
            row = self._fetchone(
                conn,
                "SELECT event_seq FROM workflows WHERE workflow_id=? AND tenant_id=?",
                (workflow_id, tenant_id),
            )
            if not row:
                raise WorkflowNotFoundError(workflow_id)
            seq = int(row["event_seq"] or 0)
            for ev in events:
                if isinstance(ev, WorkflowEvent):
                    seq = max(seq, ev.seq)
                    self._insert_event(conn, ev)
                    continue
                seq += 1
                try:
                    etype = (
                        ev.event_type
                        if isinstance(ev.event_type, WorkflowEventType)
                        else WorkflowEventType(str(ev.event_type))
                    )
                except ValueError:
                    etype = WorkflowEventType.ERROR
                self._insert_event(
                    conn,
                    WorkflowEvent(
                        event_id=f"evt_{workflow_id}_{seq}",
                        workflow_id=workflow_id,
                        tenant_id=tenant_id,
                        seq=seq,
                        event_type=etype,
                        payload=dict(ev.payload),
                        at=ev.at or utc_now_iso(),
                    ),
                )
            self._exec(
                conn,
                "UPDATE workflows SET event_seq=?, updated_at=? WHERE workflow_id=?",
                (seq, utc_now_iso(), workflow_id),
            )

    def _insert_event(self, conn: Any, event: WorkflowEvent) -> None:
        self._exec(
            conn,
            """
            INSERT INTO workflow_events (
              event_id, workflow_id, tenant_id, seq, event_type, payload_json, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                event.workflow_id,
                event.tenant_id,
                event.seq,
                event.event_type.value
                if isinstance(event.event_type, WorkflowEventType)
                else str(event.event_type),
                _j(event.payload),
                event.at,
            ),
        )

    def list_events(self, tenant_id: str, workflow_id: str) -> builtins.list[WorkflowEvent]:
        with self._lock, self._conn() as conn:
            rows = self._fetchall(
                conn,
                """
                SELECT * FROM workflow_events
                WHERE workflow_id=? AND tenant_id=?
                ORDER BY seq
                """,
                (workflow_id, tenant_id),
            )
            out: list[WorkflowEvent] = []
            for r in rows:
                et = r["event_type"]
                try:
                    etype = WorkflowEventType(et)
                except ValueError:
                    etype = WorkflowEventType.ERROR
                out.append(
                    WorkflowEvent(
                        event_id=r["event_id"],
                        workflow_id=r["workflow_id"],
                        tenant_id=r["tenant_id"],
                        seq=int(r["seq"]),
                        event_type=etype,
                        payload=_loads(r["payload_json"], {}),
                        at=r["created_at"],
                    )
                )
            return out

    def enqueue_signal_and_wake(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        signal: WorkflowSignal,
        new_run_status: WorkflowRunStatus,
        next_run_at: datetime | str,
        clear_lease: bool,
    ) -> None:
        nxt = _iso(next_run_at) if not isinstance(next_run_at, str) else next_run_at
        with self._lock, self._conn() as conn:
            row = self._fetchone(
                conn,
                "SELECT run_status FROM workflows WHERE workflow_id=? AND tenant_id=?",
                (workflow_id, tenant_id),
            )
            if not row:
                raise WorkflowNotFoundError(workflow_id)
            self._exec(
                conn,
                """
                INSERT INTO workflow_signals (
                  signal_id, workflow_id, tenant_id, signal_type,
                  payload_json, created_at, consumed_at, consume_result
                ) VALUES (?,?,?,?,?,?,NULL,NULL)
                """,
                (
                    signal.signal_id,
                    workflow_id,
                    tenant_id,
                    signal.signal_type.value
                    if isinstance(signal.signal_type, SignalType)
                    else str(signal.signal_type),
                    _j(signal.payload),
                    signal.created_at,
                ),
            )
            if clear_lease:
                self._exec(
                    conn,
                    """
                    UPDATE workflows SET
                      run_status=?, next_run_at=?, lease_owner=NULL,
                      lease_expires_at=NULL, updated_at=?
                    WHERE workflow_id=?
                    """,
                    (new_run_status.value, nxt, utc_now_iso(), workflow_id),
                )
            else:
                self._exec(
                    conn,
                    """
                    UPDATE workflows SET run_status=?, next_run_at=?, updated_at=?
                    WHERE workflow_id=?
                    """,
                    (new_run_status.value, nxt, utc_now_iso(), workflow_id),
                )

    def take_unconsumed_signals(
        self, tenant_id: str, workflow_id: str
    ) -> builtins.list[WorkflowSignal]:
        with self._lock, self._conn() as conn:
            rows = self._fetchall(
                conn,
                """
                SELECT * FROM workflow_signals
                WHERE workflow_id=? AND tenant_id=? AND consumed_at IS NULL
                ORDER BY created_at
                """,
                (workflow_id, tenant_id),
            )
            out: list[WorkflowSignal] = []
            for r in rows:
                st = r["signal_type"]
                try:
                    stype = SignalType(st)
                except ValueError:
                    stype = SignalType.RESUBMIT
                out.append(
                    WorkflowSignal(
                        signal_id=r["signal_id"],
                        workflow_id=r["workflow_id"],
                        tenant_id=r["tenant_id"],
                        signal_type=stype,
                        payload=_loads(r["payload_json"], {}),
                        created_at=r["created_at"],
                        consumed=False,
                        consume_result=r["consume_result"],
                    )
                )
            return out

    def mark_signal_consumed(self, tenant_id: str, signal_id: str, result: str) -> None:
        with self._lock, self._conn() as conn:
            self._exec(
                conn,
                """
                UPDATE workflow_signals SET consumed_at=?, consume_result=?
                WHERE signal_id=? AND tenant_id=?
                """,
                (utc_now_iso(), result, signal_id, tenant_id),
            )

    def put_execution_receipt(self, receipt: ExecutionReceipt, *, workflow_id: str) -> None:
        if receipt.status not in ("SUCCEEDED", "SIMULATED", "SKIPPED"):
            raise WorkflowStateError(
                f"must not store FAILED receipt for idempotency: {receipt.status}"
            )
        params = (
            receipt.tenant_id,
            receipt.idempotency_key,
            receipt.execution_id,
            workflow_id,
            receipt.command_type,
            receipt.status,
            _j(to_jsonable(receipt)),
            receipt.executed_at,
        )
        with self._lock, self._conn() as conn:
            if self._is_sqlite:
                self._exec(
                    conn,
                    """
                    INSERT OR REPLACE INTO execution_receipts (
                      tenant_id, idempotency_key, execution_id, workflow_id,
                      command_type, status, receipt_json, created_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    params,
                )
            else:
                self._exec(
                    conn,
                    """
                    INSERT INTO execution_receipts (
                      tenant_id, idempotency_key, execution_id, workflow_id,
                      command_type, status, receipt_json, created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                      receipt_json=EXCLUDED.receipt_json,
                      status=EXCLUDED.status,
                      execution_id=EXCLUDED.execution_id
                    """,
                    params,
                    postgres=True,
                )

    def get_execution_receipt(
        self, tenant_id: str, idempotency_key: str
    ) -> ExecutionReceipt | None:
        with self._lock, self._conn() as conn:
            row = self._fetchone(
                conn,
                """
                SELECT receipt_json FROM execution_receipts
                WHERE tenant_id=? AND idempotency_key=?
                """,
                (tenant_id, idempotency_key),
            )
            if not row:
                return None
            data = _loads(row["receipt_json"], {})
            return ExecutionReceipt(
                execution_id=data["execution_id"],
                tenant_id=data["tenant_id"],
                command_type=data["command_type"],
                idempotency_key=data["idempotency_key"],
                status=data["status"],
                output_refs=list(data.get("output_refs") or []),
                output_hash=data.get("output_hash", ""),
                executed_at=data.get("executed_at") or utc_now_iso(),
                simulated=bool(data.get("simulated", False)),
                error=data.get("error"),
                approval_id=data.get("approval_id"),
            )

    def commit_advance(self, bundle: AdvanceCommitBundle) -> None:
        with self._lock, self._conn() as conn:
            inst = bundle.instance
            cur = self._exec(
                conn,
                """
                UPDATE workflows SET
                  workflow_state=?, run_status=?, context_json=?,
                  wait_descriptor=?, wait_deadline=?, timeout_applied_at=?,
                  attempt_count=?, next_run_at=?, lease_owner=?, lease_expires_at=?,
                  last_error=?, updated_at=?, event_seq=?, policy_version=?
                WHERE workflow_id=? AND tenant_id=?
                """,
                (
                    inst.workflow_state.value,
                    inst.run_status.value,
                    _j(inst.context),
                    _j(inst.wait_descriptor) if inst.wait_descriptor else None,
                    inst.wait_deadline,
                    inst.timeout_applied_at,
                    inst.attempt_count,
                    inst.next_run_at,
                    inst.lease_owner,
                    inst.lease_expires_at,
                    inst.last_error,
                    inst.updated_at or utc_now_iso(),
                    inst.event_seq,
                    inst.policy_version,
                    inst.workflow_id,
                    inst.tenant_id,
                ),
            )
            if self._rowcount(cur) == 0:
                raise WorkflowNotFoundError(inst.workflow_id)

            # events
            seq = int(inst.event_seq or 0)
            for ev in bundle.events:
                if isinstance(ev, WorkflowEvent):
                    self._insert_event(conn, ev)
                    seq = max(seq, ev.seq)
                    continue
                seq += 1
                try:
                    etype = (
                        ev.event_type
                        if isinstance(ev.event_type, WorkflowEventType)
                        else WorkflowEventType(str(ev.event_type))
                    )
                except ValueError:
                    etype = WorkflowEventType.ERROR
                self._insert_event(
                    conn,
                    WorkflowEvent(
                        event_id=f"evt_{bundle.workflow_id}_{seq}",
                        workflow_id=bundle.workflow_id,
                        tenant_id=bundle.tenant_id,
                        seq=seq,
                        event_type=etype,
                        payload=dict(ev.payload),
                        at=ev.at or utc_now_iso(),
                    ),
                )
            self._exec(
                conn,
                "UPDATE workflows SET event_seq=? WHERE workflow_id=?",
                (seq, bundle.workflow_id),
            )

            for receipt in bundle.execution_receipts:
                if receipt.status not in ("SUCCEEDED", "SIMULATED", "SKIPPED"):
                    continue
                if self._is_sqlite:
                    self._exec(
                        conn,
                        """
                        INSERT OR REPLACE INTO execution_receipts (
                          tenant_id, idempotency_key, execution_id, workflow_id,
                          command_type, status, receipt_json, created_at
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            receipt.tenant_id,
                            receipt.idempotency_key,
                            receipt.execution_id,
                            bundle.workflow_id,
                            receipt.command_type,
                            receipt.status,
                            _j(to_jsonable(receipt)),
                            receipt.executed_at,
                        ),
                    )
                else:
                    self._exec(
                        conn,
                        """
                        INSERT INTO execution_receipts (
                          tenant_id, idempotency_key, execution_id, workflow_id,
                          command_type, status, receipt_json, created_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                          receipt_json=EXCLUDED.receipt_json
                        """,
                        (
                            receipt.tenant_id,
                            receipt.idempotency_key,
                            receipt.execution_id,
                            bundle.workflow_id,
                            receipt.command_type,
                            receipt.status,
                            _j(to_jsonable(receipt)),
                            receipt.executed_at,
                        ),
                        postgres=True,
                    )

            for signal_id, result in bundle.consume_signals:
                res = result.value if isinstance(result, SignalConsumeResult) else str(result)
                self._exec(
                    conn,
                    """
                    UPDATE workflow_signals SET consumed_at=?, consume_result=?
                    WHERE signal_id=? AND tenant_id=?
                    """,
                    (utc_now_iso(), res, signal_id, bundle.tenant_id),
                )

    def sweep_approval_timeouts(self, now: datetime | None = None) -> builtins.list[str]:
        now = now or _now()
        now_iso = _iso(now) or utc_now_iso()
        timed: list[str] = []
        with self._lock, self._conn() as conn:
            rows = self._fetchall(
                conn,
                """
                SELECT * FROM workflows
                WHERE run_status='WAITING_SIGNAL'
                  AND wait_deadline IS NOT NULL
                  AND wait_deadline < ?
                  AND timeout_applied_at IS NULL
                  AND workflow_state IN (
                      'REVIEW_PENDING','PUBLICATION_PENDING','NOTIFICATION_PENDING'
                  )
                """,
                (now_iso,),
            )
            for row in rows:
                inst = self._row_to_instance(row)
                prior_wait = dict(inst.context.get("wait") or {})
                prior_key = (
                    (inst.wait_descriptor or {}).get("command_idempotency_key")
                    or prior_wait.get("command_idempotency_key")
                    or (prior_wait.get("frozen_command") or {}).get("idempotency_key")
                )
                ctx = dict(inst.context)
                if "wait" in ctx:
                    ctx["expired_wait"] = ctx.pop("wait")
                ctx["wait_expired"] = True
                wait_desc = {
                    "signal_type": "RESUBMIT",
                    "reason": "approval_timeout",
                    "prior_command_idempotency_key": prior_key,
                }
                seq = inst.event_seq + 1
                self._exec(
                    conn,
                    """
                    UPDATE workflows SET
                      workflow_state='NEEDS_INFORMATION',
                      run_status='WAITING_SIGNAL',
                      last_error='approval_timeout',
                      wait_deadline=NULL,
                      timeout_applied_at=?,
                      wait_descriptor=?,
                      context_json=?,
                      event_seq=?,
                      updated_at=?
                    WHERE workflow_id=?
                    """,
                    (
                        now_iso,
                        _j(wait_desc),
                        _j(ctx),
                        seq,
                        now_iso,
                        inst.workflow_id,
                    ),
                )
                self._insert_event(
                    conn,
                    WorkflowEvent(
                        event_id=f"evt_{inst.workflow_id}_{seq}",
                        workflow_id=inst.workflow_id,
                        tenant_id=inst.tenant_id,
                        seq=seq,
                        event_type=WorkflowEventType.APPROVAL_TIMEOUT,
                        payload={
                            "reason": "approval_timeout",
                            "prior_command_idempotency_key": prior_key,
                        },
                        at=now_iso,
                    ),
                )
                timed.append(inst.workflow_id)
        return timed

    # ------------------------------------------------------------------
    # DB helpers (sqlite placeholders; rewrite for postgres)
    # ------------------------------------------------------------------

    def _sql(self, sql: str, *, postgres: bool = False) -> str:
        if self._is_postgres or postgres:
            # convert ? to %s when using postgres path
            if "?" in sql and "%s" not in sql:
                return to_postgres_placeholders(sql)
            return sql
        return sql

    def _exec(
        self, conn: Any, sql: str, params: tuple[Any, ...] | None = None, *, postgres: bool = False
    ) -> Any:
        sql = self._sql(sql, postgres=postgres or self._is_postgres)
        if self._is_sqlite:
            return conn.execute(sql, params or ())
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur

    def _fetchone(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        sql = self._sql(sql)
        if self._is_sqlite:
            return conn.execute(sql, params).fetchone()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _fetchall(
        self, conn: Any, sql: str, params: tuple[Any, ...] = (), *, postgres: bool = False
    ) -> builtins.list[Any]:
        sql = self._sql(sql, postgres=postgres or self._is_postgres)
        if self._is_sqlite:
            return list(conn.execute(sql, params).fetchall())
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _rowcount(self, cur: Any) -> int:
        return int(getattr(cur, "rowcount", 0) or 0)


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
  workflow_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  workflow_type TEXT NOT NULL,
  business_key TEXT NOT NULL,
  workflow_state TEXT NOT NULL,
  run_status TEXT NOT NULL,
  simulation INTEGER NOT NULL DEFAULT 0,
  policy_version TEXT NOT NULL DEFAULT 'v1.0',
  context_json TEXT NOT NULL DEFAULT '{}',
  wait_descriptor TEXT,
  wait_deadline TEXT,
  timeout_applied_at TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_run_at TEXT NOT NULL,
  lease_owner TEXT,
  lease_expires_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  event_seq INTEGER NOT NULL DEFAULT 0,
  UNIQUE (tenant_id, workflow_type, business_key)
);
CREATE INDEX IF NOT EXISTS workflows_claim_idx
  ON workflows (next_run_at) WHERE run_status IN ('PENDING', 'RETRY_SCHEDULED');
CREATE INDEX IF NOT EXISTS workflows_tenant_idx
  ON workflows (tenant_id, workflow_state, run_status);

CREATE TABLE IF NOT EXISTS workflow_events (
  event_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (workflow_id, seq),
  FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS workflow_signals (
  signal_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  consumed_at TEXT,
  consume_result TEXT,
  FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);
CREATE INDEX IF NOT EXISTS workflow_signals_pending_idx
  ON workflow_signals (workflow_id);

CREATE TABLE IF NOT EXISTS execution_receipts (
  tenant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  execution_id TEXT NOT NULL,
  workflow_id TEXT,
  command_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'SIMULATED', 'SKIPPED')),
  receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, idempotency_key)
);
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
  workflow_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  workflow_type TEXT NOT NULL,
  business_key TEXT NOT NULL,
  workflow_state TEXT NOT NULL,
  run_status TEXT NOT NULL,
  simulation BOOLEAN NOT NULL DEFAULT FALSE,
  policy_version TEXT NOT NULL DEFAULT 'v1.0',
  context_json JSONB NOT NULL DEFAULT '{}',
  wait_descriptor JSONB,
  wait_deadline TIMESTAMPTZ,
  timeout_applied_at TIMESTAMPTZ,
  attempt_count INT NOT NULL DEFAULT 0,
  next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  lease_owner TEXT,
  lease_expires_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_seq INT NOT NULL DEFAULT 0,
  UNIQUE (tenant_id, workflow_type, business_key)
);
CREATE INDEX IF NOT EXISTS workflows_claim_idx
  ON workflows (next_run_at)
  WHERE run_status IN ('PENDING', 'RETRY_SCHEDULED');
CREATE INDEX IF NOT EXISTS workflows_lease_reclaim_idx
  ON workflows (lease_expires_at)
  WHERE run_status = 'RUNNING';
CREATE INDEX IF NOT EXISTS workflows_tenant_state_idx
  ON workflows (tenant_id, workflow_state, run_status);

CREATE TABLE IF NOT EXISTS workflow_events (
  event_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
  tenant_id TEXT NOT NULL,
  seq INT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workflow_id, seq)
);

CREATE TABLE IF NOT EXISTS workflow_signals (
  signal_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
  tenant_id TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consumed_at TIMESTAMPTZ,
  consume_result TEXT
);
CREATE INDEX IF NOT EXISTS workflow_signals_pending_idx
  ON workflow_signals (workflow_id)
  WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS execution_receipts (
  tenant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  execution_id TEXT NOT NULL,
  workflow_id TEXT,
  command_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'SIMULATED', 'SKIPPED')),
  receipt_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, idempotency_key)
);
"""


def _split_sql_statements(script: str) -> list[str]:
    """Split a multi-statement SQL script on semicolons (no procedure bodies)."""
    parts: list[str] = []
    for raw in script.split(";"):
        stmt = raw.strip()
        if stmt:
            parts.append(stmt)
    return parts


def open_sql_store(
    data_dir: Path | str | None = None, database_url: str | None = None
) -> SqlWorkflowStore:
    """Open store: DATABASE_URL / env, else SQLite under data_dir/workflows.db."""
    import os

    url = (
        database_url
        or os.environ.get("IMPACT_RELAY_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if url:
        return SqlWorkflowStore(url)
    data_dir = Path(data_dir or ".impact-relay/durable")
    return SqlWorkflowStore(data_dir / "workflows.db")
