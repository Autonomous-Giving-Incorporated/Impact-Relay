"""Scaffolds are durable storage, never activation or fixture copies."""

from dataclasses import replace

import pytest

from impact_relay.policy import AuthorityPolicy, TenantPolicy

pytest_plugins = ["test_sql_command_log"]


@pytest.mark.parametrize(
    "table", ["ledger_command_log", "ledger_entity", "ledger_meta", "tenants", "outbox_events"]
)
def test_existing_legacy_tenant_is_not_adopted(database, table):
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository, WorkspaceConflict

    engine = SqlEngine(database)
    statements = {
        "outbox_events": (
            "INSERT INTO outbox_events (tenant_id,event_id,topic,payload_json,created_at) "
            "VALUES (?, 'old', 'test', '{}', '2026-01-01')"
        ),
        "ledger_command_log": (
            "INSERT INTO ledger_command_log "
            "(tenant_id,idempotency_key,command_type,payload_json,result_json,created_at) "
            "VALUES (?, 'old', 'test', '{}', '{}', '2026-01-01')"
        ),
        "ledger_entity": "INSERT INTO ledger_entity VALUES (?, 'donor', 'old', '{}', '2026-01-01')",
        "ledger_meta": "INSERT INTO ledger_meta VALUES (?, '{}', '{}', '{}', '2026-01-01')",
        "tenants": (
            "INSERT INTO tenants VALUES (?, 'Old', 'v1', 'old', 'active', NULL, "
            "'2026-01-01', '2026-01-01', '{}')"
        ),
    }
    with engine.conn() as conn:
        engine.execute(conn, statements[table], ("org_existing",))
    repo = SqlWorkspaceRepository(engine)
    with pytest.raises(WorkspaceConflict):
        repo.create(
            policy=TenantPolicy(tenant_id="org_existing", version="v1"), idempotency_key="new"
        )
    assert repo.get("org_existing") is None


@pytest.mark.parametrize("identical", [True, False])
def test_concurrent_create(database, identical):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository, WorkspaceConflict

    barrier = Barrier(2)

    def create(index):
        repo = SqlWorkspaceRepository(SqlEngine(database))
        policy = TenantPolicy(
            tenant_id="org_race", version="v1", display_name="Same" if identical else str(index)
        )
        barrier.wait(timeout=10)
        try:
            repo.create(policy=policy, idempotency_key="same")
            return "ok"
        except WorkspaceConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results) == (["ok", "ok"] if identical else ["conflict", "ok"])


@pytest.mark.parametrize("tenant", ["", " org_bad", "org_bad ", "../bad", "a/b"])
def test_literal_tenant_ids_rejected(database, tenant):
    from impact_relay.policy import PolicyError
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository

    repo = SqlWorkspaceRepository(SqlEngine(database))
    with pytest.raises(PolicyError):
        repo.create(policy=TenantPolicy(tenant_id=tenant, version="v1"), idempotency_key="key")
    with pytest.raises(PolicyError):
        repo.get(tenant)


def test_corrupt_policy_fails_closed(database):
    from impact_relay.policy import PolicyError
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository, canonical_policy_json

    engine = SqlEngine(database)
    repo = SqlWorkspaceRepository(engine)
    repo.create(policy=TenantPolicy(tenant_id="org_a", version="v1"), idempotency_key="key")
    for document in ["{}", canonical_policy_json(TenantPolicy(tenant_id="org_b", version="v1"))]:
        with engine.conn() as conn:
            engine.execute(
                conn,
                "UPDATE workspace_scaffolds SET policy_json = ? WHERE tenant_id = ?",
                (document, "org_a"),
            )
        with pytest.raises(PolicyError):
            repo.reopen("org_a")


def test_reopen_rejects_foreign_entity_in_own_log(database):
    from impact_relay.domain.ledger_log import LedgerLogError
    from impact_relay.storage.command_log import SqlLedgerCommandLog
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository

    engine = SqlEngine(database)
    repo = SqlWorkspaceRepository(engine)
    repo.create(policy=TenantPolicy(tenant_id="org_a", version="v1"), idempotency_key="key")
    SqlLedgerCommandLog(engine).append(
        tenant_id="org_a",
        idempotency_key="bad",
        command_type="test",
        payload={},
        result_json={
            "entities": {
                "donors": {
                    "foreign": {
                        "id": "foreign",
                        "organization_id": "org_b",
                        "display_name": "Foreign",
                    }
                }
            }
        },
    )
    with pytest.raises(LedgerLogError, match="tenant"):
        repo.reopen("org_a")


@pytest.mark.parametrize("change", ["format", "unknown", "boolean", "nan"])
def test_malformed_canonical_policy_is_rejected(change):
    import json

    from impact_relay.policy import PolicyError
    from impact_relay.storage.workspace import canonical_policy_json, policy_from_canonical_json

    data = json.loads(canonical_policy_json(TenantPolicy(tenant_id="org_a", version="v1")))
    if change == "format":
        data["format"] = "future"
    elif change == "unknown":
        data["policy"]["unknown"] = True
    elif change == "boolean":
        data["policy"]["notifications"]["fixture_consent_allowed"] = "false"
    else:
        data["policy"]["confidence"]["block_below"] = float("nan")
    with pytest.raises(PolicyError):
        policy_from_canonical_json(json.dumps(data, sort_keys=True, separators=(",", ":")))


def test_template_provenance_survives_without_claiming_clone_file():
    from impact_relay.storage.template import clone_tenant_from_hacker_dojo
    from impact_relay.storage.workspace import canonical_policy_json, policy_from_canonical_json

    policy = clone_tenant_from_hacker_dojo(tenant_id="org_new", display_name="New")
    restored = policy_from_canonical_json(canonical_policy_json(policy))
    assert restored == policy
    assert restored.source_path and "hacker-dojo" in restored.source_path


def test_canonical_policy_lossless():
    from impact_relay.storage.workspace import canonical_policy_json, policy_from_canonical_json

    policy = TenantPolicy(
        tenant_id="org_empty",
        version="v2",
        display_name="Empty",
        source_path="policies/template.yaml",
        authority=AuthorityPolicy(l3_command_types=()),
    )
    encoded = canonical_policy_json(policy)
    assert policy_from_canonical_json(encoded) == policy
    assert canonical_policy_json(policy_from_canonical_json(encoded)) == encoded
    assert (
        policy_from_canonical_json(
            canonical_policy_json(replace(policy, source_path=None))
        ).source_path
        is None
    )


def test_create_empty_scaffold_and_conflict(database):
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository, WorkspaceConflict

    repo = SqlWorkspaceRepository(SqlEngine(database))
    policy = TenantPolicy(tenant_id="org_empty", version="v2", display_name="Empty")
    saved = repo.create(policy=policy, idempotency_key="request-1")
    assert saved.runtime_ready is False
    assert repo.get("org_empty") == saved
    assert repo.create(policy=policy, idempotency_key="request-1") == saved
    for changed, key in [(replace(policy, display_name="Changed"), "request-1"), (policy, "new")]:
        with pytest.raises(WorkspaceConflict):
            repo.create(policy=changed, idempotency_key=key)
    assert repo.get("org_empty") == saved
    assert repo.get("org_missing") is None
    with SqlEngine(database).conn() as conn:
        for table in ["tenants", "ledger_command_log", "ledger_entity", "ledger_meta"]:
            assert (
                SqlEngine(database).fetchone(conn, f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0
            )


def test_fresh_process_reopen_result_fold(database, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from impact_relay.storage.command_log import SqlLedgerCommandLog
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository

    repo = SqlWorkspaceRepository(SqlEngine(database))
    policy = TenantPolicy(
        tenant_id="org_empty",
        version="v2",
        display_name="Empty",
        source_path="/nonexistent/template.yaml",
    )
    repo.create(policy=policy, idempotency_key="request-1")
    opened = repo.reopen("org_empty")
    assert opened.policy == policy
    assert opened.workspace.organization.id == "org_empty"
    assert not opened.workspace.ledger.donors
    assert not opened.workspace.ledger.expenses
    with pytest.raises(KeyError):
        repo.reopen("org_missing")
    log = SqlLedgerCommandLog(SqlEngine(database))
    for tenant in ["org_empty", "org_foreign"]:
        log.append(
            tenant_id=tenant,
            idempotency_key="one",
            command_type="not_dispatchable",
            payload={},
            result_json={
                "entities": {
                    "donors": {
                        tenant: {"id": tenant, "organization_id": tenant, "display_name": "Test"}
                    }
                }
            },
        )
    script = """
import sys
from impact_relay.storage.sql import SqlEngine
from impact_relay.storage.workspace import SqlWorkspaceRepository
opened = SqlWorkspaceRepository(SqlEngine(sys.argv[1], read_only=True)).reopen("org_empty")
assert opened.policy.source_path == "/nonexistent/template.yaml"
assert opened.workspace.organization.policy_version == "v2"
assert set(opened.workspace.ledger.donors) == {"org_empty"}
assert not opened.workspace.ledger.expenses
assert opened.scaffold.runtime_ready is False
print("fresh-process-replay-ok")
"""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DATABASE_URL", "IMPACT_RELAY_DATABASE_URL"}
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", script, database],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "fresh-process-replay-ok"


def test_bundle_exposes_scaffolds(tmp_path):
    from impact_relay.storage.sql import StorageBundle

    assert StorageBundle(tmp_path).workspaces.get("unknown") is None
