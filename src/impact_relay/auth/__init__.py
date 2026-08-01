"""Identity and RBAC ports for host apps (OIDC boundary + role gates).

Impact Relay does not run an IdP. The Hacker-Dojo (or other nonprofit) host
validates OIDC tokens and maps humans to roles. This package provides:

- canonical role vocabulary (template for all tenants)
- permission checks and separation-of-duties rules
- fixture principal builder for local pilot (no live OIDC required)
"""

from impact_relay.auth.oidc import (
    FixtureOidcMapper,
    OidcClaims,
    OidcIdentityProvider,
    principal_from_claims,
)
from impact_relay.auth.principal import Principal, principal_from_fixture
from impact_relay.auth.rbac import (
    AuthorizationError,
    Permission,
    assert_permission,
    assert_separation_of_duties,
    has_permission,
)
from impact_relay.auth.roles import (
    Role,
    default_role_permissions,
    permissions_for_roles,
)

__all__ = [
    "AuthorizationError",
    "FixtureOidcMapper",
    "OidcClaims",
    "OidcIdentityProvider",
    "Permission",
    "Principal",
    "Role",
    "assert_permission",
    "assert_separation_of_duties",
    "default_role_permissions",
    "has_permission",
    "permissions_for_roles",
    "principal_from_claims",
    "principal_from_fixture",
]
