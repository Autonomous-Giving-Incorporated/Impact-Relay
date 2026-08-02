"""Permission checks and separation of duties."""

from __future__ import annotations

import logging

from impact_relay.auth.principal import Principal
from impact_relay.auth.roles import Permission, permissions_for_roles

logger = logging.getLogger(__name__)

# Re-export Permission for auth package consumers
__all__ = [
    "DUAL_CONTROL_ACTIONS",
    "AuthorizationError",
    "Permission",
    "assert_permission",
    "assert_separation_of_duties",
    "has_permission",
    "violates_dual_control",
]

# Later-step approvals that must not be signed by the earlier approver.
DUAL_CONTROL_ACTIONS = frozenset({"approve_publish", "approve_send"})


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


def violates_dual_control(
    principal: Principal,
    *,
    action: str,
    prior_approver_id: str | None = None,
) -> bool:
    """True when ``principal`` would sign both sides of a dual-control chain.

    Triggers whenever the human who approved an earlier step is also the one
    signing a publish/send gate. Identity is the whole test — deliberately not
    conditioned on which roles they hold. An earlier version required the
    principal to hold both `finance_approver` and `communications_approver`,
    which let `tenant_admin` walk both sides: it carries every *permission* but
    neither of those *roles*, so the check silently passed.
    """
    if not prior_approver_id or action not in DUAL_CONTROL_ACTIONS:
        return False
    return prior_approver_id in (
        principal.email,
        principal.subject,
        principal.approver_id,
    )


def assert_separation_of_duties(
    principal: Principal,
    *,
    action: str,
    proposer_id: str | None = None,
    prior_approver_id: str | None = None,
    enforce_hard: bool = True,
    enforce_dual_control: bool = True,
) -> None:
    """Separation of duties (SoD) gates.

    Hard (always when ``enforce_hard``):
    - principal cannot approve their own proposal (``proposer_id`` match)
    - agent identities rejected
    - dual control: whoever approved an earlier step cannot also sign a
      publish/send gate, whatever roles they hold

    Set ``enforce_dual_control=False`` for tenants whose policy accepts
    single-signer publication; the violation is then logged, not raised.
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

    if violates_dual_control(principal, action=action, prior_approver_id=prior_approver_id):
        if enforce_dual_control:
            raise AuthorizationError(
                f"dual control: {principal.email!r} already approved an earlier step "
                f"(prior_approver_id={prior_approver_id!r}) and cannot also sign "
                f"{action}; a second approver is required"
            )
        logger.warning(
            "dual_control_waived action=%s approver=%s prior_approver=%s",
            action,
            principal.email,
            prior_approver_id,
        )
