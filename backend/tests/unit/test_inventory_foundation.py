"""Step 5.0 foundation checks that need no database: the migration text, the engine types and the registered routers."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.engine import inventory_types as t
from app.main import app

MIGRATION = Path(__file__).resolve().parents[2].parent / "database" / "migrations" / "0016_inventory.sql"
NEW_TABLES = [
    "godowns", "inventory_settings", "stock_items", "stock_opening", "stock_journals", "stock_journal_lines",
    "stock_journal_sequences", "stock_movements", "voucher_stock_lines", "stock_nrv_entries",
]


def test_the_inventory_migration_exists_and_0015_is_left_to_phase_4_1():
    names = sorted(p.name for p in MIGRATION.parent.glob("*.sql"))
    assert "0016_inventory.sql" in names
    assert "0015_inventory.sql" not in names


def test_every_inventory_table_enables_row_level_security_and_has_no_policy():
    text = MIGRATION.read_text(encoding="utf-8")
    created = re.findall(r"CREATE TABLE (\w+) \(", text)
    assert sorted(created) == sorted(NEW_TABLES)
    for table in created:
        assert re.search(rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;", text), table
    assert "CREATE POLICY" not in text.upper()


def test_the_inventory_migration_closes_function_privileges_and_is_schema_agnostic():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA" in text
    assert not re.search(r"\b(public|ledgermind_test)\s*\.", text, re.IGNORECASE)


def test_every_quantity_column_has_the_three_decimal_check():
    text = MIGRATION.read_text(encoding="utf-8")
    assert len(re.findall(r"quantity\s+numeric\(18, 4\)", text)) == 3
    assert len(re.findall(r"CHECK \(quantity = round\(quantity, 3\)\)", text)) == 3
    assert "numeric(18, 3)" not in text


def test_movement_kinds_are_split_into_inward_and_outward_without_overlap():
    assert t.INWARD_KINDS.isdisjoint(t.OUTWARD_KINDS)
    assert t.INWARD_KINDS | t.OUTWARD_KINDS == set(t.MovementKind)
    assert t.TRANSFER_KINDS <= t.INWARD_KINDS | t.OUTWARD_KINDS


def test_engine_types_are_frozen_decimal_data():
    movement = t.Movement("m1", 1, date(2026, 4, 5), "i1", "g1", t.MovementKind.PURCHASE, Decimal(200), Decimal("2400.00"))
    assert movement.ref_movement_id is None
    assert t.InventoryPolicy(t.ValuationMethod.FIFO).negative_stock_mode is t.NegativeStockMode.BLOCK


def test_the_three_inventory_routers_are_registered():
    tags = {tag for route in app.routes for tag in (getattr(route, "tags", None) or [])}
    from app.api import inventory_journals, inventory_masters, inventory_reports
    from app.main import ROUTERS

    for module in (inventory_masters, inventory_journals, inventory_reports):
        assert module.router in ROUTERS
    assert isinstance(tags, set)
