from app import config
from app.db import connection, migrate


def test_migrations_apply_in_test_schema_only(test_conn):
    applied = migrate.apply_migrations(config.test_database_url(), connection.TEST_SCHEMA)
    assert isinstance(applied, list)

    names = [
        r[0] for r in test_conn.execute("SELECT filename FROM schema_migrations ORDER BY filename")
    ]
    test_conn.commit()
    assert names[:2] == ["0001_schema_migrations.sql", "0002_revoke_rls_auto_enable.sql"]
    # the unqualified table above was resolved inside the test schema
    assert connection.current_schema(test_conn) == "ledgermind_test"
    found = test_conn.execute("SELECT to_regclass('ledgermind_test.schema_migrations')").fetchone()
    assert found[0] is not None


def test_running_again_applies_nothing(test_conn):
    assert migrate.apply_migrations(config.test_database_url(), connection.TEST_SCHEMA) == []


def test_test_schema_is_closed_to_api_roles_and_has_rls(test_conn):
    anon_usage = test_conn.execute(
        "SELECT has_schema_privilege('anon', 'ledgermind_test', 'USAGE')"
    ).fetchone()[0]
    auth_usage = test_conn.execute(
        "SELECT has_schema_privilege('authenticated', 'ledgermind_test', 'USAGE')"
    ).fetchone()[0]
    rls = test_conn.execute(
        "SELECT relrowsecurity FROM pg_class "
        "WHERE oid = 'ledgermind_test.schema_migrations'::regclass"
    ).fetchone()[0]
    test_conn.commit()
    assert (anon_usage, auth_usage, rls) == (False, False, True)


def test_cleanup_keeps_the_migrations_table(clean_db):
    count = clean_db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    assert count >= 2
