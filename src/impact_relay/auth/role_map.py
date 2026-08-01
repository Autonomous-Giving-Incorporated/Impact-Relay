"""Map host campaign roles (Hacker-Dojo) → Impact Relay RBAC roles."""

from __future__ import annotations

from impact_relay.auth.principal import Principal
from impact_relay.auth.roles import Role
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID

# Hacker-Dojo Supabase profile.role → Impact Relay Role
HACKER_DOJO_CAMPAIGN_ROLE_MAP: dict[str, list[Role]] = {
    "director": [Role.TENANT_ADMIN, Role.FINANCE_APPROVER],
    "campaign_lead": [Role.FINANCE_APPROVER, Role.FINANCE_REVIEWER],
    "development": [Role.FINANCE_APPROVER, Role.FINANCE_REVIEWER],
    "data_steward": [Role.FINANCE_REVIEWER],
    "auditor": [Role.AUDITOR],
    "board_viewer": [Role.AUDITOR],
}


def roles_for_campaign_role(campaign_role: str) -> list[Role]:
    key = (campaign_role or "").strip().lower()
    return list(HACKER_DOJO_CAMPAIGN_ROLE_MAP.get(key, []))


def principal_from_host_headers(
    *,
    email: str,
    campaign_role: str | None = None,
    subject: str | None = None,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    display_name: str = "",
    impact_roles: list[str] | None = None,
) -> Principal:
    """Build Principal from host-authenticated identity (Supabase profile).

    Prefer ``impact_roles`` (explicit IR roles). Else map ``campaign_role``.
    """
    if email.startswith("agent:"):
        raise ValueError("agents cannot be host principals")
    roles: list[Role] = []
    if impact_roles:
        roles = [Role(r) for r in impact_roles]
    elif campaign_role:
        roles = roles_for_campaign_role(campaign_role)
    if not roles:
        raise ValueError(
            f"no Impact Relay roles for email={email!r} campaign_role={campaign_role!r}"
        )
    return Principal(
        subject=subject or f"host:{email}",
        tenant_id=tenant_id,
        email=email,
        roles=frozenset(roles),
        display_name=display_name or email,
        issuer="host://hacker-dojo",
        raw_claims={
            "campaign_role": campaign_role,
            "impact_roles": [r.value for r in roles],
        },
    )
