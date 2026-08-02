"""Authenticated principal (human or service) for a single tenant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from impact_relay.auth.roles import Role


@dataclass(frozen=True)
class Principal:
    """Identity bound to one tenant after OIDC (or fixture) mapping.

    ``subject`` is the stable IdP subject (``sub`` claim).
    ``email`` is display / approver_id for ApprovalReceipt.
    """

    subject: str
    tenant_id: str
    email: str
    roles: frozenset[Role]
    display_name: str = ""
    issuer: str | None = None
    raw_claims: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        roles = frozenset(r if isinstance(r, Role) else Role(str(r)) for r in self.roles)
        object.__setattr__(self, "roles", roles)

    @property
    def approver_id(self) -> str:
        """Value stamped on ApprovalReceipt — human email preferred."""
        return self.email or self.subject

    def has_role(self, role: Role | str) -> bool:
        r = role if isinstance(role, Role) else Role(str(role))
        return r in self.roles

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "roles": sorted(r.value for r in self.roles),
            "display_name": self.display_name,
            "issuer": self.issuer,
        }


def principal_from_fixture(
    *,
    tenant_id: str,
    email: str,
    roles: list[str] | list[Role],
    subject: str | None = None,
    display_name: str = "",
    donor_id: str | None = None,
) -> Principal:
    """Build a principal without live OIDC (local pilot / tests).

    Host apps should use OIDC in production and this only for demos.

    ``donor_id`` binds ``claims.donor_id``. Donor-role principals need it: the
    donor API fails closed when a donor-only principal is unbound.
    """
    if email.startswith("agent:"):
        raise ValueError("fixture principal cannot be agent:*")
    role_set = frozenset(r if isinstance(r, Role) else Role(str(r)) for r in roles)
    return Principal(
        subject=subject or f"fixture:{email}",
        tenant_id=tenant_id,
        email=email,
        roles=role_set,
        display_name=display_name or email,
        issuer="fixture://local",
        raw_claims={"donor_id": donor_id} if donor_id is not None else {},
    )
