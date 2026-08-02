"""JWKS-backed OIDC provider (optional extra: ``pip install 'impact-relay[oidc]'``).

The base package stays dependency-free: this module imports PyJWT lazily and is
only used by hosts that want the library to validate tokens itself rather than
terminating auth at a gateway.

    provider = JwksOidcProvider(
        jwks_url="https://issuer.example/.well-known/jwks.json",
        issuer="https://issuer.example/",
        audience="impact-relay",
        tenant_id="org_hacker_dojo",
        role_map={"finance@dojo.org": ["finance_approver"]},
    )
    principal = provider.principal_for_token(bearer_token)

Signature, ``exp``, ``iss``, and ``aud`` are all verified. Unsigned tokens and
symmetric algorithms are rejected outright: a JWKS publishes public keys, so an
HS256 token would let anyone who can read the JWKS mint an approver identity.
"""

from __future__ import annotations

from typing import Any, Protocol

from impact_relay.auth.oidc import OidcClaims, principal_from_claims
from impact_relay.auth.principal import Principal

# Asymmetric only. "none" and HS* are never acceptable against a public JWKS.
DEFAULT_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256")

_FORBIDDEN_ALGORITHMS = frozenset({"none", "HS256", "HS384", "HS512"})


class TokenValidationError(ValueError):
    """Token failed signature, expiry, issuer, or audience validation."""


class SigningKeyResolver(Protocol):
    """Resolves the verification key for a token. Implemented by PyJWKClient."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class JwksOidcProvider:
    """``OidcIdentityProvider`` backed by a JWKS endpoint.

    ``key_resolver`` is injectable so tests (and hosts with their own key
    caching) can supply keys without network access.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | list[str],
        tenant_id: str,
        jwks_url: str | None = None,
        role_map: dict[str, list[str]] | None = None,
        default_roles: list[str] | None = None,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        leeway_seconds: int = 60,
        key_resolver: SigningKeyResolver | None = None,
        roles_claim: str = "roles",
    ) -> None:
        if jwks_url is None and key_resolver is None:
            raise ValueError("provide jwks_url or key_resolver")
        bad = _FORBIDDEN_ALGORITHMS & set(algorithms)
        if bad:
            raise ValueError(f"refusing symmetric/unsigned algorithms: {sorted(bad)}")
        if not issuer:
            raise ValueError("issuer is required")
        if not audience:
            raise ValueError("audience is required")

        self.issuer = issuer
        self.audience = audience
        self.tenant_id = tenant_id
        self.jwks_url = jwks_url
        self.role_map = dict(role_map or {})
        self.default_roles = list(default_roles or [])
        self.algorithms = tuple(algorithms)
        self.leeway_seconds = leeway_seconds
        self.roles_claim = roles_claim
        self._key_resolver = key_resolver

    # ------------------------------------------------------------------

    def _resolver(self) -> SigningKeyResolver:
        if self._key_resolver is None:
            jwt = _import_jwt()
            self._key_resolver = jwt.PyJWKClient(self.jwks_url)
        return self._key_resolver

    def validate_access_token(self, token: str) -> OidcClaims:
        """Verify the token and return its claims. Raises on any failure."""
        jwt = _import_jwt()
        raw = token.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        if not raw:
            raise TokenValidationError("empty bearer token")

        try:
            signing_key = self._resolver().get_signing_key_from_jwt(raw)
            payload: dict[str, Any] = jwt.decode(
                raw,
                key=getattr(signing_key, "key", signing_key),
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={
                    "require": ["exp", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except TokenValidationError:
            raise
        except Exception as exc:
            raise TokenValidationError(f"token rejected: {type(exc).__name__}: {exc}") from exc

        sub = str(payload.get("sub") or "")
        if not sub:
            raise TokenValidationError("token has no sub claim")

        roles_raw = payload.get(self.roles_claim) or ()
        if isinstance(roles_raw, str):
            roles = tuple(r.strip() for r in roles_raw.split(",") if r.strip())
        else:
            roles = tuple(str(r) for r in roles_raw)

        return OidcClaims(
            sub=sub,
            email=payload.get("email"),
            name=payload.get("name"),
            iss=payload.get("iss"),
            aud=payload.get("aud"),
            roles=roles,
            tenant_id=payload.get("tenant_id") or self.tenant_id,
            raw=payload,
        )

    def map_principal(self, claims: OidcClaims, *, tenant_id: str) -> Principal:
        return principal_from_claims(
            claims,
            tenant_id=tenant_id or self.tenant_id,
            role_map=self.role_map,
            default_roles=self.default_roles,
        )

    def principal_for_token(self, token: str) -> Principal:
        claims = self.validate_access_token(token)
        return self.map_principal(claims, tenant_id=self.tenant_id)


def _import_jwt() -> Any:
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - exercised by the extra
        raise RuntimeError("JWKS validation requires: pip install 'impact-relay[oidc]'") from exc
    return jwt
