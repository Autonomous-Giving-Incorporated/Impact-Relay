"""Shared SQL connection + schema for multi-tenant storage (SQLite / Postgres)."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from impact_relay.storage.command_log import SqlLedgerCommandLog
from impact_relay.storage.ledger_repo import LedgerEntityRepository
from impact_relay.storage.objects import LocalObjectStorage, open_object_storage
from impact_relay.storage.outbox import SqlOutboxStore
from impact_relay.storage.tenants import SqlTenantRepository


class StorageBundle:
    """Opened storage root: tenants + ledger entities + outbox + objects."""

    def __init__(
        self,
        data_dir: Path,
        *,
        dsn: str | None = None,
        objects_dir: Path | None = None,
        object_store: Any | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.dsn = dsn
        self._engine = SqlEngine(dsn or self.data_dir / "storage.db")
        self._engine.migrate()
        self.tenants = SqlTenantRepository(self._engine)
        self.outbox = SqlOutboxStore(self._engine)
        self.command_log = SqlLedgerCommandLog(self._engine)
        self.ledger = LedgerEntityRepository(self._engine)
        if object_store is not None:
            self.objects = object_store
        elif objects_dir is not None:
            self.objects = LocalObjectStorage(objects_dir)
        else:
            # Respect IMPACT_RELAY_OBJECT_STORE=s3 when set
            self.objects = open_object_storage(self.data_dir)

    @property
    def is_postgres(self) -> bool:
        return self._engine.is_postgres


def to_postgres_placeholders(statement: str) -> str:
    """Rewrite ``?`` placeholders as ``%s`` for psycopg.

    A blanket ``str.replace`` would also rewrite a ``?`` inside a quoted
    literal (``WHERE note = 'why?'``), silently corrupting the query, so
    single-quoted literals are skipped. Doubled ``''`` is SQL's escaped quote
    and stays inside the literal.

    Callers must not mix ``?`` placeholders with literal ``%`` (e.g. ``LIKE
    '%x%'``) in one statement: psycopg would read the ``%`` as a format spec.
    No query in this package does.
    """
    out: list[str] = []
    in_literal = False
    i = 0
    while i < len(statement):
        ch = statement[i]
        if ch == "'":
            if in_literal and statement[i + 1 : i + 2] == "'":
                out.append("''")
                i += 2
                continue
            in_literal = not in_literal
            out.append(ch)
        elif ch == "?" and not in_literal:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class SqlEngine:
    """Minimal connection helper shared by storage repositories."""

    def __init__(self, dsn_or_path: str | Path) -> None:
        self._dsn = str(dsn_or_path)
        self._lock = threading.RLock()
        self.is_postgres = self._dsn.startswith("postgresql:") or self._dsn.startswith("postgres:")
        if not self.is_postgres:
            path = self._dsn
            if path.startswith("sqlite:///"):
                path = path[len("sqlite:///") :]
            self._sqlite_path: Path | None = Path(path)
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._sqlite_path = None

    @contextmanager
    def conn(self) -> Iterator[Any]:
        with self._lock:
            if not self.is_postgres:
                c = sqlite3.connect(str(self._sqlite_path), timeout=30)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA foreign_keys=ON")
                try:
                    yield c
                    c.commit()
                except Exception:
                    c.rollback()
                    raise
                finally:
                    c.close()
            else:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                except ImportError as exc:
                    raise RuntimeError(
                        "PostgreSQL storage requires: pip install 'impact-relay[db]'"
                    ) from exc
                with psycopg.connect(self._dsn, row_factory=dict_row) as pg_conn:
                    try:
                        yield pg_conn
                        pg_conn.commit()
                    except Exception:
                        pg_conn.rollback()
                        raise

    def sql(self, statement: str) -> str:
        if self.is_postgres and "?" in statement and "%s" not in statement:
            return to_postgres_placeholders(statement)
        return statement

    def execute(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        sql = self.sql(sql)
        if not self.is_postgres:
            return conn.execute(sql, params)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur

    def fetchone(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        sql = self.sql(sql)
        if not self.is_postgres:
            return conn.execute(sql, params).fetchone()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        sql = self.sql(sql)
        if not self.is_postgres:
            return list(conn.execute(sql, params).fetchall())
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def migrate(self) -> None:
        script = _POSTGRES_SCHEMA if self.is_postgres else _SQLITE_SCHEMA
        with self.conn() as conn:
            if not self.is_postgres:
                conn.executescript(script)
            else:
                with conn.cursor() as cur:
                    for stmt in _split(script):
                        cur.execute(stmt)


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  policy_slug TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  template_source TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ledger_command_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  command_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ledger_command_log_tenant_idx
  ON ledger_command_log (tenant_id, seq);

CREATE TABLE IF NOT EXISTS outbox_events (
  event_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  published_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx
  ON outbox_events (created_at) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS outbox_tenant_idx
  ON outbox_events (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS ledger_entity (
  tenant_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  body_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS ledger_entity_type_idx
  ON ledger_entity (tenant_id, entity_type);

CREATE TABLE IF NOT EXISTS ledger_meta (
  tenant_id TEXT PRIMARY KEY,
  organization_json TEXT NOT NULL,
  expense_receipts_json TEXT NOT NULL DEFAULT '{}',
  receipt_snapshots_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  policy_slug TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  template_source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta_json JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ledger_command_log (
  seq BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  command_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  result_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ledger_command_log_tenant_idx
  ON ledger_command_log (tenant_id, seq);

CREATE TABLE IF NOT EXISTS outbox_events (
  event_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ,
  attempts INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx
  ON outbox_events (created_at)
  WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS outbox_tenant_idx
  ON outbox_events (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS ledger_entity (
  tenant_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  body_json JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS ledger_entity_type_idx
  ON ledger_entity (tenant_id, entity_type);

CREATE TABLE IF NOT EXISTS ledger_meta (
  tenant_id TEXT PRIMARY KEY,
  organization_json JSONB NOT NULL,
  expense_receipts_json JSONB NOT NULL DEFAULT '{}',
  receipt_snapshots_json JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def open_storage(
    data_dir: Path | str | None = None,
    *,
    database_url: str | None = None,
) -> StorageBundle:
    """Open multi-tenant storage root (easy local default)."""
    root = Path(data_dir or os.environ.get("IMPACT_RELAY_DATA_DIR") or ".impact-relay")
    url = (
        database_url
        or os.environ.get("IMPACT_RELAY_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    return StorageBundle(root, dsn=url)
