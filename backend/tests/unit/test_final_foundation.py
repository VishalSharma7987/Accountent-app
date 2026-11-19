"""Step 6.0 foundation checks that need no database: the migration text, the seeds, the engine types and the registered routers."""

import re
from dataclasses import fields, is_dataclass
from decimal import Decimal
from pathlib import Path

from app.engine import final_types as t
from app.main import ROUTERS

ROOT = Path(__file__).resolve().parents[2].parent
MIGRATION = ROOT / "database" / "migrations" / "0017_final_accounts.sql"
NEW_TABLES = [
    "dep_it_block_rates", "dep_it_rules", "dep_sched2_classes", "fs_lines", "fs_group_map", "client_ledger_fs_map", "final_ledger_roles",
    "partners", "partner_fy_terms", "adjustment_entries", "fixed_assets", "fixed_asset_events", "depreciation_runs",
    "depreciation_run_lines", "it_block_openings", "it_depreciation_workings", "final_closing_stock", "statement_snapshots",
    "year_end_closes", "year_end_close_vouchers",
]


def test_every_final_accounts_table_enables_row_level_security_and_has_no_policy():
    text = MIGRATION.read_text(encoding="utf-8")
    created = re.findall(r"CREATE TABLE (\w+) \(", text)
    assert sorted(created) == sorted(NEW_TABLES)
    for table in created:
        assert re.search(rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;", text), table
    assert "CREATE POLICY" not in text.upper()


def test_the_migration_closes_function_privileges_and_is_schema_agnostic():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA" in text
    assert not re.search(r"\b(public|ledgermind_test)\s*\.", text, re.IGNORECASE)


def test_every_money_column_has_the_two_decimal_check_and_no_numeric_18_2():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "numeric(18, 2)" not in text
    for col in re.findall(r"^\s+(\w+)\s+numeric\(18, 4\)", text, re.MULTILINE):
        assert re.search(rf"{col} = round\({col}, 2\)", text), col


def test_the_law_tables_carry_effective_dates_source_and_verification_status():
    text = MIGRATION.read_text(encoding="utf-8")
    for table in ("dep_it_block_rates", "dep_it_rules", "dep_sched2_classes", "fs_lines", "fs_group_map"):
        body = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", text, re.DOTALL).group(1)
        for column in ("effective_from", "effective_to", "source_reference", "verification_status"):
            assert column in body, (table, column)


def test_the_new_seeds_never_mark_a_value_verified():
    for name in ("0012_depreciation_rates.sql", "0013_schedule_iii_lines.sql"):
        text = (ROOT / "database" / "seeds" / name).read_text(encoding="utf-8")
        assert not re.search(r",\s*'verified'\s*[,)]", text), name


def test_the_seven_final_routers_are_registered():
    from app.api import (
        final_adjustments,
        final_assets,
        final_cashflow,
        final_close,
        final_export,
        final_sch3,
        final_statements,
    )

    for module in (final_adjustments, final_assets, final_statements, final_sch3, final_cashflow, final_export, final_close):
        assert module.router in ROUTERS


def test_engine_types_are_frozen_decimal_data():
    for name in ("AdjustmentInput", "AssetEvent", "ItBlockInput", "LedgerBalanceIn", "StatementLine", "Statement", "CarryForward"):
        cls = getattr(t, name)
        assert is_dataclass(cls) and cls.__dataclass_params__.frozen, name
    line = t.StatementLine("sales", "Sales", Decimal("1200000.00"))
    assert line.previous_amount is None and line.drill == ()
    assert {f.name for f in fields(t.Finding)} >= {"rule_id", "message", "severity"}
    assert t.AdjustmentType.PROVISION_DOUBTFUL_DEBTS.value == "provision_doubtful_debts"


def test_the_year_end_hooks_exist():
    from app.services import final_hooks

    assert callable(final_hooks.year_is_closed) and callable(final_hooks.guard_reverse)
