import pytest

from app.db import connection
from app.db.connection import SchemaGuardError


def test_guard_passes_only_for_the_expected_schema():
    connection.require_schema("ledgermind_test", "ledgermind_test")


@pytest.mark.parametrize(
    "actual", ["public", "extensions", "", None, "LEDGERMIND_TEST", "ledgermind_test2"]
)
def test_guard_refuses_any_other_schema(actual):
    with pytest.raises(SchemaGuardError):
        connection.require_schema(actual, "ledgermind_test")


def test_truncate_is_built_only_for_the_test_schema():
    sql = connection.truncate_statement("ledgermind_test", ["vouchers", "ledgers"])
    assert sql == (
        'TRUNCATE TABLE "ledgermind_test"."vouchers", "ledgermind_test"."ledgers" '
        "RESTART IDENTITY CASCADE"
    )


@pytest.mark.parametrize("schema", ["public", "auth", "ledgermind_test2", ""])
def test_truncate_refuses_other_schemas(schema):
    with pytest.raises(SchemaGuardError):
        connection.truncate_statement(schema, ["vouchers"])


def test_truncate_needs_tables():
    with pytest.raises(ValueError):
        connection.truncate_statement("ledgermind_test", [])


def test_identifiers_are_quoted_so_names_cannot_inject_sql():
    sql = connection.truncate_statement("ledgermind_test", ['x"; DROP TABLE y; --'])
    assert sql == (
        'TRUNCATE TABLE "ledgermind_test"."x""; DROP TABLE y; --" RESTART IDENTITY CASCADE'
    )


def test_no_statement_builder_can_produce_drop():
    sql = connection.truncate_statement("ledgermind_test", ["a", "b"])
    assert sql.startswith("TRUNCATE TABLE ") and "DROP" not in sql.upper()


def test_connect_checks_the_guard_for_the_test_schema(monkeypatch):
    """connect() must close the connection and raise if the search_path did not take effect."""
    closed = []

    class FakeConn:
        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return ("public",)  # pooler ignored our search_path

        def commit(self):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setattr(connection.psycopg, "connect", lambda *a, **k: FakeConn())
    with pytest.raises(SchemaGuardError):
        connection.connect("postgresql://x", "ledgermind_test")
    assert closed == [True]
