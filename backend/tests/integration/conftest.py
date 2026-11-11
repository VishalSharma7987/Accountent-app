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
    When the session ends, nothing may be left behind: a test that committed data fails the whole run.
    """
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    yield
    test_conn.rollback()
    leftover = test_conn.execute("SELECT count(*) FROM clients").fetchone()[0]
    test_conn.rollback()
    assert leftover == 0, "a test committed data into ledgermind_test and did not clean up"


@pytest.fixture
def clean_db(test_conn, _emptied_test_schema):
    """The test connection, inside a transaction that is rolled back after the test.

    Tests never commit (the one cleanup test does, and cleans up after itself), so every test starts
    from the seeded, otherwise empty schema.
    """
    yield test_conn
    test_conn.rollback()
