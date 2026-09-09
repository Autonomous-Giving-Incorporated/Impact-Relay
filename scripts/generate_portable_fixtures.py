"""Generate only public synthetic conformance vectors (never public data/ exports)."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from impact_relay.policy import EvidencePolicy, NotificationPolicy, TenantPolicy
from impact_relay.storage.portable import (
    build_scaffold,
    canonical_json,
    verify_initialized_workspace,
)
from impact_relay.storage.sql import SqlEngine
from impact_relay.storage.workspace import SqlWorkspaceRepository


def generate(output: Path) -> None:
    base = TenantPolicy(
        tenant_id="org_synthetic_portable",
        version="v1",
        display_name="Synthetic portable scaffold",
        source_path="fixture:public/template-v1",
    )
    policies = [
        ("default", base),
        (
            "unicode-empty",
            replace(
                base,
                tenant_id="org_synthetic_unicode",
                display_name='Synthetic café 🌱\n"quoted"\\',
                source_path="fixture:public/不存在.yaml",
                evidence=EvidencePolicy(sufficient_kinds=()),
                notifications=NotificationPolicy(
                    default_email_topics=(), fixture_consent_allowed=False
                ),
            ),
        ),
        ("null-provenance", replace(base, source_path=None)),
    ]
    output.mkdir(parents=True, exist_ok=True)
    vectors = []
    for name, policy in policies:
        artifact = build_scaffold(policy, "synthetic-request-" + name)
        text = canonical_json(artifact)
        (output / (name + ".json")).write_text(text, encoding="utf-8")
        vectors.append(
            {
                "file": name + ".json",
                "scaffold_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "policy_sha256": artifact["policy_sha256"],
            }
        )
    with TemporaryDirectory(prefix="ir-empty-fixture-") as directory:
        database = str(Path(directory) / "storage.sqlite")
        engine = SqlEngine(database)
        engine.migrate()
        SqlWorkspaceRepository(engine).create(
            policy=base, idempotency_key="synthetic-request-default"
        )
        state, receipt = verify_initialized_workspace(
            database, (output / "default.json").read_text()
        )
    for name, artifact in [("initialized-empty", state), ("initialized-receipt", receipt)]:
        (output / (name + ".json")).write_text(canonical_json(artifact), encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ir-portable-conformance-v1",
                "provenance": "public_synthetic",
                "vectors": vectors,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)
