"""Versioned, number-free scaffold interchange. Not a provisioning authority.

Separate from ir-policy-v1's Python-specific serialization; never rewrite stored rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.ledger_log import snapshot_ledger_entities
from impact_relay.domain.types import Organization
from impact_relay.policy import AuthorityPolicy, PolicyError, TenantPolicy
from impact_relay.storage.sql import SqlEngine
from impact_relay.storage.workspace import (
    SqlWorkspaceRepository,
    canonical_policy_json,
    policy_from_canonical_json,
)

EMPTY_TABLES = ("tenants", "ledger_command_log", "ledger_entity", "ledger_meta", "outbox_events")


def _initialized_state(scaffold: dict[str, Any], entities: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "ir-initialized-empty-workspace-v1",
        "scaffold": scaffold,
        "ledger_binding": {
            "format": "ir-empty-ledger-binding-v1",
            "tenant_id": scaffold["tenant_id"],
            "entities": entities,
        },
        "operational": False,
    }


def decode_initialized_workspace(document: str) -> dict[str, Any]:
    """Validate state bytes, not storage evidence; accept only exactly empty bindings."""
    try:
        state = json.loads(document)
        policy = decode_scaffold(canonical_json(state["scaffold"]))
        ledger = Ledger(
            Organization(
                id=policy.tenant_id, name=policy.display_name, policy_version=policy.version
            )
        )
        expected = _initialized_state(state["scaffold"], snapshot_ledger_entities(ledger))
        if canonical_json(expected) != document:
            raise PolicyError("initialized workspace fields, binding or canonical bytes mismatch")
        return state
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PolicyError("invalid initialized workspace") from exc


def _initialized_receipt(state: dict[str, Any]) -> dict[str, Any]:
    scaffold = state["scaffold"]
    return {
        "format": "ir-initialized-workspace-verification-v1",
        "tenant_id": scaffold["tenant_id"],
        "idempotency_key": scaffold["idempotency_key"],
        "policy_sha256": scaffold["policy_sha256"],
        "scaffold_sha256": policy_hash(scaffold),
        "state_sha256": policy_hash(state),
        "storage_scope": "sql-scaffold-empty-tables-v1",
        "empty_tables": list(EMPTY_TABLES),
        "readiness": {
            "policy_initialized": True,
            "artifact_verified": True,
            "storage_initialized": True,
            "workspace_reopened": True,
            "operational": False,
        },
    }


def validate_initialized_receipt(document: str, state: dict[str, Any]) -> None:
    """Validate receipt structure/bindings only; does not establish its provenance."""
    decode_initialized_workspace(canonical_json(state))
    if canonical_json(_initialized_receipt(state)) != document:
        raise PolicyError("initialized receipt fields, hashes or canonical bytes mismatch")


def verify_initialized_workspace(
    database: str, expected_document: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reopen real SQL storage in one read-only snapshot; never accepts readiness flags.

    No migration, writes, fixture loader, authorization, or activation. Storage scope
    is precisely EMPTY_TABLES plus workspace_scaffolds, not a live host runtime.
    """
    policy = decode_scaffold(expected_document)
    engine = SqlEngine(database, read_only=True)
    with engine.conn() as conn:
        if engine.is_postgres:
            engine.execute(conn, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        else:
            engine.execute(conn, "BEGIN")

        class SnapshotEngine(SqlEngine):
            @contextmanager
            def conn(self):
                yield conn

        snapshot = SnapshotEngine(database, read_only=True)
        reopened = SqlWorkspaceRepository(snapshot).reopen(policy.tenant_id)
        actual = build_scaffold(reopened.policy, reopened.scaffold.idempotency_key)
        verify_readback(expected_document, canonical_json(actual))
        for table in EMPTY_TABLES:
            if (
                engine.fetchone(
                    conn,
                    f"SELECT tenant_id FROM {table} WHERE tenant_id=? LIMIT 1",
                    (policy.tenant_id,),
                )
                is not None
            ):
                raise PolicyError("initialized empty storage contains rows: " + table)
        entities = snapshot_ledger_entities(reopened.workspace.ledger)
        state = _initialized_state(actual, entities)
        decode_initialized_workspace(canonical_json(state))
        return state, _initialized_receipt(state)


DECIMAL = re.compile(r"(?:0|1|0\.[0-9]{0,5}[1-9])\Z")


def canonical_json(value: Any) -> str:
    """Sorted ASCII keys, scalar Unicode UTF-8, compact JSON; numbers forbidden."""

    def check(item: Any) -> None:
        if item is None or type(item) is bool:
            return
        if type(item) is str:
            item.encode("utf-8", errors="strict")
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or not key.isascii():
                    raise PolicyError("canonical keys must be ASCII strings")
                check(child)
        else:
            raise PolicyError("portable JSON forbids numbers and non-JSON values")

    try:
        check(value)
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (ValueError, UnicodeError) as exc:
        raise PolicyError("invalid portable JSON") from exc


def policy_hash(policy_document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(policy_document).encode("utf-8")).hexdigest()


def build_scaffold(policy: TenantPolicy, idempotency_key: str) -> dict[str, Any]:
    """Build an inert empty scaffold, preserving policy provenance as data only."""
    body = json.loads(canonical_policy_json(policy))["policy"]
    if type(idempotency_key) is not str or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", idempotency_key
    ):
        raise PolicyError("invalid literal idempotency_key")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", policy.version):
        raise PolicyError("invalid literal portable policy version")
    for key, value in body["confidence"].items():
        number = Decimal(str(value))
        text = (
            format(number, "f").rstrip("0").rstrip(".")
            if "." in format(number, "f")
            else str(number)
        )
        if not DECIMAL.fullmatch(text):
            raise PolicyError("confidence must be exact decimal in [0,1], at most six places")
        body["confidence"][key] = text
    confidence = body["confidence"]
    if Decimal(confidence["block_below"]) > Decimal(confidence["recommend_high"]):
        raise PolicyError("confidence thresholds are inverted")
    if not set(AuthorityPolicy().l3_command_types).issubset(body["authority"]["l3_command_types"]):
        raise PolicyError("portable scaffold must retain all L3 gates")
    if (
        not body["evidence"]["require_donor_visible"]
        or not body["notifications"]["require_separate_send_approval"]
    ):
        raise PolicyError("portable scaffold must retain evidence and send approval gates")
    document = {"format": "ir-portable-policy-v1", "policy": body}
    artifact = {
        "format": "ir-empty-scaffold-v1",
        "tenant_id": policy.tenant_id,
        "idempotency_key": idempotency_key,
        "policy": document,
        "policy_sha256": policy_hash(document),
        "empty_state": {"ledger_commands": [], "entities": [], "outbox_events": []},
        "readiness": {"scaffold_verified": False, "operational": False},
    }
    canonical_json(artifact)
    return artifact


def verify_readback(expected_document: str, persisted_document: str) -> dict[str, Any]:
    """Compare caller-supplied readback; caller must actually read durable storage.

    This verifies bytes only, not authorization, transaction atomicity or emptiness
    of external tables. The host must establish those separately before recording it.
    """
    decode_scaffold(expected_document)
    decode_scaffold(persisted_document)
    if expected_document != persisted_document:
        raise PolicyError("persisted scaffold differs from immutable request")
    artifact = json.loads(persisted_document)
    return {
        "format": "ir-scaffold-verification-v1",
        "tenant_id": artifact["tenant_id"],
        "idempotency_key": artifact["idempotency_key"],
        "policy_sha256": artifact["policy_sha256"],
        "scaffold_sha256": hashlib.sha256(persisted_document.encode("utf-8")).hexdigest(),
        "readiness": {"scaffold_verified": True, "operational": False},
    }


def decode_scaffold(document: str) -> TenantPolicy:
    """Reject unknown fields, duplicate keys, noncanonical bytes and hash drift."""
    try:
        artifact = json.loads(document)
        if canonical_json(artifact) != document:
            raise PolicyError("scaffold document is not canonical")
        body = dict(artifact["policy"]["policy"])
        confidence = body["confidence"]
        if set(confidence) != {"block_below", "recommend_high"} or any(
            type(value) is not str or not DECIMAL.fullmatch(value) for value in confidence.values()
        ):
            raise PolicyError("invalid portable confidence")
        body["confidence"] = {key: float(value) for key, value in confidence.items()}
        legacy = json.dumps(
            {"format": "ir-policy-v1", "policy": body},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        policy = policy_from_canonical_json(legacy)
        expected = build_scaffold(policy, artifact["idempotency_key"])
        if canonical_json(expected) != document:
            raise PolicyError("scaffold fields, tenant, hash or readiness mismatch")
        return policy
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PolicyError("invalid portable scaffold") from exc
