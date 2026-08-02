"""Supabase JWT mapping for the A.G.I. multi-tenant host contract."""

from __future__ import annotations

from typing import Any

from impact_relay.auth.jwt_oidc import JwksOidcProvider, TokenValidationError
from impact_relay.auth.oidc import OidcClaims
from impact_relay.auth.principal import Principal
from impact_relay.auth.role_map import roles_for_campaign_role


def principal_from_supabase_claims(claims: OidcClaims, *, tenant_id: str) -> Principal:
    """Select one signed active membership and map its campaign role to IR roles."""
    memberships = claims.raw.get("client_memberships") or []
    if not isinstance(memberships, list):
        raise TokenValidationError("client_memberships claim must be a list")

    matches = [
        item
        for item in memberships
        if isinstance(item, dict) and item.get("client_id") == tenant_id
    ]
    if len(matches) != 1:
        raise TokenValidationError(f"token has no unique active membership for {tenant_id}")

    campaign_role = str(matches[0].get("role") or "")
    roles = roles_for_campaign_role(campaign_role)
    if not roles:
        raise TokenValidationError(f"membership role {campaign_role!r} has no Impact Relay roles")

    email = (claims.email or "").strip()
    if not email:
        raise TokenValidationError("Supabase token is missing email")
    return Principal(
        subject=claims.sub,
        tenant_id=tenant_id,
        email=email,
        roles=frozenset(roles),
        display_name=claims.name or email,
        issuer=claims.iss,
        raw_claims=dict(claims.raw),
    )


class SupabaseJwksProvider(JwksOidcProvider):
    """JWKS validator for access tokens enriched by Fund-Intel's auth hook."""

    def __init__(
        self,
        *,
        supabase_url: str,
        tenant_id: str,
        audience: str = "authenticated",
        **kwargs: Any,
    ) -> None:
        base = supabase_url.rstrip("/")
        super().__init__(
            issuer=f"{base}/auth/v1",
            audience=audience,
            tenant_id=tenant_id,
            jwks_url=f"{base}/auth/v1/.well-known/jwks.json",
            **kwargs,
        )

    def map_principal(self, claims: OidcClaims, *, tenant_id: str) -> Principal:
        return principal_from_supabase_claims(claims, tenant_id=tenant_id or self.tenant_id)
