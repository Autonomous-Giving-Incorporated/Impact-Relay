"""Real SQL command-log identity and read-only transaction regression tests.

Postgres tests opt in via IMPACT_RELAY_DATABASE_URL (a disposable test database
only). Each test creates/drops its own schema; no production database is safe.
"""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest

from impact_relay.domain.ledger_log import LedgerLogError
from impact_relay.domain.types import Organization
from impact_relay.storage.command_log import SqlLedgerCommandLog
from impact_relay.storage.sql import SqlEngine


@pytest.fixture
def postgres_url() -> Iterator[str]:
    url = os.environ.get("IMPACT_RELAY_DATABASE_URL")
    if not url:
        pytest.skip("set IMPACT_RELAY_DATABASE_URL to a disposable Postgres test database")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = "test_storage_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query["options"] = (
            query.get("options", "")
            + f" -csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"
        ).strip()
        yield urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(params=["sqlite", "postgres"])
def database(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    path = (
        str(tmp_path / "commands.sqlite")
        if request.param == "sqlite"
        else request.getfixturevalue("postgres_url")
    )
    SqlEngine(path).migrate()
    return path


def _request(**changes: Any) -> dict[str, Any]:
    return {
        "tenant_id": "org_test",
        "idempotency_key": "import:one",
        "command_type": "import_normalized_expense",
        "payload": {"amount": "10.00"},
        "result_json": {"entities": {}},
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"payload": {"amount": "20.00"}},
        {"command_type": "approve_expense"},
        {"payload": {}},
    ],
    ids=["changed-payload", "changed-command", "missing-payload-field"],
)
def test_append_rejects_changed_request_without_replacing_result(
    database: str, changes: dict[str, Any]
) -> None:
    log = SqlLedgerCommandLog(SqlEngine(database))
    log.append(**_request())
    before = log.iter_rows("org_test")
    with pytest.raises(LedgerLogError, match=r"idempotency.*conflict"):
        SqlLedgerCommandLog(SqlEngine(database)).append(**_request(**changes))
    assert log.iter_rows("org_test") == before


def test_identical_retry_uses_serialized_payload_and_keeps_first_result(database: str) -> None:
    log = SqlLedgerCommandLog(SqlEngine(database))
    log.append(**_request(payload={"amount": Decimal("10.00"), "refs": ("a", "b")}))
    before = log.iter_rows("org_test")
    reopened = SqlLedgerCommandLog(SqlEngine(database))
    reopened.append(
        **_request(
            payload={"refs": ["a", "b"], "amount": "10.00"},
            result_json={"entities": {}, "generated_id": "different-on-retry"},
        )
    )
    assert reopened.iter_rows("org_test") == before
    reopened.append(**_request(tenant_id="org_other", payload={"amount": "20.00"}))
    assert len(reopened.iter_rows("org_other")) == 1
    assert reopened.iter_rows("org_test") == before


def test_reopen_replays_first_result_not_retry_result_or_command(database: str) -> None:
    log = SqlLedgerCommandLog(SqlEngine(database))
    result = {
        "entities": {
            "donors": {
                "donor_test": {
                    "id": "donor_test",
                    "organization_id": "org_test",
                    "display_name": "Synthetic test donor",
                }
            }
        }
    }
    # Deliberately not dispatchable: replay must fold results, not run commands.
    request = _request(command_type="projection_test_only", result_json=result)
    log.append(**request)
    log.append(**{**request, "result_json": {"entities": {}}})
    reopened = SqlLedgerCommandLog(SqlEngine(database))
    organization = Organization(id="org_test", name="Synthetic test organization")
    rebuilt = reopened.rehydrate(organization)
    assert rebuilt.donors["donor_test"].display_name == "Synthetic test donor"
    assert reopened.rehydrate(organization).donors == rebuilt.donors
    assert len(reopened.iter_rows("org_test")) == 1


@pytest.mark.parametrize("number", [1e20, 1e-20])
def test_identical_retry_preserves_json_numbers(database: str, number: float) -> None:
    log = SqlLedgerCommandLog(SqlEngine(database))
    request = _request(payload={"measurement": number})
    log.append(**request)
    before = log.iter_rows("org_test")
    log.append(**request)
    assert log.iter_rows("org_test") == before


def test_boolean_is_not_numeric_identity(database: str) -> None:
    log = SqlLedgerCommandLog(SqlEngine(database))
    log.append(**_request(payload={"flag": True}))
    with pytest.raises(LedgerLogError, match=r"idempotency.*conflict"):
        log.append(**_request(payload={"flag": 1}))


@pytest.mark.parametrize("identical", [True, False], ids=["identical", "conflicting"])
def test_concurrent_append_arbitrates_across_independent_engines(
    database: str, identical: bool
) -> None:
    barrier = Barrier(2)

    def append(index: int) -> str:
        log = SqlLedgerCommandLog(SqlEngine(database))
        payload = {"amount": "10.00" if identical or index == 0 else "20.00"}
        barrier.wait(timeout=10)
        try:
            log.append(**_request(payload=payload, result_json={"winner": index, "entities": {}}))
        except LedgerLogError:
            return "conflict"
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, range(2)))
    assert sorted(outcomes) == (["ok", "ok"] if identical else ["conflict", "ok"])
    reopened = SqlLedgerCommandLog(SqlEngine(database))
    rows = reopened.iter_rows("org_test")
    assert len(rows) == 1
    winner = rows[0]["result_json"]["winner"]
    assert rows[0]["payload"] == {"amount": "10.00" if identical or winner == 0 else "20.00"}
    reopened.append(**_request(payload=rows[0]["payload"], result_json={"entities": {}}))
    assert reopened.iter_rows("org_test") == rows


def test_postgres_read_only_transactions_reject_writes_and_reopen(postgres_url: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    writer = SqlEngine(postgres_url)
    with writer.conn() as conn:
        writer.execute(conn, "CREATE TABLE read_only_probe (value INTEGER NOT NULL)")
        writer.execute(conn, "INSERT INTO read_only_probe VALUES (?)", (1,))
    reader = SqlEngine(postgres_url, read_only=True)
    statements = [
        "INSERT INTO read_only_probe VALUES (2)",
        "UPDATE read_only_probe SET value=2",
        "DELETE FROM read_only_probe",
        "CREATE TABLE forbidden_probe (value INTEGER)",
    ]
    for statement in statements:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with reader.conn() as conn:
                assert (
                    reader.fetchone(conn, "SHOW transaction_read_only")["transaction_read_only"]
                    == "on"
                )
                assert reader.fetchone(conn, "SELECT value FROM read_only_probe")["value"] == 1
                reader.execute(conn, statement)
        # Failed writes roll back; every fresh connection remains read-only.
        with reader.conn() as conn:
            assert reader.fetchall(conn, "SELECT value FROM read_only_probe") == [{"value": 1}]
            assert (
                reader.fetchone(conn, "SELECT to_regclass('forbidden_probe') AS name")["name"]
                is None
            )
    with writer.conn() as conn:
        assert writer.fetchone(conn, "SHOW transaction_read_only")["transaction_read_only"] == "off"
        writer.execute(conn, "INSERT INTO read_only_probe VALUES (?)", (2,))
    with SqlEngine(postgres_url, read_only=True).conn() as conn:
        assert reader.fetchall(conn, "SELECT value FROM read_only_probe ORDER BY value") == [
            {"value": 1},
            {"value": 2},
        ]
