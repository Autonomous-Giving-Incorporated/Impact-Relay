"""Tenant admin HTTP regressions; all storage is disposable and local."""

from urllib.parse import quote

import pytest

from impact_relay.console_server import make_handler
from test_console_api import _request

ROUTES = [
    ("GET", "/api/admin/tenants"),
    ("GET", "/api/admin/tenants/verify?tenant_id=org_hacker_dojo"),
    ("POST", "/api/admin/tenants/clone"),
]


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("pilot", [False, True])
@pytest.mark.parametrize("role,expected", [(None, 401), ("donor", 403), ("finance_approver", 403)])
def test_admin_requires_tenant_permission(tmp_path, method, path, pilot, role, expected):
    handler = make_handler(tmp_path / "srv", trusted_proxy=True, allow_unauthenticated_pilot=pilot)
    headers = {"X-Impact-Email": "admin@example.test", "X-Impact-Roles": role} if role else {}
    response = _request(handler, method, path, headers=headers, raw_body=b"not json")
    assert response.code == expected
    assert not (tmp_path / "srv").exists()


@pytest.fixture(autouse=True)
def local_storage_only(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("IMPACT_RELAY_DATABASE_URL", raising=False)
    monkeypatch.setenv("IMPACT_RELAY_OBJECT_STORE", "local")


ADMIN = {"X-Impact-Email": "admin@example.test", "X-Impact-Roles": "tenant_admin"}


@pytest.mark.parametrize(
    "target,expected",
    [
        ("../outside", 400),
        ("/__invalid_tenant_admin_path__", 400),
        ("org_other", 403),
        (" org_hacker_dojo", 400),
        ("org_hacker_dojo/..", 400),
    ],
)
def test_verify_rejects_invalid_or_foreign_tenant(tmp_path, target, expected):
    handler = make_handler(tmp_path / "srv", trusted_proxy=True)
    response = _request(
        handler, "GET", "/api/admin/tenants/verify?tenant_id=" + quote(target), headers=ADMIN
    )
    assert response.code == expected
    assert list(tmp_path.iterdir()) == []


def test_registry_reads_configured_root_without_migrating_or_scanning(tmp_path, monkeypatch):
    from impact_relay.storage import open_storage
    from impact_relay.storage.template import register_cloned_tenant

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("IMPACT_RELAY_DATABASE_URL", raising=False)
    monkeypatch.setenv("IMPACT_RELAY_OBJECT_STORE", "local")
    root = tmp_path / "storage"
    store = open_storage(root)
    register_cloned_tenant(store, tenant_id="org_hacker_dojo", display_name="Hacker Dojo")
    register_cloned_tenant(store, tenant_id="org_other", display_name="Private nonprofit")
    (tmp_path / "org_link").symlink_to(root, target_is_directory=True)
    before = (root / "storage.db").read_bytes()
    handler = make_handler(root, trusted_proxy=True)
    response = _request(handler, "GET", "/api/admin/tenants", headers=ADMIN)
    assert response.code == 200
    assert [t["tenant_id"] for t in response.json["tenants"]] == ["org_hacker_dojo"]
    result = _request(handler, "GET", ROUTES[1][1], headers=ADMIN)
    assert result.code == 200
    assert result.json["registered"] is True
    assert result.json["display_name"] == "Hacker Dojo"
    assert result.json["storage_isolated"] is None
    assert result.json["cross_tenant_access"] == "not_tested"
    assert result.json["ready"] is False
    assert (root / "storage.db").read_bytes() == before
    assert not (tmp_path / "storage.db").exists()


def test_missing_registry_reads_do_not_create_storage(tmp_path):
    root = tmp_path / "missing"
    handler = make_handler(root, trusted_proxy=True)
    result = _request(handler, "GET", "/api/admin/tenants", headers=ADMIN)
    assert result.code == 200
    assert result.json["tenants"] == []
    assert not root.exists()


def test_clone_fails_closed_until_platform_provisioning_exists(tmp_path):
    handler = make_handler(tmp_path / "srv", trusted_proxy=True)
    response = _request(
        handler,
        "POST",
        "/api/admin/tenants/clone",
        headers=ADMIN,
        body={"tenant_id": "org_new", "display_name": "New nonprofit"},
    )
    assert response.code == 503
    assert response.json["error"] == "tenant_provisioning_unavailable"
    assert list(tmp_path.iterdir()) == []


def test_missing_explicit_database_is_not_created(tmp_path, monkeypatch):
    database = tmp_path / "absent" / "registry.db"
    monkeypatch.setenv("IMPACT_RELAY_DATABASE_URL", "sqlite:///" + str(database))
    handler = make_handler(tmp_path / "srv", trusted_proxy=True)
    response = _request(handler, "GET", "/api/admin/tenants", headers=ADMIN)
    assert response.code == 500
    assert response.json == {"ok": False, "error": "internal_error"}
    assert not database.parent.exists()


@pytest.mark.parametrize(
    "tenant,subject,expected",
    [
        ("org_hacker_dojo", "human", 200),
        ("org_other", "human", 403),
        ("org_hacker_dojo", "agent:bot", 403),
    ],
)
def test_provider_principal_scope_and_human_gate(tmp_path, tenant, subject, expected):
    from impact_relay.auth.principal import Principal
    from impact_relay.auth.roles import Role
    from impact_relay.console_server import ServerConfig

    principal = Principal(
        subject=subject,
        tenant_id=tenant,
        email="admin@example.test",
        roles=frozenset({Role.TENANT_ADMIN}),
    )

    class Provider:
        def principal_for_token(self, token):
            assert token == "verified-by-provider"
            return principal

    cfg = ServerConfig(data_dir=tmp_path / "srv", identity_provider=Provider())
    response = _request(
        make_handler(cfg.data_dir, config=cfg),
        "GET",
        "/api/admin/tenants",
        headers={"Authorization": "Bearer verified-by-provider"},
    )
    assert response.code == expected
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("method,path", ROUTES)
def test_untrusted_admin_headers_are_not_identity(tmp_path, method, path):
    response = _request(make_handler(tmp_path / "srv"), method, path, headers=ADMIN)
    assert response.code == 401
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path", ["/api/admin/tenants", ROUTES[1][1]])
def test_corrupt_registry_is_500_not_false_success(tmp_path, path):
    root = tmp_path / "srv"
    root.mkdir()
    database = root / "storage.db"
    database.write_bytes(b"not a database")
    result = _request(make_handler(root, trusted_proxy=True), "GET", path, headers=ADMIN)
    assert result.code == 500
    assert result.json == {"ok": False, "error": "internal_error"}
    assert database.read_bytes() == b"not a database"


def test_symlinked_registry_is_rejected(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    target = tmp_path / "private.db"
    target.write_bytes(b"private")
    (root / "storage.db").symlink_to(target)
    result = _request(make_handler(root, trusted_proxy=True), "GET", ROUTES[1][1], headers=ADMIN)
    assert result.code == 403
    assert target.read_bytes() == b"private"


def test_sql_engine_read_only_rejects_writes(tmp_path):
    import sqlite3

    from impact_relay.storage.sql import SqlEngine

    database = tmp_path / "spaces #?" / "registry.db"
    writer = SqlEngine(database)
    writer.migrate()
    reader = SqlEngine(database, read_only=True)
    with reader.conn() as conn:
        assert reader.fetchone(conn, "SELECT COUNT(*) FROM tenants")[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute(conn, "DELETE FROM tenants")


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("trusted_proxy", [False, True])
def test_admin_rejects_public_fixture_bearer(tmp_path, method, path, trusted_proxy):
    handler = make_handler(
        tmp_path / "srv", trusted_proxy=trusted_proxy, allow_unauthenticated_pilot=True
    )
    response = _request(
        handler, method, path, headers={"Authorization": "Bearer admin@hackersdojo.example"}
    )
    assert response.code == 401
    assert list(tmp_path.iterdir()) == []
