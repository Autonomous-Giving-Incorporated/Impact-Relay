"""Permission checks and separation of duties."""

from __future__ import annotations

from impact_relay.auth.principal import Principal
from impact_relay.auth.roles import Permission, Role, permissions_for_roles

# Re-export Permission for auth package consumers
__all__ = [
    "AuthorizationError",
    "Permission",
    "assert_permission",
    "assert_separation_of_duties",
    "has_permission",
]


class AuthorizationError(PermissionError):
    """Principal lacks role/permission or violates SoD."""


def has_permission(principal: Principal, permission: Permission | str) -> bool:
    perm = permission if isinstance(permission, Permission) else Permission(str(permission))
    return perm in permissions_for_roles(principal.roles)


def assert_permission(
    principal: Principal,
    permission: Permission | str,
    *,
    tenant_id: str | None = None,
) -> None:
    if tenant_id is not None and principal.tenant_id != tenant_id:
        raise AuthorizationError(
            f"principal tenant {principal.tenant_id!r} does not match {tenant_id!r}"
        )
    if principal.email.startswith("agent:") or principal.subject.startswith("agent:"):
        raise AuthorizationError("agents cannot act as human principals")
    if not has_permission(principal, permission):
        perm = permission if isinstance(permission, Permission) else Permission(str(permission))
        raise AuthorizationError(
            f"principal {principal.email!r} lacks permission {perm.value} "
            f"(roles={[r.value for r in principal.roles]})"
        )


def assert_separation_of_duties(
    principal: Principal,
    *,
    action: str,
    proposer_id: str | None = None,
    prior_approver_id: str | None = None,
    enforce_hard: bool = True,
) -> None:
    """Separation of duties (SoD) gates.

    Hard (always when ``enforce_hard``):
    - principal cannot approve their own proposal (``proposer_id`` match)
    - agent identities rejected

    Soft preferences (documented; not hard-fail unless both roles used on same step):
    - finance_reviewer vs finance_approver preferably distinct people
    """
    if principal.email.startswith("agent:") or principal.subject.startswith("agent:"):
        raise AuthorizationError("agents cannot satisfy SoD as approvers")

    if not enforce_hard:
        return

    if proposer_id and proposer_id in (principal.email, principal.subject, principal.approver_id):
        raise AuthorizationError(
            f"separation of duties: {principal.email!r} cannot approve own proposal "
            f"(proposer_id={proposer_id!r}, action={action})"
        )

    # Soft: if same person already approved a prior step in chain, flag for dual-control paths
    if (
        prior_approver_id
        and prior_approver_id in (principal.email, principal.subject)
        and action in ("approve_publish", "approve_send")
        and principal.has_role(Role.FINANCE_APPROVER)
        and principal.has_role(Role.COMMUNICATIONS_APPROVER)
    ):
        # Same principal holding both roles re-approving later step — require explicit
        # dual-control only when policy hardens; for now soft pass with no raise.
        pass
