"""OIDC identity boundary — host validates tokens; library maps claims → Principal.

Impact Relay never talks to an IdP. The host app (Hacker-Dojo or other) validates
Bearer tokens and either:

1. Calls ``principal_from_claims`` with a role map, or
2. Implements ``OidcIdentityProvider`` for its IdP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from impact_relay.auth.principal import Principal
from impact_relay.auth.roles import Role


@dataclass(frozen=True)
class OidcClaims:
    """Minimal OIDC claims we care about (standard + custom roles claim)."""

    sub: str
    email: str | None = None
    name: str | None = None
    iss: str | None = None
    aud: str | list[str] | None = None
    # Custom: list of role strings or tenant-scoped roles
    roles: tuple[str, ...] = ()
    # Optional tenant binding from host mapping
    tenant_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub": self.sub,
            "email": self.email,
            "name": self.name,
            "iss": self.iss,
            "aud": self.aud,
            "roles": list(self.roles),
            "tenant_id": self.tenant_id,
        }


@runtime_checkable
class OidcIdentityProvider(Protocol):
    """Host implements this against Auth0 / Clerk / Keycloak / etc."""

    def validate_access_token(self, token: str) -> OidcClaims:
        """Validate signature/exp/aud; return claims. Raise on failure."""
        ...

    def map_principal(self, claims: OidcClaims, *, tenant_id: str) -> Principal:
        """Map claims + tenant context to a Principal with roles."""
        ...


def principal_from_claims(
    claims: OidcClaims,
    *,
    tenant_id: str,
    role_map: dict[str, list[str]] | None = None,
    default_roles: list[str] | None = None,
) -> Principal:
    """Map OIDC claims to Principal.

    ``role_map``: email or sub → role name list (host directory).
    If claims already carry ``roles``, those are used first.
    """
    email = (claims.email or claims.sub or "").strip()
    if not email or email.startswith("agent:"):
        raise ValueError("OIDC claims missing usable human email/sub")

    tid = claims.tenant_id or tenant_id
    role_names: list[str] = list(claims.roles)
    if not role_names and role_map:
        role_names = list(role_map.get(email) or role_map.get(claims.sub) or [])
    if not role_names and default_roles:
        role_names = list(default_roles)
    if not role_names:
        raise ValueError(
            f"no roles for subject {claims.sub!r} email {email!r} — "
            "configure host role_map or claims.roles"
        )

    roles = frozenset(Role(r) for r in role_names)
    return Principal(
        subject=claims.sub,
        tenant_id=tid,
        email=email,
        roles=roles,
        display_name=claims.name or email,
        issuer=claims.iss,
        raw_claims=dict(claims.raw or claims.to_dict()),
    )


class FixtureOidcMapper:
    """Local pilot stand-in for OIDC (no JWT validation).

    The Hacker-Dojo app should replace this with a real ``OidcIdentityProvider``
    in production. Other nonprofits reuse the same pattern.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        role_map: dict[str, list[str]],
        issuer: str = "fixture://oidc",
    ) -> None:
        self.tenant_id = tenant_id
        self.role_map = dict(role_map)
        self.issuer = issuer

    def validate_access_token(self, token: str) -> OidcClaims:
        # token format for fixtures: "email:user@example.org" or bare email
        raw = token.strip()
        if raw.startswith("Bearer "):
            raw = raw[7:].strip()
        if raw.startswith("email:"):
            email = raw[6:]
        else:
            email = raw
        if not email or "@" not in email:
            raise ValueError("fixture token must be email:user@domain or user@domain")
        roles = tuple(self.role_map.get(email) or [])
        return OidcClaims(
            sub=f"fixture|{email}",
            email=email,
            name=email,
            iss=self.issuer,
            roles=roles,
            tenant_id=self.tenant_id,
            raw={"token": token},
        )

    def map_principal(self, claims: OidcClaims, *, tenant_id: str) -> Principal:
        return principal_from_claims(
            claims,
            tenant_id=tenant_id or self.tenant_id,
            role_map=self.role_map,
        )

    def principal_for_token(self, token: str) -> Principal:
        claims = self.validate_access_token(token)
        return self.map_principal(claims, tenant_id=self.tenant_id)


# Default Hacker Dojo pilot directory (emails used in fixtures/tests)
HACKER_DOJO_FIXTURE_ROLE_MAP: dict[str, list[str]] = {
    "finance.approver@hackersdojo.example": ["finance_approver"],
    "finance.reviewer@hackersdojo.example": ["finance_reviewer"],
    "finance@hackersdojo.org": ["finance_approver"],
    "comms.approver@hackersdojo.example": ["communications_approver"],
    "auditor@hackersdojo.example": ["auditor"],
    "admin@hackersdojo.example": ["tenant_admin"],
}


def hacker_dojo_fixture_oidc() -> FixtureOidcMapper:
    """Canonical pilot OIDC stand-in for org_hacker_dojo."""
    from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID

    return FixtureOidcMapper(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        role_map=HACKER_DOJO_FIXTURE_ROLE_MAP,
    )
