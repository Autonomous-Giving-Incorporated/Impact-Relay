"""Canonical RBAC roles — shared platform vocabulary.

Hacker Dojo uses these roles first; other nonprofits reuse the same enum.
Host apps map OIDC groups/claims → ``Role`` values.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Roles from TODO / ROADMAP (nonprofit finance + program ops)."""

    DONOR = "donor"
    FINANCE_REVIEWER = "finance_reviewer"
    FINANCE_APPROVER = "finance_approver"
    PROGRAM_VERIFIER = "program_verifier"
    COMMUNICATIONS_APPROVER = "communications_approver"
    AUDITOR = "auditor"
    TENANT_ADMIN = "tenant_admin"


# Default permission strings (stable for host apps + tests)
class Permission(str, Enum):
    WORKFLOW_LIST = "workflow.list"
    WORKFLOW_SEED = "workflow.seed"  # ops / fixture only
    WORKFLOW_APPROVE_EXPENSE = "workflow.approve_expense"
    WORKFLOW_APPROVE_PUBLISH = "workflow.approve_publish"
    WORKFLOW_APPROVE_SEND = "workflow.approve_send"
    WORKFLOW_APPROVE_CORRECTION = "workflow.approve_correction"
    EXPENSE_READ = "expense.read"
    RECEIPT_READ = "receipt.read"
    AUDIT_READ = "audit.read"
    TENANT_ADMIN = "tenant.admin"
    OBJECT_WRITE = "object.write"


def default_role_permissions() -> dict[Role, frozenset[Permission]]:
    """Platform default matrix (Hacker Dojo pilot template)."""
    return {
        Role.DONOR: frozenset(
            {
                # Scoped to the principal's own donor_id by DonorExperienceAPI,
                # which fails closed when claims.donor_id is unbound.
                Permission.RECEIPT_READ,
            }
        ),
        Role.FINANCE_REVIEWER: frozenset(
            {
                Permission.WORKFLOW_LIST,
                Permission.EXPENSE_READ,
                Permission.RECEIPT_READ,
                Permission.AUDIT_READ,
            }
        ),
        Role.FINANCE_APPROVER: frozenset(
            {
                Permission.WORKFLOW_LIST,
                Permission.WORKFLOW_APPROVE_EXPENSE,
                Permission.WORKFLOW_APPROVE_CORRECTION,
                Permission.EXPENSE_READ,
                Permission.RECEIPT_READ,
                Permission.AUDIT_READ,
            }
        ),
        Role.PROGRAM_VERIFIER: frozenset(
            {
                Permission.WORKFLOW_LIST,
                Permission.EXPENSE_READ,
                Permission.AUDIT_READ,
            }
        ),
        Role.COMMUNICATIONS_APPROVER: frozenset(
            {
                Permission.WORKFLOW_LIST,
                Permission.WORKFLOW_APPROVE_PUBLISH,
                Permission.WORKFLOW_APPROVE_SEND,
                Permission.RECEIPT_READ,
            }
        ),
        Role.AUDITOR: frozenset(
            {
                Permission.WORKFLOW_LIST,
                Permission.EXPENSE_READ,
                Permission.RECEIPT_READ,
                Permission.AUDIT_READ,
            }
        ),
        Role.TENANT_ADMIN: frozenset(set(Permission)),
    }


def permissions_for_roles(roles: list[Role] | set[Role] | frozenset[Role]) -> frozenset[Permission]:
    matrix = default_role_permissions()
    out: set[Permission] = set()
    for role in roles:
        r = role if isinstance(role, Role) else Role(str(role))
        out |= set(matrix.get(r, frozenset()))
    return frozenset(out)
