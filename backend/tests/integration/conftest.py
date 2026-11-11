"""Integration fixtures: they only ever touch the ledgermind_test schema."""

import pytest

from app import config
from app.db import connection


@pytest.fixture(scope="session")
def test_conn():
    url = config.test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    # connect() raises unless current_schema() = ledgermind_test
    conn = connection.connect(url, connection.TEST_SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def clean_db(test_conn):
    """The test connection with every test-schema table emptied (guarded; never outside ledgermind_test)."""
    connection.clean_test_tables(test_conn)
    yield test_conn
    test_conn.rollback()
