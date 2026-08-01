"""RBAC roles, SoD, and fixture OIDC mapping (Hacker Dojo canonical)."""

from __future__ import annotations

from pathlib import Path

import pytest

from impact_relay.auth import (
    AuthorizationError,
    Permission,
    Role,
    assert_permission,
    assert_separation_of_duties,
    has_permission,
    principal_from_fixture,
)
from impact_relay.auth.oidc import (
    OidcClaims,
    hacker_dojo_fixture_oidc,
    principal_from_claims,
)
from impact_relay.host import open_hacker_dojo_session
from impact_relay.host.hacker_dojo import finance_approver_fixture
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def test_finance_approver_permissions() -> None:
    p = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="finance.approver@hackersdojo.example",
        roles=[Role.FINANCE_APPROVER],
    )
    assert has_permission(p, Permission.WORKFLOW_APPROVE_EXPENSE)
    assert has_permission(p, Permission.EXPENSE_READ)
    assert not has_permission(p, Permission.WORKFLOW_APPROVE_SEND)
    assert_permission(p, Permission.WORKFLOW_APPROVE_EXPENSE)


def test_comms_cannot_approve_expense() -> None:
    p = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="comms@hackersdojo.example",
        roles=[Role.COMMUNICATIONS_APPROVER],
    )
    with pytest.raises(AuthorizationError, match="lacks permission"):
        assert_permission(p, Permission.WORKFLOW_APPROVE_EXPENSE)


def test_agent_principal_rejected() -> None:
    with pytest.raises(ValueError, match="agent"):
        principal_from_fixture(
            tenant_id=CANONICAL_PILOT_TENANT_ID,
            email="agent:bot",
            roles=[Role.FINANCE_APPROVER],
        )


def test_sod_self_approve_blocked() -> None:
    p = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="alice@hackersdojo.example",
        roles=[Role.FINANCE_APPROVER],
    )
    with pytest.raises(AuthorizationError, match="separation of duties"):
        assert_separation_of_duties(
            p, action="approve_expense", proposer_id="alice@hackersdojo.example"
        )


def test_fixture_oidc_maps_hd_roles() -> None:
    oidc = hacker_dojo_fixture_oidc()
    principal = oidc.principal_for_token("finance.approver@hackersdojo.example")
    assert principal.tenant_id == CANONICAL_PILOT_TENANT_ID
    assert Role.FINANCE_APPROVER in principal.roles
    assert has_permission(principal, Permission.WORKFLOW_APPROVE_EXPENSE)


def test_principal_from_claims_role_map() -> None:
    claims = OidcClaims(
        sub="auth0|abc",
        email="rev@hackersdojo.example",
        iss="https://idp.example",
    )
    p = principal_from_claims(
        claims,
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        role_map={"rev@hackersdojo.example": ["finance_reviewer"]},
    )
    assert p.subject == "auth0|abc"
    assert has_permission(p, Permission.WORKFLOW_LIST)
    with pytest.raises(AuthorizationError):
        assert_permission(p, Permission.WORKFLOW_APPROVE_EXPENSE)


def test_host_approve_with_principal_rbac(tmp_path: Path) -> None:
    base = open_hacker_dojo_session(tmp_path / "hd")
    base.seed(expense_batch=BATCH)
    waiting = base.list_waiting()
    wid = waiting["cases"][0]["workflow_id"]

    # Donor cannot approve
    donor = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="donor@example.com",
        roles=[Role.DONOR],
    )
    denied = base.with_principal(donor).approve(workflow_id=wid)
    assert denied["ok"] is False
    assert denied["error"] == "forbidden"

    # Finance approver can
    session = base.with_principal(finance_approver_fixture())
    ok = session.approve(workflow_id=wid)
    assert ok["ok"] is True
    assert ok["expense_state"] == "APPROVED"


def test_host_require_principal_for_approve(tmp_path: Path) -> None:
    session = open_hacker_dojo_session(
        tmp_path / "hd2", require_principal_for_approve=True
    )
    session.seed(expense_batch=BATCH)
    out = session.approve()
    assert out["ok"] is False
    assert out["error"] == "principal_required"

    authed = session.with_principal(finance_approver_fixture())
    waiting = authed.list_waiting()
    wid = waiting["cases"][0]["workflow_id"]
    ok = authed.approve(workflow_id=wid)
    assert ok["ok"] is True


def test_sod_on_host_approve(tmp_path: Path) -> None:
    session = open_hacker_dojo_session(tmp_path / "hd3")
    session.seed(expense_batch=BATCH)
    wid = session.list_waiting()["cases"][0]["workflow_id"]
    me = finance_approver_fixture("same@hackersdojo.example")
    out = session.with_principal(me).approve(
        workflow_id=wid, proposer_id="same@hackersdojo.example"
    )
    assert out["ok"] is False
    assert out["error"] == "separation_of_duties"
