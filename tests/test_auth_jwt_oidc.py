"""JWKS OIDC provider — signature, expiry, issuer, audience, and role mapping.

Fully offline: an RSA keypair is generated in-process and the resolver is
injected, so no JWKS endpoint is contacted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

jwt = pytest.importorskip("jwt", reason="install impact-relay[oidc] for JWKS tests")
pytest.importorskip("cryptography", reason="RS256 signing needs cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from impact_relay.auth.jwt_oidc import (  # noqa: E402
    JwksOidcProvider,
    TokenValidationError,
)
from impact_relay.auth.roles import Role  # noqa: E402
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID  # noqa: E402

ISSUER = "https://issuer.example/"
AUDIENCE = "impact-relay"
APPROVER = "finance.approver@hackersdojo.example"


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


class _StaticResolver:
    """Stands in for PyJWKClient without touching the network."""

    def __init__(self, public_pem: str) -> None:
        self.key = public_pem

    def get_signing_key_from_jwt(self, token: str) -> _StaticResolver:
        return self


def _provider(public_pem: str, **overrides) -> JwksOidcProvider:
    kwargs = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "tenant_id": CANONICAL_PILOT_TENANT_ID,
        "key_resolver": _StaticResolver(public_pem),
        "role_map": {APPROVER: ["finance_approver"]},
    }
    kwargs.update(overrides)
    return JwksOidcProvider(**kwargs)


def _token(private_pem: str, **overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "auth0|abc123",
        "email": APPROVER,
        "name": "Finance Approver",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def test_valid_token_maps_to_principal_with_roles(keypair) -> None:
    private_pem, public_pem = keypair
    principal = _provider(public_pem).principal_for_token(_token(private_pem))
    assert principal.email == APPROVER
    assert principal.subject == "auth0|abc123"
    assert principal.tenant_id == CANONICAL_PILOT_TENANT_ID
    assert Role.FINANCE_APPROVER in principal.roles


def test_bearer_prefix_is_accepted(keypair) -> None:
    private_pem, public_pem = keypair
    token = _token(private_pem)
    assert _provider(public_pem).principal_for_token(f"Bearer {token}").email == APPROVER


def test_roles_claim_on_the_token_is_honoured(keypair) -> None:
    private_pem, public_pem = keypair
    token = _token(private_pem, roles=["auditor"])
    principal = _provider(public_pem, role_map={}).principal_for_token(token)
    assert Role.AUDITOR in principal.roles


def test_expired_token_is_rejected(keypair) -> None:
    private_pem, public_pem = keypair
    now = datetime.now(UTC)
    token = _token(private_pem, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1))
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(token)


def test_wrong_issuer_is_rejected(keypair) -> None:
    private_pem, public_pem = keypair
    token = _token(private_pem, iss="https://evil.example/")
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(token)


def test_wrong_audience_is_rejected(keypair) -> None:
    private_pem, public_pem = keypair
    token = _token(private_pem, aud="some-other-service")
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(token)


def test_token_signed_by_a_different_key_is_rejected(keypair) -> None:
    _, public_pem = keypair
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_pem = attacker.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(_token(attacker_pem))


def test_unsigned_token_is_rejected(keypair) -> None:
    _, public_pem = keypair
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {
            "sub": "auth0|abc123",
            "email": APPROVER,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": now + timedelta(minutes=5),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(unsigned)


def test_symmetric_algorithms_are_refused_at_construction(keypair) -> None:
    _, public_pem = keypair
    with pytest.raises(ValueError, match="symmetric"):
        _provider(public_pem, algorithms=("HS256",))


def test_missing_required_claims_are_rejected(keypair) -> None:
    private_pem, public_pem = keypair
    now = datetime.now(UTC)
    # No `sub`: PyJWT's require list must reject it before we map a principal.
    token = jwt.encode(
        {"email": APPROVER, "iss": ISSUER, "aud": AUDIENCE, "exp": now + timedelta(minutes=5)},
        private_pem,
        algorithm="RS256",
    )
    with pytest.raises(TokenValidationError):
        _provider(public_pem).validate_access_token(token)


def test_agent_identity_cannot_be_minted_through_oidc(keypair) -> None:
    """An `agent:*` email must never become a human principal, even with a valid token."""
    private_pem, public_pem = keypair
    token = _token(private_pem, email="agent:finance_review", sub="agent:finance_review")
    with pytest.raises(ValueError):
        _provider(
            public_pem, role_map={"agent:finance_review": ["finance_approver"]}
        ).principal_for_token(token)


def test_constructor_requires_a_key_source() -> None:
    with pytest.raises(ValueError, match="jwks_url or key_resolver"):
        JwksOidcProvider(issuer=ISSUER, audience=AUDIENCE, tenant_id=CANONICAL_PILOT_TENANT_ID)
