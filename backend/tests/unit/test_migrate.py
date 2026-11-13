import re
from pathlib import Path

import pytest

from app.db import migrate

REPO = Path(__file__).resolve().parents[3]


def test_dev_target_uses_public_schema():
    assert migrate.target_settings("dev", "postgresql://d", "postgresql://t") == (
        "postgresql://d",
        "public",
    )


def test_test_target_uses_ledgermind_test_schema():
    assert migrate.target_settings("test", "postgresql://d", "postgresql://t") == (
        "postgresql://t",
        "ledgermind_test",
    )


def test_missing_url_is_an_error():
    with pytest.raises(SystemExit, match="TEST_DATABASE_URL is not set"):
        migrate.target_settings("test", "postgresql://d", None)


def test_migration_files_are_sorted_and_names_checked(tmp_path):
    (tmp_path / "0002_b.sql").write_text("select 1;")
    (tmp_path / "0001_a.sql").write_text("select 1;")
    assert [f.name for f in migrate.migration_files(tmp_path)] == ["0001_a.sql", "0002_b.sql"]
    (tmp_path / "notes.sql").write_text("select 1;")
    with pytest.raises(ValueError, match="notes.sql"):
        migrate.migration_files(tmp_path)


def test_real_migrations_are_in_order():
    names = [f.name for f in migrate.migration_files()]
    assert names[:4] == [
        "0001_schema_migrations.sql",
        "0002_revoke_rls_auto_enable.sql",
        "0003_accounting_core.sql",
        "0004_exact_money_and_closed_grants.sql",
    ]


def test_seeds_are_listed_in_name_order_and_recorded_with_a_prefix():
    seeds = migrate.seed_files()
    assert [s.name for s in seeds] == [
        "0001_account_groups.sql",
        "0002_msme_payment_rules.sql",
        "0003_msme_rule_corrections.sql",
        "0004_gst_state_codes_uqc.sql",
        "0005_gst_rate_slabs_rules.sql",
        "0006_gst_rcm_blocked_itc_rules.sql",
        "0007_gst_composition_thresholds.sql",
        "0008_tds_sections_rates.sql",
        "0009_tds_due_dates_interest_forms.sql",
    ]
    assert migrate.seed_record_name(seeds[0]) == "seeds/0001_account_groups.sql"


def test_seed_file_names_are_checked(tmp_path):
    (tmp_path / "groups.sql").write_text("select 1;")
    with pytest.raises(ValueError, match="groups.sql"):
        migrate.seed_files(tmp_path)


def test_every_function_in_migrations_pins_its_search_path():
    """Each CREATE FUNCTION must say SET search_path FROM CURRENT (schema-agnostic and advisor-clean)."""
    for path in migrate.migration_files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"CREATE\s+FUNCTION\s+(\w+)\(\).*?\$\$", text, re.IGNORECASE | re.DOTALL):
            assert "SET search_path FROM CURRENT" in match.group(0), f"{path.name}: {match.group(1)}"


def test_sql_files_never_hardcode_a_schema():
    """Migrations and seeds are schema-agnostic: the connection's search_path decides the schema."""
    offenders = []
    for folder in ("database/migrations", "database/seeds"):
        for path in (REPO / folder).glob("*.sql"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\b(public|ledgermind_test)\s*\.", text, re.IGNORECASE):
                offenders.append(path.name)
            # 'SET search_path FROM CURRENT' on a function is allowed: it pins the schema it was created in
            if re.search(r"\bSET\s+search_path\s+(TO|=)|\bCREATE\s+SCHEMA\b", text, re.IGNORECASE):
                offenders.append(path.name)
    assert offenders == []
