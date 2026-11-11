"""Integration fixtures: they only ever touch the ledgermind_test schema."""

import pytest

from app import config
from app.db import connection, migrate


@pytest.fixture(scope="session")
def test_conn():
    url = config.test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    # connect() raises unless current_schema() = ledgermind_test
    conn = connection.connect(url, connection.TEST_SCHEMA)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def _emptied_test_schema(test_conn):
    """Once per session: empty every test-schema table (guarded) and put the seed data back.

    TRUNCATE ... CASCADE also empties the seeded account_groups, so the idempotent seed files run again.
    """
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def clean_db(test_conn, _emptied_test_schema):
    """The test connection, inside a transaction that is rolled back after the test.

    Tests never commit, so each starts from the seeded, otherwise empty schema; a test that did commit
    would show up here as a leftover client and fail loudly.
    """
    test_conn.rollback()
    leftover = test_conn.execute("SELECT count(*) FROM clients").fetchone()[0]
    assert leftover == 0, "a previous test committed data into ledgermind_test"
    yield test_conn
    test_conn.rollback()
