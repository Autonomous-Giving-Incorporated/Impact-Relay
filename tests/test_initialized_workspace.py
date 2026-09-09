"""Initialized-empty evidence must come from durable read-only reopen, not flags."""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from impact_relay.policy import PolicyError
from impact_relay.storage import portable
from impact_relay.storage.sql import SqlEngine
from impact_relay.storage.workspace import SqlWorkspaceRepository

pytest_plugins = ["test_sql_command_log"]
ROOT = Path(__file__).resolve().parents[1]


def seed(database):
    raw = (ROOT / "fixtures/portable_provisioning_v1/default.json").read_text()
    policy = portable.decode_scaffold(raw)
    SqlWorkspaceRepository(SqlEngine(database)).create(
        policy=policy, idempotency_key=json.loads(raw)["idempotency_key"]
    )
    return raw, policy.tenant_id


def test_initialized_fixture_exists_and_matches_real_reopen(database):
    raw, _ = seed(database)
    state, receipt = portable.verify_initialized_workspace(database, raw)
    assert (
        ROOT / "fixtures/portable_provisioning_v1/initialized-empty.json"
    ).read_text() == portable.canonical_json(state)
    assert (
        ROOT / "fixtures/portable_provisioning_v1/initialized-receipt.json"
    ).read_text() == portable.canonical_json(receipt)


def test_verified_initialized_receipt_from_real_reopen(database):
    raw, tenant = seed(database)
    state, receipt = portable.verify_initialized_workspace(database, raw)
    assert state["ledger_binding"]["tenant_id"] == tenant
    assert state["ledger_binding"]["entities"]["donors"] == {}
    assert receipt["readiness"] == {
        "policy_initialized": True,
        "artifact_verified": True,
        "storage_initialized": True,
        "workspace_reopened": True,
        "operational": False,
    }
    assert portable.decode_initialized_workspace(portable.canonical_json(state)) == state
    portable.validate_initialized_receipt(portable.canonical_json(receipt), state)
    assert portable.verify_initialized_workspace(database, raw) == (state, receipt)
    with pytest.raises(TypeError):
        portable.verify_initialized_workspace(database, raw, storage_initialized=True)


@pytest.mark.parametrize("table", portable.EMPTY_TABLES)
def test_receipt_rejects_nonempty_real_storage(database, table):
    raw, tenant = seed(database)
    statements = {
        "tenants": (
            "INSERT INTO tenants VALUES "
            "(?, 'Test', 'v1', 'test', 'inactive', NULL, 'now', 'now', '{}')"
        ),
        "ledger_command_log": (
            "INSERT INTO ledger_command_log "
            "(tenant_id,idempotency_key,command_type,payload_json,result_json,created_at) "
            "VALUES (?, 'test', 'not_dispatchable', '{}', '{\"entities\":{}}', 'now')"
        ),
        "ledger_entity": "INSERT INTO ledger_entity VALUES (?, 'donor', 'test', '{}', 'now')",
        "ledger_meta": "INSERT INTO ledger_meta VALUES (?, '{}', '{}', '{}', 'now')",
        "outbox_events": (
            "INSERT INTO outbox_events (tenant_id,event_id,topic,payload_json,created_at) "
            "VALUES (?, 'test', 'test', '{}', 'now')"
        ),
    }
    engine = SqlEngine(database)
    with engine.conn() as conn:
        engine.execute(conn, statements[table], (tenant,))
    with pytest.raises(PolicyError, match="contains rows"):
        portable.verify_initialized_workspace(database, raw)


@pytest.mark.parametrize("corruption", ["{}", "foreign", "version"])
def test_receipt_rejects_persisted_corruption(database, corruption):
    raw, tenant = seed(database)
    engine = SqlEngine(database)
    saved = SqlWorkspaceRepository(engine).get(tenant)
    assert saved is not None
    original = saved.policy_json
    bad = (
        original.replace(tenant, "org_foreign")
        if corruption == "foreign"
        else (
            original.replace("ir-policy-v1", "ir-policy-v99")
            if corruption == "version"
            else corruption
        )
    )
    with engine.conn() as conn:
        engine.execute(
            conn, "UPDATE workspace_scaffolds SET policy_json=? WHERE tenant_id=?", (bad, tenant)
        )
    with pytest.raises(PolicyError):
        portable.verify_initialized_workspace(database, raw)


def test_foreign_storage_is_not_adopted(database):
    raw, _ = seed(database)
    engine = SqlEngine(database)
    with engine.conn() as conn:
        engine.execute(
            conn, "INSERT INTO ledger_meta VALUES (?, '{}', '{}', '{}', 'now')", ("org_foreign",)
        )
    state, _ = portable.verify_initialized_workspace(database, raw)
    assert state["ledger_binding"]["entities"]["donors"] == {}
    from impact_relay.policy import TenantPolicy

    missing = portable.canonical_json(
        portable.build_scaffold(TenantPolicy(tenant_id="org_foreign", version="v1"), "key")
    )
    with pytest.raises(KeyError):
        portable.verify_initialized_workspace(database, missing)


def test_missing_database_not_created(tmp_path):
    path = tmp_path / "absent.sqlite"
    raw = (ROOT / "fixtures/portable_provisioning_v1/default.json").read_text()
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        portable.verify_initialized_workspace(str(path), raw)
    assert not path.exists()


def test_fresh_process_receipt(database, tmp_path):
    raw, _ = seed(database)
    script = """
import sys
from impact_relay.storage.portable import verify_initialized_workspace, canonical_json
state, receipt = verify_initialized_workspace(sys.argv[1], sys.stdin.read())
print(canonical_json(receipt))
"""
    import os

    result = subprocess.run(
        [sys.executable, "-c", script, database],
        input=raw,
        text=True,
        capture_output=True,
        check=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert json.loads(result.stdout) == portable.verify_initialized_workspace(database, raw)[1]


def test_strict_python_javascript_shared_negative_corpus():
    if not shutil.which("node"):
        pytest.skip("Node required for cross-runtime conformance")
    directory = ROOT / "fixtures/portable_provisioning_v1"
    state = json.loads((directory / "initialized-empty.json").read_text())
    receipt = json.loads((directory / "initialized-receipt.json").read_text())
    cases = []
    for file in ["unicode-empty.json", "null-provenance.json"]:
        positive = copy.deepcopy(state)
        positive["scaffold"] = json.loads((directory / file).read_text())
        policy = positive["scaffold"]["policy"]["policy"]
        positive["ledger_binding"]["tenant_id"] = policy["tenant_id"]
        positive["ledger_binding"]["entities"]["organization"] = {
            "id": policy["tenant_id"],
            "name": policy["display_name"],
            "policy_version": policy["version"],
        }
        cases.append({"kind": "state", "raw": portable.canonical_json(positive), "valid": True})
    for kind, valid in [("state", state), ("receipt", receipt)]:
        cases.append({"kind": kind, "raw": portable.canonical_json(valid), "valid": True})
        paths = [("format", "future"), ("unknown", True)]
        if kind == "state":
            paths += [
                ("operational", True),
                ("ledger_binding.tenant_id", "org_foreign"),
                ("ledger_binding.format", "future"),
                ("ledger_binding.entities.organization.id", "org_foreign"),
                ("ledger_binding.entities.organization.name", "wrong"),
                ("ledger_binding.entities.organization.policy_version", "wrong"),
                ("ledger_binding.entities.donors", []),
                ("ledger_binding.entities.expenses", {"foreign": {}}),
                ("scaffold.policy_sha256", "0" * 64),
                ("scaffold.policy.format", "future"),
                ("scaffold.policy.policy.tenant_id", "org_foreign"),
                ("scaffold.policy.policy.confidence.block_below", "0.750"),
                ("scaffold.policy.policy.confidence.block_below", "0.99"),
                ("scaffold.policy.policy.authority.l3_command_types", []),
            ]
        else:
            paths += [
                ("readiness.operational", True),
                ("readiness.storage_initialized", "true"),
                ("tenant_id", "org_foreign"),
                ("state_sha256", "0" * 64),
                ("policy_sha256", "0" * 64),
                ("storage_scope", "host-runtime"),
                ("empty_tables", []),
            ]
        if kind == "state":
            for group in state["ledger_binding"]["entities"]:
                paths.append(("ledger_binding.entities." + group, []))
            for field in ["id", "name", "policy_version"]:
                mutated = copy.deepcopy(state)
                del mutated["ledger_binding"]["entities"]["organization"][field]
                cases.append(
                    {"kind": kind, "raw": portable.canonical_json(mutated), "valid": False}
                )
        for path, value in paths:
            mutated = copy.deepcopy(valid)
            target = mutated
            keys = path.split(".")
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            # Rehash corrupt policies so semantic validation, not hash alone, is tested.
            if path.startswith("scaffold.policy."):
                mutated["scaffold"]["policy_sha256"] = portable.policy_hash(
                    mutated["scaffold"]["policy"]
                )
            cases.append({"kind": kind, "raw": portable.canonical_json(mutated), "valid": False})
        for key in valid:
            mutated = copy.deepcopy(valid)
            del mutated[key]
            cases.append({"kind": kind, "raw": portable.canonical_json(mutated), "valid": False})
        raw = portable.canonical_json(valid)
        for bad in [raw + "\n", '{"format":"duplicate",' + raw[1:]]:
            cases.append({"kind": kind, "raw": bad, "valid": False})
    for case in cases:

        def validate(case=case):
            if case["kind"] == "state":
                portable.decode_initialized_workspace(case["raw"])
            else:
                portable.validate_initialized_receipt(case["raw"], state)

        if case["valid"]:
            validate()
        else:
            with pytest.raises(PolicyError):
                validate()
    result = subprocess.run(
        ["node", str(ROOT / "scripts/check_initialized_conformance.mjs"), "--stdin"],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == [case["valid"] for case in cases]
