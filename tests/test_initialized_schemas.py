"""Structural schemas and strict Python/Node wire validators have distinct jobs."""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from impact_relay.policy import PolicyError
from impact_relay.storage import portable

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "fixtures/portable_provisioning_v1"
NAMES = {
    "state": "ir-initialized-empty-workspace-v1",
    "receipt": "ir-initialized-workspace-verification-v1",
}
MAPS = (
    "allocations",
    "attributions",
    "donation_allocations",
    "donations",
    "donors",
    "evidence",
    "expense_allocations",
    "expense_receipts",
    "expenses",
    "external_index",
    "receipt_snapshots",
    "receipts",
)


def validators():
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource

    documents = [json.loads(path.read_text()) for path in SCHEMAS.glob("ir-*.schema.json")]
    registry = Registry().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in documents
    )
    result = {}
    for kind, name in NAMES.items():
        path = SCHEMAS / (name + ".schema.json")
        assert path.exists(), f"missing initialized structural schema: {path.name}"
        doc = json.loads(path.read_text())
        jsonschema.Draft202012Validator.check_schema(doc)
        result[kind] = jsonschema.Draft202012Validator(doc, registry=registry)
    return result


def fixtures():
    return {
        "state": json.loads((FIXTURES / "initialized-empty.json").read_text()),
        "receipt": json.loads((FIXTURES / "initialized-receipt.json").read_text()),
    }


def test_initialized_schema_accepts_deterministic_storage_fixtures():
    for kind, value in fixtures().items():
        validators()[kind].validate(value)


def corpus():
    """Expected schema and semantic acceptance are explicit, never inferred."""
    originals = fixtures()
    cases = []

    def add(kind, value, structural=False, semantic=False, label="mutation", raw=None):
        cases.append(
            {
                "kind": kind,
                "raw": raw or portable.canonical_json(value),
                "schema": structural,
                "valid": semantic,
                "label": label,
            }
        )

    def mutate(kind, path, value, structural=False):
        obj = copy.deepcopy(originals[kind])
        target = obj
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        if path[:2] == ("scaffold", "policy"):
            obj["scaffold"]["policy_sha256"] = portable.policy_hash(obj["scaffold"]["policy"])
        add(kind, obj, structural, label=".".join(path) + "=" + repr(value))

    def closed_objects(kind, obj, path=()):
        for key, value in obj.items():
            removed = copy.deepcopy(originals[kind])
            target = removed
            for part in path:
                target = target[part]
            del target[key]
            add(kind, removed, label="missing " + ".".join((*path, key)))
            if isinstance(value, dict):
                closed_objects(kind, value, (*path, key))
        mutate(kind, (*path, "unknown"), True)

    for kind, obj in originals.items():
        add(kind, obj, True, True, "fixture")
        closed_objects(kind, obj)
        mutate(kind, ("format",), "future")
        raw = portable.canonical_json(obj)
        for bad in [raw + "\n", '{"format":"duplicate",' + raw[1:], json.dumps(obj)]:
            add(kind, obj, True, label="noncanonical wire", raw=bad)

    for name in MAPS:
        for value in [[], None, {"foreign": {}}, {"items": []}]:
            mutate("state", ("ledger_binding", "entities", name), value)
    for field in ["id", "name", "policy_version"]:
        mutate("state", ("ledger_binding", "entities", "organization", field), None)
        mutate("state", ("ledger_binding", "entities", "organization", field), "foreign", True)
    mutate("state", ("ledger_binding", "tenant_id"), "org_foreign", True)
    mutate("state", ("ledger_binding", "format"), "future")
    mutate("state", ("operational",), True)
    for value in [True, "false", None]:
        mutate("state", ("scaffold", "readiness", "operational"), value)
    policy = ("scaffold", "policy", "policy")
    for value in ["0.750", "0.75\n", "1.0", "1e-1"]:
        mutate("state", (*policy, "confidence", "block_below"), value)
    mutate("state", (*policy, "confidence", "block_below"), "0.99", True)
    mutate("state", (*policy, "authority", "l3_command_types"), [])
    mutate("state", (*policy, "evidence", "require_donor_visible"), False)
    mutate("state", (*policy, "notifications", "require_separate_send_approval"), False)
    mutate("state", (*policy, "tenant_id"), "org_foreign", True)
    mutate("state", ("scaffold", "policy_sha256"), "0" * 64, True)
    for field in ["policy_sha256", "scaffold_sha256", "state_sha256"]:
        for value in ["A" * 64, "a" * 63, "a" * 64 + "\n", None]:
            mutate("receipt", (field,), value)
        mutate("receipt", (field,), "0" * 64, True)
    for field in ["tenant_id", "idempotency_key"]:
        mutate("receipt", (field,), "foreign", True)
        for value in ["", "bad\n", "bad/identifier", None]:
            mutate("receipt", (field,), value)
    for value in ["host-runtime", "cf-persisted-workspace-v1", None]:
        mutate("receipt", ("storage_scope",), value)
    tables = originals["receipt"]["empty_tables"]
    for value in [[], list(reversed(tables)), [*tables, tables[0]], tables[:-1], {}]:
        mutate("receipt", ("empty_tables",), value)
    for field, value in originals["receipt"]["readiness"].items():
        for bad in [not value, str(value).lower(), None]:
            mutate("receipt", ("readiness", field), bad)

    for file in ["unicode-empty.json", "null-provenance.json"]:
        state = copy.deepcopy(originals["state"])
        state["scaffold"] = json.loads((FIXTURES / file).read_text())
        p = state["scaffold"]["policy"]["policy"]
        state["ledger_binding"]["tenant_id"] = p["tenant_id"]
        state["ledger_binding"]["entities"]["organization"] = {
            "id": p["tenant_id"],
            "name": p["display_name"],
            "policy_version": p["version"],
        }
        add("state", state, True, True, file)
    return cases


def test_initialized_schema_python_node_adversarial_conformance():
    schema_validators = validators()
    cases = corpus()
    state = fixtures()["state"]
    for case in cases:
        assert (
            schema_validators[case["kind"]].is_valid(json.loads(case["raw"])) == case["schema"]
        ), case

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
    if not shutil.which("node"):
        pytest.skip("Node required for cross-runtime conformance")
    result = subprocess.run(
        ["node", str(ROOT / "scripts/check_initialized_conformance.mjs"), "--stdin"],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == [case["valid"] for case in cases]
