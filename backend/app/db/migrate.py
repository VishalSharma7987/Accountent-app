"""Apply database/migrations/NNNN_name.sql files in name order, one transaction per file.

Usage (from backend/):  python -m app.db.migrate --target dev|test

After the migrations, the files in database/seeds/ are applied the same way (one transaction per file) and
recorded in schema_migrations as 'seeds/<file>'. Seed files are written to be safe to run more than once.

  dev  -> schema public           (DATABASE_URL)
  test -> schema ledgermind_test  (TEST_DATABASE_URL, same project; schema is created if missing)

Migration files are schema-agnostic: they never name a schema; the connection's search_path decides
where objects go. Each schema has its own schema_migrations table.
Plain PostgreSQL only: the same SQL runs on any Postgres, not just Supabase.
"""

import argparse
import re
import sys
from pathlib import Path

from app import config
from app.db import connection
from app.db.connection import DEV_SCHEMA, MIGRATIONS_TABLE, TEST_SCHEMA

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "database" / "migrations"
SEEDS_DIR = Path(__file__).resolve().parents[3] / "database" / "seeds"
_FILENAME = re.compile(r"^\d{4}_[A-Za-z0-9_]+\.sql$")


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """Migration files in name order. A .sql file with a bad name is an error, never skipped."""
    files = sorted(directory.glob("*.sql"))
    bad = [f.name for f in files if not _FILENAME.match(f.name)]
    if bad:
        raise ValueError(f"Migration file names must look like 0001_name.sql: {bad}")
    return files


def seed_files(directory: Path = SEEDS_DIR) -> list[Path]:
    """Seed files in name order; same naming rule as migrations."""
    return migration_files(directory)


def seed_record_name(path: Path) -> str:
    return f"seeds/{path.name}"


def apply_seed_sql(conn) -> list[str]:
    """Run every seed file on `conn` (no bookkeeping). For test cleanup, which empties the seeded tables.

    The caller's connection decides the schema; the seed files are idempotent.
    """
    names = []
    for path in seed_files():
        conn.execute(path.read_text(encoding="utf-8"))
        names.append(path.name)
    conn.commit()
    return names


def target_settings(target: str, dev_url: str | None, test_url: str | None) -> tuple[str, str]:
    """(url, schema) for 'dev' or 'test'."""
    url, name, schema = (
        (dev_url, "DATABASE_URL", DEV_SCHEMA)
        if target == "dev"
        else (test_url, "TEST_DATABASE_URL", TEST_SCHEMA)
    )
    if not url:
        raise SystemExit(f"{name} is not set in .env")
    return url, schema


def apply_migrations(
    url: str,
    schema: str,
    directory: Path = MIGRATIONS_DIR,
    seeds_directory: Path = SEEDS_DIR,
) -> list[str]:
    """Apply every pending migration, then every pending seed, inside `schema`.

    Returns what was applied in this run (seeds appear as 'seeds/<file>').
    """
    files = [(path, path.name) for path in migration_files(directory)]
    files += [(path, seed_record_name(path)) for path in seed_files(seeds_directory)]
    applied_now: list[str] = []

    if schema == TEST_SCHEMA:
        with connection.connect(url, DEV_SCHEMA) as setup_conn:
            connection.ensure_test_schema(setup_conn)

    with connection.connect(url, schema) as conn:
        has_table = conn.execute(
            "SELECT to_regclass(quote_ident(current_schema()) || '.' || %s) IS NOT NULL",
            (MIGRATIONS_TABLE,),
        ).fetchone()[0]
        already: set[str] = set()
        if has_table:
            already = {r[0] for r in conn.execute(f"SELECT filename FROM {MIGRATIONS_TABLE}")}
        conn.commit()

        for path, record in files:
            if record in already:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(f"INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES (%s)", (record,))
            applied_now.append(record)
    return applied_now


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply SQL migrations.")
    parser.add_argument("--target", choices=["dev", "test"], required=True)
    args = parser.parse_args(argv)

    url, schema = target_settings(args.target, config.database_url(), config.test_database_url())
    applied = apply_migrations(url, schema)
    label = f"[{args.target}:{schema}]"
    if applied:
        print(f"{label} applied: " + ", ".join(applied))
    else:
        print(f"{label} nothing to apply; up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
