"""Characterize template provenance; this is not durable tenant provisioning."""

import json

from impact_relay.policy import load_tenant_policy, parse_tenant_policy
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    clone_tenant_from_hacker_dojo,
)


def test_clone_retains_template_source_path_but_parser_requires_explicit_provenance() -> None:
    base = load_tenant_policy(CANONICAL_PILOT_TENANT_ID)
    clone = clone_tenant_from_hacker_dojo(
        tenant_id="org_provenance_test", display_name="Synthetic provenance test"
    )
    assert base.source_path is not None
    assert clone.source_path == base.source_path
    document = json.loads(json.dumps(clone.to_dict()))
    assert document["source_path"] == base.source_path
    assert document["tenant_id"] == "org_provenance_test"
    # The parser accepts provenance only as an explicit, caller-owned argument;
    # a source_path in JSON does not establish a durable document location.
    restored = parse_tenant_policy(document)
    assert restored.source_path is None
    assert restored.to_dict() == {**document, "source_path": None}
