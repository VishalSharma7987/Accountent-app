"""Step 8.0 foundation checks that need no database: migration 0019 text, seed / catalogue agreement, pure helpers, hooks and routers."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.engine import audit_types as t
from app.main import ROUTERS

ROOT = Path(__file__).resolve().parents[2].parent
MIGRATION = ROOT / "database" / "migrations" / "0019_audit.sql"
SEED = ROOT / "database" / "seeds" / "0014_audit_checks_limits.sql"
PLAN = ROOT / "docs" / "PHASE8_PLAN.md"
NEW_TABLES = [
    "audit_rule_limits", "audit_checks", "audit_form_defs", "audit_form_clauses", "audit_holidays", "audit_related_parties", "audit_runs",
    "audit_findings", "audit_working_papers", "audit_paper_items", "audit_paper_notes", "audit_ai_summaries", "audit_form_sets",
    "audit_form_entries",
]


def test_every_phase8_table_enables_row_level_security_and_has_no_policy():
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


def test_money_columns_carry_the_two_decimal_check():
    text = MIGRATION.read_text(encoding="utf-8")
    for column in ("amount", "disallowance_amount", "population_amount"):
        assert re.search(rf"{column}\s*=\s*round\({column}, 2\)", text), column


def test_the_migration_never_writes_to_the_books():
    text = MIGRATION.read_text(encoding="utf-8")
    assert not re.search(r"(UPDATE|DELETE FROM|INSERT INTO)\s+(vouchers|voucher_lines|ledgers)\b", text)


def test_the_catalogue_matches_the_seed_ids_titles_and_severities():
    seed = SEED.read_text(encoding="utf-8")
    rows = re.findall(r"\('(A-\d\d)', '([^']+)',.*?'(error|review|warning|info)', '(books|compliance|analytical)'", seed, re.DOTALL)
    assert [r[0] for r in rows] == sorted(t.CHECKS) and len(rows) == 18
    for check_id, title, severity, category in rows:
        info = t.CHECKS[check_id]
        assert (info.title, info.severity.value, info.category.value) == (title, severity, category), check_id


def test_every_check_is_explained_in_the_plan():
    plan = PLAN.read_text(encoding="utf-8")
    assert [c for c in t.CHECKS if c not in plan] == []


def _rule(on_from, on_to, amount="10000.00", breach="above", key="cash_payment_daily_limit"):
    return t.LimitRule(key, "x", "s", Decimal(amount), breach, Decimal("100.00"), on_from, on_to, "pending")


def test_A05_pick_limit_takes_the_row_in_force_on_the_date_and_none_when_no_row_covers_it():
    old = _rule(date(2017, 4, 1), date(2026, 3, 31), "10000.00")
    new = _rule(date(2026, 4, 1), None, "12000.00")
    assert t.pick_limit([old, new], "cash_payment_daily_limit", date(2026, 3, 31)).amount == Decimal("10000.00")
    assert t.pick_limit([old, new], "cash_payment_daily_limit", date(2026, 4, 1)).amount == Decimal("12000.00")
    assert t.pick_limit([old, new], "cash_payment_daily_limit", date(2016, 3, 31)) is None
    assert t.pick_limit([old, new], "cash_receipt_limit", date(2026, 4, 1)) is None


def test_A05_A06_breach_wording_above_versus_at_or_above():
    pay = _rule(date(2017, 4, 1), None, "10000.00", "above")
    rcpt = _rule(date(2017, 4, 1), None, "200000.00", "at_or_above", "cash_receipt_limit")
    assert not t.breaches(pay, Decimal("10000.00")) and t.breaches(pay, Decimal("10000.01"))
    assert t.breaches(rcpt, Decimal("200000.00")) and not t.breaches(rcpt, Decimal("199999.99"))


def test_population_digest_ignores_order_and_changes_with_content():
    a = t.population_digest(["b", "a", "c"])
    assert a == t.population_digest(["c", "b", "a"])
    assert a != t.population_digest(["a", "b"])
    assert len(a) == 64


def test_paper_path_matches_the_database_guard_and_signed_off_is_terminal():
    assert t.can_move_paper(t.PaperStatus.OPEN, t.PaperStatus.IN_REVIEW)
    assert t.can_move_paper(t.PaperStatus.IN_REVIEW, t.PaperStatus.SIGNED_OFF)
    assert not t.can_move_paper(t.PaperStatus.OPEN, t.PaperStatus.SIGNED_OFF)
    assert t.PAPER_TRANSITIONS[t.PaperStatus.SIGNED_OFF] == ()


def test_finding_key_and_sunday_helpers():
    assert t.finding_key("A-05", "p1", date(2026, 8, 14)) == "A-05:p1:2026-08-14"
    assert t.is_sunday(date(2026, 11, 22)) and not t.is_sunday(date(2026, 11, 23))


def test_the_phase8_routers_are_registered_and_the_hooks_import():
    from app.api import (
        audit_checks,
        audit_holidays,
        audit_papers,
        audit_related,
        audit_sampling,
        audit_summary,
        audit_tax,
    )
    from app.engine import audit_checks_analytic, audit_checks_books, audit_checks_compliance
    from app.services import audit_hooks

    for module in (audit_checks, audit_holidays, audit_related, audit_papers, audit_sampling, audit_tax, audit_summary):
        assert module.router in ROUTERS
    assert callable(audit_hooks.log_action) and callable(audit_hooks.require_ai_for_summary)
    assert "vouchers" in audit_hooks.READ_ONLY_TABLES
    for module in (audit_checks_books, audit_checks_compliance, audit_checks_analytic):
        assert isinstance(module.CHECKS, dict)


def test_check_registries_only_hold_catalogue_ids_and_never_the_same_id_twice():
    from app.engine import audit_checks_analytic, audit_checks_books, audit_checks_compliance

    seen: dict[str, str] = {}
    for module in (audit_checks_books, audit_checks_compliance, audit_checks_analytic):
        for check_id in module.CHECKS:
            assert check_id in t.CHECKS and check_id not in seen, check_id
            seen[check_id] = module.__name__
