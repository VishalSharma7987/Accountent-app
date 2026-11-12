"""The real per-request transaction of the API (commit on success, rollback on error), without the test override.

Needs real commits, so it lives in its own module and cleans the guarded test schema before and after.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import clients as clients_router
from app.api.deps import get_engine
from app.db import connection, migrate
from app.main import app
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
BODY = {"name": "Committed Co", "entity_type": "proprietorship", "business_type": "trading", "gst_type": "regular",
        "fy_start": "2026-04-01", "proprietor_name": "Owner"}


@pytest.fixture
def real_api(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    app.dependency_overrides[get_engine] = lambda: test_engine
    yield TestClient(app)
    app.dependency_overrides.clear()
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def count(test_conn, table):
    test_conn.rollback()  # a fresh view of what other connections committed
    value = test_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    test_conn.rollback()
    return value


def test_a_successful_request_is_committed(real_api, test_conn):
    r = real_api.post("/clients", json=BODY, headers=H)
    assert r.status_code == 201
    assert count(test_conn, "clients") == 1  # visible to another connection: it was committed
    assert count(test_conn, "ledgers") == 18 and count(test_conn, "audit_log") == 32
    assert real_api.get("/clients").json()[0]["name"] == "Committed Co"


def test_a_failed_request_leaves_nothing_behind_even_after_writing(real_api, test_conn, monkeypatch):
    def write_then_fail(conn, *args, **kwargs):
        conn.execute(text("INSERT INTO clients (name, entity_type, business_type, gst_type) "
                          "VALUES ('Half done', 'company', 'service', 'regular')"))
        raise ServiceError("conflict_for_test", "refused after a write")

    monkeypatch.setattr(clients_router.client_setup, "create_client", write_then_fail)
    r = real_api.post("/clients", json=BODY, headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "conflict_for_test")
    assert count(test_conn, "clients") == 0  # the write was rolled back


def test_requests_without_the_actor_header_write_nothing(real_api, test_conn):
    assert real_api.post("/clients", json=BODY).status_code == 400
    assert count(test_conn, "clients") == 0
