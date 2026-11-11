"""Connections and the test-schema guard.

One Supabase project, two schemas:
  public           = dev data
  ledgermind_test  = automated tests only (wiped freely)

Anything destructive (test cleanup) must pass the guard first: it runs only when the
connection's current_schema() is exactly 'ledgermind_test'.
"""

from collections.abc import Iterable

import psycopg

DEV_SCHEMA = "public"
TEST_SCHEMA = "ledgermind_test"
MIGRATIONS_TABLE = "schema_migrations"


class SchemaGuardError(RuntimeError):
    """Raised when code is about to run against the wrong schema."""


def require_schema(actual: str | None, expected: str) -> None:
    if actual != expected:
        raise SchemaGuardError(
            f"Refusing to run: current_schema() is {actual!r}, expected {expected!r}."
        )


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def truncate_statement(schema: str, tables: Iterable[str]) -> str:
    """TRUNCATE for tables of the test schema only. Never builds anything else (no DROP)."""
    require_schema(schema, TEST_SCHEMA)
    names = [f"{quote_identifier(schema)}.{quote_identifier(t)}" for t in tables]
    if not names:
        raise ValueError("No tables to truncate")
    return "TRUNCATE TABLE " + ", ".join(names) + " RESTART IDENTITY CASCADE"


def driver_url(url: str) -> str:
    """psycopg wants 'postgresql://'; config may hold the SQLAlchemy form."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def current_schema(conn: psycopg.Connection) -> str | None:
    return conn.execute("SELECT current_schema()").fetchone()[0]


def connect(url: str, schema: str) -> psycopg.Connection:
    """Open a connection whose search_path is exactly `schema`; the guard is checked for the test schema.

    Works through Supabase's session pooler (port 5432). Set via SET, not a startup option,
    because poolers may ignore startup options.
    """
    conn = psycopg.connect(driver_url(url), prepare_threshold=None)
    try:
        conn.execute("SELECT set_config('search_path', %s, false)", (schema,))
        conn.commit()
        require_schema(current_schema(conn), schema)
    except Exception:
        conn.close()
        raise
    return conn


def ensure_test_schema(conn: psycopg.Connection) -> None:
    """Create the test schema if missing and close it to the Supabase API roles.

    Do NOT add this schema to the Supabase API 'exposed schemas'.
    """
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(TEST_SCHEMA)}")
    conn.execute(f"REVOKE ALL ON SCHEMA {quote_identifier(TEST_SCHEMA)} FROM PUBLIC")
    # anon / authenticated exist on Supabase only; skip them on plain PostgreSQL.
    conn.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM %I', 'ledgermind_test', r);
                END IF;
            END LOOP;
        END $$;
        """
    )
    conn.commit()


def clean_test_tables(conn: psycopg.Connection) -> list[str]:
    """Empty every table in ledgermind_test except the migrations table. Guarded."""
    require_schema(current_schema(conn), TEST_SCHEMA)
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename <> %s ORDER BY tablename",
        (TEST_SCHEMA, MIGRATIONS_TABLE),
    ).fetchall()
    tables = [r[0] for r in rows]
    if tables:
        conn.execute(truncate_statement(TEST_SCHEMA, tables))
    conn.commit()
    return tables
