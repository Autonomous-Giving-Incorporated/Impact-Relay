from __future__ import annotations

from typing import ClassVar

import pytest

from impact_relay.auth.jwt_oidc import TokenValidationError
from impact_relay.auth.oidc import OidcClaims
from impact_relay.auth.roles import Role
from impact_relay.auth.supabase import principal_from_supabase_claims
from impact_relay.console_server import resolve_principal_from_request


def claims(memberships) -> OidcClaims:
    return OidcClaims(
        sub="user-1",
        email="lead@example.org",
        name="Campaign Lead",
        iss="https://project.supabase.co/auth/v1",
        aud="authenticated",
        raw={"client_memberships": memberships},
    )


def test_maps_only_configured_tenant_membership() -> None:
    principal = principal_from_supabase_claims(
        claims(
            [
                {"client_id": "org_other", "role": "auditor"},
                {"client_id": "org_hacker_dojo", "role": "campaign_lead"},
            ]
        ),
        tenant_id="org_hacker_dojo",
    )
    assert principal.tenant_id == "org_hacker_dojo"
    assert Role.FINANCE_APPROVER in principal.roles
    assert Role.AUDITOR not in principal.roles


@pytest.mark.parametrize("memberships", [[], [{"client_id": "org_other", "role": "director"}]])
def test_rejects_token_without_tenant_membership(memberships) -> None:
    with pytest.raises(TokenValidationError, match="no unique active membership"):
        principal_from_supabase_claims(claims(memberships), tenant_id="org_hacker_dojo")


def test_rejects_unknown_campaign_role() -> None:
    with pytest.raises(TokenValidationError, match="has no Impact Relay roles"):
        principal_from_supabase_claims(
            claims([{"client_id": "org_hacker_dojo", "role": "unknown"}]),
            tenant_id="org_hacker_dojo",
        )


def test_console_uses_bearer_provider_and_ignores_forged_headers() -> None:
    expected = principal_from_supabase_claims(
        claims([{"client_id": "org_hacker_dojo", "role": "auditor"}]),
        tenant_id="org_hacker_dojo",
    )

    class Provider:
        def principal_for_token(self, token: str):
            assert token == "signed-token"
            return expected

    class Handler:
        headers: ClassVar[dict[str, str]] = {
            "Authorization": "Bearer signed-token",
            "X-Impact-Email": "attacker@example.org",
            "X-HD-Campaign-Role": "director",
        }

    principal = resolve_principal_from_request(
        Handler(),
        "org_hacker_dojo",
        trusted_proxy=False,
        identity_provider=Provider(),
    )
    assert principal == expected
    assert principal.email == "lead@example.org"
    assert principal.roles == frozenset({Role.AUDITOR})
