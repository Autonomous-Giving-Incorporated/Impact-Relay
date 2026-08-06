"""Hacker Dojo as canonical pilot + nonprofit policy template."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from impact_relay.policy import TenantPolicy, load_tenant_policy, tenant_slug
from impact_relay.storage.ports import TenantRecord

if TYPE_CHECKING:
    from impact_relay.storage.sql import StorageBundle

# Canonical identifiers — used by fixtures, CI, and Hacker-Dojo host app.
CANONICAL_PILOT_TENANT_ID = "org_hacker_dojo"
CANONICAL_POLICY_SLUG = "hacker-dojo"
CANONICAL_POLICY_VERSION = "v1.0"
CANONICAL_DISPLAY_NAME = "Hacker Dojo"


def clone_tenant_from_hacker_dojo(
    *,
    tenant_id: str,
    display_name: str,
    version: str | None = None,
) -> TenantPolicy:
    """Materialize a new nonprofit policy from the Hacker Dojo pack.

    Copies confidence / evidence / attribution / notification / L3 authority
    rules. Only tenant identity and display name change. Money invariants stay
    in shared domain code — never special-cased per nonprofit.
    """
    if tenant_id == CANONICAL_PILOT_TENANT_ID:
        return load_tenant_policy(CANONICAL_PILOT_TENANT_ID, CANONICAL_POLICY_VERSION)

    base = load_tenant_policy(CANONICAL_PILOT_TENANT_ID, CANONICAL_POLICY_VERSION)
    ver = version or base.version
    return replace(
        base,
        tenant_id=tenant_id,
        display_name=display_name,
        version=ver,
        # source_path would mislead — clear via to_dict consumers using tenant_id
    )


def ensure_canonical_hacker_dojo_tenant(store: StorageBundle) -> TenantRecord:
    """Register Hacker Dojo in the tenant registry (idempotent)."""
    policy = load_tenant_policy(CANONICAL_PILOT_TENANT_ID, CANONICAL_POLICY_VERSION)
    return store.tenants.upsert_from_policy(
        policy,
        template_source=None,
        meta={
            "role": "canonical_pilot",
            "policy_slug": CANONICAL_POLICY_SLUG,
            "integration": "hacker-dojo-app",
        },
    )


def register_cloned_tenant(
    store: StorageBundle,
    *,
    tenant_id: str,
    display_name: str,
) -> tuple[TenantPolicy, TenantRecord]:
    """Clone HD template policy and register the new tenant."""
    if tenant_id == CANONICAL_PILOT_TENANT_ID:
        rec = ensure_canonical_hacker_dojo_tenant(store)
        return load_tenant_policy(CANONICAL_PILOT_TENANT_ID), rec
    policy = clone_tenant_from_hacker_dojo(tenant_id=tenant_id, display_name=display_name)
    rec = store.tenants.upsert_from_policy(
        policy,
        template_source=CANONICAL_PILOT_TENANT_ID,
        meta={
            "role": "cloned_nonprofit",
            "policy_slug": tenant_slug(tenant_id),
            "template": CANONICAL_POLICY_SLUG,
        },
    )
    return policy, rec


def canonical_tenant_ids() -> dict[str, Any]:
    """Stable constants for host apps and tests."""
    return {
        "tenant_id": CANONICAL_PILOT_TENANT_ID,
        "policy_slug": CANONICAL_POLICY_SLUG,
        "policy_version": CANONICAL_POLICY_VERSION,
        "display_name": CANONICAL_DISPLAY_NAME,
    }
