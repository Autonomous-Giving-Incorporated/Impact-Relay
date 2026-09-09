"""Immutable tenant scaffolds. Internal storage APIs, not provisioning authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from impact_relay.storage.sql import SqlEngine

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.ledger_log import LedgerLogError, apply_result_json
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import Organization
from impact_relay.policy import (
    AttributionPolicy,
    AuthorityPolicy,
    ConfidencePolicy,
    EvidencePolicy,
    NotificationPolicy,
    PolicyError,
    TenantPolicy,
)
from impact_relay.storage.command_log import SqlLedgerCommandLog


def _validate_shape(value: Any, example: Any) -> None:
    if isinstance(example, dict):
        if not isinstance(value, dict) or value.keys() != example.keys():
            raise PolicyError("canonical policy fields mismatch")
        for key in example:
            _validate_shape(value[key], example[key])
    elif isinstance(example, list):
        if not isinstance(value, list) or any(type(item) is not str for item in value):
            raise PolicyError("canonical policy requires string lists")
    elif example is None:
        if value is not None and type(value) is not str:
            raise PolicyError("invalid source_path provenance")
    elif isinstance(example, float):
        if type(value) not in (float, int):
            raise PolicyError("canonical policy requires numeric confidence")
    elif type(value) is not type(example):
        raise PolicyError("canonical policy field type mismatch")


def _tenant_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise PolicyError("invalid literal tenant_id")


def canonical_policy_json(policy: TenantPolicy) -> str:
    """Versioned lossless model JSON, not the permissive YAML parser format."""
    body = policy.to_dict()
    _validate_shape(body, TenantPolicy(tenant_id="example", version="v1").to_dict())
    _tenant_id(policy.tenant_id)
    if not policy.version or not policy.version.strip():
        raise PolicyError("policy version is required")
    try:
        return json.dumps(
            {"format": "ir-policy-v1", "policy": body},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except ValueError as exc:
        raise PolicyError("canonical policy must contain finite numbers") from exc


def policy_from_canonical_json(document: str) -> TenantPolicy:
    """Decode strictly; preserve empty tuples and original source provenance."""
    try:
        data = json.loads(document)
        if not isinstance(data, dict) or set(data) != {"format", "policy"}:
            raise PolicyError("invalid canonical policy envelope")
        if data["format"] != "ir-policy-v1":
            raise PolicyError("unsupported canonical policy format")
        body = data["policy"]
        _validate_shape(body, TenantPolicy(tenant_id="example", version="v1").to_dict())
        fields = dict(body)
        for name, cls in (
            ("confidence", ConfidencePolicy),
            ("evidence", EvidencePolicy),
            ("attribution", AttributionPolicy),
            ("notifications", NotificationPolicy),
            ("authority", AuthorityPolicy),
        ):
            values: dict[str, Any] = {
                key: tuple(value) if isinstance(value, list) else value
                for key, value in body[name].items()
            }
            fields[name] = cls(**values)
        policy = TenantPolicy(**fields)
        if canonical_policy_json(policy) != document:
            raise PolicyError("policy document is not canonical")
        return policy
    except (TypeError, ValueError) as exc:
        raise PolicyError("invalid canonical policy document") from exc


class WorkspaceConflict(ValueError):
    """Tenant already has a different immutable scaffold request."""


@dataclass(frozen=True)
class WorkspaceScaffold:
    tenant_id: str
    idempotency_key: str
    policy_json: str

    @property
    def runtime_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class ReopenedWorkspace:
    scaffold: WorkspaceScaffold
    policy: TenantPolicy
    workspace: TenantWorkspace


class SqlWorkspaceRepository:
    """Trusted internal create/read API. Never authorizes or activates tenants."""

    def __init__(self, engine: SqlEngine) -> None:
        self._engine = engine

    def create(self, *, policy: TenantPolicy, idempotency_key: str) -> WorkspaceScaffold:
        document = canonical_policy_json(policy)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        expected = WorkspaceScaffold(policy.tenant_id, idempotency_key, document)
        with self._engine.conn() as conn:
            inserted = self._engine.fetchone(
                conn,
                """
                INSERT INTO workspace_scaffolds (tenant_id, idempotency_key, policy_json)
                VALUES (?, ?, ?) ON CONFLICT (tenant_id) DO NOTHING RETURNING tenant_id
                """,
                (policy.tenant_id, idempotency_key, document),
            )
            if inserted is not None:
                for table in (
                    "tenants",
                    "ledger_command_log",
                    "ledger_entity",
                    "ledger_meta",
                    "outbox_events",
                ):
                    existing = self._engine.fetchone(
                        conn,
                        f"SELECT tenant_id FROM {table} WHERE tenant_id = ? LIMIT 1",
                        (policy.tenant_id,),
                    )
                    if existing is not None:
                        raise WorkspaceConflict(
                            "existing tenant storage requires explicit migration"
                        )
            row = self._engine.fetchone(
                conn, "SELECT * FROM workspace_scaffolds WHERE tenant_id = ?", (policy.tenant_id,)
            )
            actual = WorkspaceScaffold(row["tenant_id"], row["idempotency_key"], row["policy_json"])
            if actual != expected:
                raise WorkspaceConflict("workspace idempotency conflict")
        return actual

    def get(self, tenant_id: str) -> WorkspaceScaffold | None:
        _tenant_id(tenant_id)
        with self._engine.conn() as conn:
            row = self._engine.fetchone(
                conn, "SELECT * FROM workspace_scaffolds WHERE tenant_id = ?", (tenant_id,)
            )
        if row is None:
            return None
        policy = policy_from_canonical_json(row["policy_json"])
        if policy.tenant_id != tenant_id:
            raise PolicyError("workspace policy tenant mismatch")
        return WorkspaceScaffold(row["tenant_id"], row["idempotency_key"], row["policy_json"])

    def reopen(self, tenant_id: str) -> ReopenedWorkspace:
        scaffold = self.get(tenant_id)
        if scaffold is None:
            raise KeyError(tenant_id)
        policy = policy_from_canonical_json(scaffold.policy_json)
        organization = Organization(
            id=tenant_id, name=policy.display_name, policy_version=policy.version
        )
        ledger = Ledger(organization)
        for row in SqlLedgerCommandLog(self._engine).iter_rows(tenant_id):
            result = row["result_json"]
            for group in result.get("entities", {}).values():
                if isinstance(group, dict):
                    for entity in group.values():
                        if isinstance(entity, dict) and "organization_id" in entity:
                            if entity["organization_id"] != tenant_id:
                                raise LedgerLogError("cross-tenant entity in workspace command log")
            apply_result_json(ledger, result)
        return ReopenedWorkspace(scaffold, policy, TenantWorkspace(organization, ledger=ledger))
