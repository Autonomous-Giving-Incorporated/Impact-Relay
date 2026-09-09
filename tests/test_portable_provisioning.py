"""Public cross-runtime provisioning contract oracle; no deployed executor implied."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from impact_relay.policy import PolicyError, TenantPolicy
from impact_relay.storage import portable

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/portable_provisioning_v1"


def test_portable_roundtrip():
    policy = TenantPolicy(
        tenant_id="org_synthetic_portable", version="v1", source_path="fixture:public"
    )
    artifact = portable.build_scaffold(policy, "synthetic-request-1")
    assert artifact["format"] == "ir-empty-scaffold-v1"
    assert artifact["policy"]["policy"]["confidence"]["block_below"] == "0.75"
    assert portable.decode_scaffold(portable.canonical_json(artifact)) == policy
    assert artifact["readiness"] == {"scaffold_verified": False, "operational": False}
    schema = json.loads((ROOT / "schemas/ir-empty-scaffold-v1.schema.json").read_text())
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(artifact, schema)


def test_verified_readback_is_not_operational():
    artifact = portable.build_scaffold(
        TenantPolicy(tenant_id="org_test", version="v1"), "request-1"
    )
    raw = portable.canonical_json(artifact)
    receipt = portable.verify_readback(raw, raw)
    assert receipt["readiness"] == {"scaffold_verified": True, "operational": False}
    assert receipt["scaffold_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(PolicyError):
        portable.verify_readback(raw, raw.replace("org_test", "org_other"))
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schemas/ir-scaffold-verification-v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(receipt, schema)
    receipt["readiness"]["operational"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)


def test_fixture_generation_and_schema(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/generate_portable_fixtures.py"),
            "--output",
            str(tmp_path),
        ],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=True,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["provenance"] == "public_synthetic"
    schema = json.loads((ROOT / "schemas/ir-empty-scaffold-v1.schema.json").read_text())
    jsonschema = pytest.importorskip("jsonschema")
    for path in tmp_path.iterdir():
        assert path.read_bytes() == (FIXTURES / path.name).read_bytes()
    for vector in manifest["vectors"]:
        raw = (FIXTURES / vector["file"]).read_text()
        artifact = json.loads(raw)
        jsonschema.validate(artifact, schema)
        policy = portable.decode_scaffold(raw)
        assert policy.source_path == artifact["policy"]["policy"]["source_path"]
        assert hashlib.sha256(raw.encode()).hexdigest() == vector["scaffold_sha256"]
        assert portable.policy_hash(artifact["policy"]) == vector["policy_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.update(format="ir-empty-scaffold-v2"),
        lambda a: a.update(tenant_id="org_foreign"),
        lambda a: a.update(policy_sha256="0" * 64),
        lambda a: a.update(unexpected=True),
        lambda a: a["readiness"].update(operational=True),
        lambda a: a["readiness"].update(scaffold_verified=True),
        lambda a: a["empty_state"]["entities"].append({"donor": "synthetic"}),
        lambda a: a["policy"]["policy"]["confidence"].update(block_below="0.750"),
        lambda a: a["policy"]["policy"]["confidence"].update(block_below="0.99"),
        lambda a: a["policy"]["policy"]["authority"].update(l3_command_types=[]),
        lambda a: a["policy"]["policy"]["notifications"].update(
            require_separate_send_approval=False
        ),
        lambda a: a["policy"]["policy"].update(source_path={"fetch": "forbidden"}),
    ],
)
def test_invalid_scaffolds_fail_closed(change):
    artifact = portable.build_scaffold(TenantPolicy(tenant_id="org_test", version="v1"), "key")
    change(artifact)
    with pytest.raises(PolicyError):
        portable.decode_scaffold(portable.canonical_json(artifact))


@pytest.mark.parametrize("value", [1, 0.75, float("nan"), float("inf"), "\ud800", {"é": True}])
def test_canonicalizer_rejects_ambiguous_values(value):
    with pytest.raises(PolicyError):
        portable.canonical_json(value)


@pytest.mark.parametrize("version,key", [("v1\n", "key"), ("v1", "key\n"), ("v 1", "key")])
def test_portable_tokens_are_literal(version, key):
    with pytest.raises(PolicyError):
        portable.build_scaffold(TenantPolicy(tenant_id="org_test", version=version), key)


def test_noncanonical_and_duplicate_keys_rejected():
    artifact = portable.build_scaffold(TenantPolicy(tenant_id="org_test", version="v1"), "key")
    raw = portable.canonical_json(artifact)
    for bad in [
        raw + "\n",
        '{"format":"discarded",' + raw[1:],
        raw.replace('"block_below":"0.75"', '"block_below":0.75'),
    ]:
        with pytest.raises(PolicyError):
            portable.decode_scaffold(bad)


def test_javascript_hash_conformance():
    if not shutil.which("node"):
        pytest.skip("Node required for cross-runtime conformance")
    result = subprocess.run(
        ["node", str(ROOT / "scripts/check_portable_conformance.mjs")],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(result.stdout)["operational"] is False


def test_sqlite_scaffold_reopen_bridge(tmp_path):
    from impact_relay.storage.sql import SqlEngine
    from impact_relay.storage.workspace import SqlWorkspaceRepository

    raw = (FIXTURES / "unicode-empty.json").read_text()
    artifact = json.loads(raw)
    policy = portable.decode_scaffold(raw)
    database = "sqlite:///" + str(tmp_path / "portable.db")
    engine = SqlEngine(database)
    engine.migrate()
    repo = SqlWorkspaceRepository(engine)
    repo.create(policy=policy, idempotency_key=artifact["idempotency_key"])
    reopened = SqlWorkspaceRepository(SqlEngine(database)).reopen(policy.tenant_id)
    actual = portable.canonical_json(
        portable.build_scaffold(reopened.policy, reopened.scaffold.idempotency_key)
    )
    assert portable.verify_readback(raw, actual)["readiness"]["scaffold_verified"] is True
    assert reopened.scaffold.runtime_ready is False
    assert not reopened.workspace.ledger.donors
    assert not reopened.workspace.ledger.expenses
    assert reopened.policy.evidence.sufficient_kinds == ()
