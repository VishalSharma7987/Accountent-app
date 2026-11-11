"""Migration 0004: money is rejected (not rounded) at database level; API roles hold no privileges."""

from decimal import Decimal
from pathlib import Path

import pytest
from dbfactory import Factory, check_deferred, rejected

pytestmark = pytest.mark.integration

MIGRATION = Path(__file__).resolve().parents[3] / "database" / "migrations" / "0004_exact_money_and_closed_grants.sql"
GRANTS_MARKER = "-- @@ section: close default grants"
API_ROLES = ("anon", "authenticated")


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


# =====================================================================================================
# Money: 10.005 must fail, never round to 10.01
# =====================================================================================================

LINE_INSERT = (
    "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit, credit) "
    "VALUES (%s, %s, 3, %s, %s, %s)"
)
OPENING_INSERT = (
    "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (%s, %s, %s, %s, %s)"
)


@pytest.fixture
def draft_voucher(f):
    client_id, fy_id = f.setup()
    lines = f.balanced_lines(client_id)
    return client_id, f.draft(client_id, fy_id, lines), lines[0][0]


@pytest.mark.parametrize("amount", ["10.005", "0.005", "0.001", "100.0001", "99.995", "1.234"])
def test_voucher_line_debit_with_more_than_two_decimals_is_rejected(f, draft_voucher, amount):
    client_id, voucher_id, ledger_id = draft_voucher
    with rejected(f.conn, constraint="voucher_lines_debit_two_decimals"):
        f.conn.execute(LINE_INSERT, (client_id, voucher_id, ledger_id, amount, "0"))


@pytest.mark.parametrize("amount", ["10.005", "0.005", "100.0001"])
def test_voucher_line_credit_with_more_than_two_decimals_is_rejected(f, draft_voucher, amount):
    client_id, voucher_id, ledger_id = draft_voucher
    with rejected(f.conn, constraint="voucher_lines_credit_two_decimals"):
        f.conn.execute(LINE_INSERT, (client_id, voucher_id, ledger_id, "0", amount))


@pytest.mark.parametrize("amount", ["10.5", "10.50", "10.5000", "10", "0.01", "99999999999999.99"])
def test_voucher_line_amounts_with_at_most_two_decimals_are_accepted_exactly(f, draft_voucher, amount):
    client_id, voucher_id, ledger_id = draft_voucher
    f.conn.execute(LINE_INSERT, (client_id, voucher_id, ledger_id, amount, "0"))
    stored = f.conn.execute("SELECT debit FROM voucher_lines WHERE voucher_id = %s AND line_no = 3", (voucher_id,)).fetchone()[0]
    assert stored == Decimal(amount)


def test_a_line_amount_is_never_silently_rounded_on_update(f, draft_voucher):
    client_id, voucher_id, _ = draft_voucher
    with rejected(f.conn, constraint="voucher_lines_debit_two_decimals"):
        f.conn.execute("UPDATE voucher_lines SET debit = 10.005 WHERE voucher_id = %s AND line_no = 1", (voucher_id,))
    assert f.conn.execute("SELECT debit FROM voucher_lines WHERE voucher_id = %s AND line_no = 1", (voucher_id,)).fetchone()[0] == Decimal("100.00")


def test_amount_with_more_than_14_whole_digits_is_rejected(f, draft_voucher):
    client_id, voucher_id, ledger_id = draft_voucher
    with rejected(f.conn, message="numeric field overflow"):
        f.conn.execute(LINE_INSERT, (client_id, voucher_id, ledger_id, "100000000000000.00", "0"))


@pytest.mark.parametrize("amount", ["10.005", "0.005", "100.0001"])
def test_opening_balance_with_more_than_two_decimals_is_rejected(f, amount):
    client_id, fy_id = f.setup()
    cash = f.ledger(client_id, "Cash", "cash_in_hand")
    with rejected(f.conn, constraint="opening_balances_debit_two_decimals"):
        f.conn.execute(OPENING_INSERT, (client_id, cash, fy_id, amount, "0"))
    with rejected(f.conn, constraint="opening_balances_credit_two_decimals"):
        f.conn.execute(OPENING_INSERT, (client_id, cash, fy_id, "0", amount))


@pytest.mark.parametrize("amount", ["10.5", "10.50", "10"])
def test_opening_balance_with_at_most_two_decimals_is_accepted_exactly(f, amount):
    client_id, fy_id = f.setup()
    cash = f.ledger(client_id, "Cash", "cash_in_hand")
    f.conn.execute(OPENING_INSERT, (client_id, cash, fy_id, "0", amount))
    stored = f.conn.execute("SELECT credit FROM opening_balances WHERE ledger_id = %s", (cash,)).fetchone()[0]
    assert stored == Decimal(amount)


def test_posting_still_compares_exact_amounts_after_the_type_change(f):
    """Dr 10.5 = Cr 10.50, and Dr 0.10 + 0.20 = Cr 0.30 exactly (the classic floating-point trap)."""
    client_id, fy_id = f.setup()
    a, b, c = f.ledger(client_id, "A"), f.ledger(client_id, "B"), f.ledger(client_id, "C", "cash_in_hand")
    same = f.draft(client_id, fy_id, [(a, "10.5", "0"), (c, "0", "10.50")])
    trap = f.draft(client_id, fy_id, [(a, "0.10", "0"), (b, "0.20", "0"), (c, "0", "0.30")])
    for voucher_id in (same, trap):
        f.approve(voucher_id)
        f.post(voucher_id)
    check_deferred(f.conn)
    assert f.status(same) == f.status(trap) == "posted"


def test_unbalanced_by_one_paisa_still_cannot_be_posted(f):
    client_id, fy_id = f.setup()
    a, c = f.ledger(client_id, "A"), f.ledger(client_id, "C", "cash_in_hand")
    voucher_id = f.draft(client_id, fy_id, [(a, "10.01", "0"), (c, "0", "10.00")])
    f.approve(voucher_id)
    f.post(voucher_id)
    with rejected(f.conn, message="is not balanced"):
        check_deferred(f.conn)


# =====================================================================================================
# Grants: anon / authenticated hold nothing
# =====================================================================================================


@pytest.fixture
def api_roles(f):
    present = [r[0] for r in f.conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(API_ROLES),))]
    if len(present) < len(API_ROLES):
        pytest.skip("anon/authenticated roles do not exist (not a Supabase database)")
    return present


def privileges_held_by_api_roles(conn) -> list[tuple]:
    """Every (role, object, privilege) that anon/authenticated hold on the current schema's tables,
    sequences and functions. PUBLIC grants count, because the API roles inherit them."""
    held = []
    held += conn.execute(
        "SELECT r.role, c.relname, p.priv FROM pg_class c "
        "CROSS JOIN (VALUES ('anon'), ('authenticated')) r(role) "
        "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p(priv) "
        "WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'r' "
        "AND has_table_privilege(r.role, c.oid, p.priv) ORDER BY 1, 2, 3"
    ).fetchall()
    held += conn.execute(
        "SELECT r.role, c.relname, p.priv FROM pg_class c "
        "CROSS JOIN (VALUES ('anon'), ('authenticated')) r(role) "
        "CROSS JOIN unnest(ARRAY['USAGE','SELECT','UPDATE']) p(priv) "
        "WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'S' "
        "AND has_sequence_privilege(r.role, c.oid, p.priv) ORDER BY 1, 2, 3"
    ).fetchall()
    held += conn.execute(
        "SELECT r.role, p.proname, 'EXECUTE' FROM pg_proc p "
        "CROSS JOIN (VALUES ('anon'), ('authenticated')) r(role) "
        "WHERE p.pronamespace = current_schema()::regnamespace "
        "AND has_function_privilege(r.role, p.oid, 'EXECUTE') ORDER BY 1, 2"
    ).fetchall()
    return held


def default_acl_entries_for_api_roles(conn) -> list[tuple]:
    return conn.execute(
        "SELECT defaclobjtype::text, defaclacl::text FROM pg_default_acl "
        "WHERE defaclnamespace = current_schema()::regnamespace "
        "AND (defaclacl::text LIKE '%anon=%' OR defaclacl::text LIKE '%authenticated=%')"
    ).fetchall()


def test_api_roles_hold_no_privilege_on_any_table_sequence_or_function(f, api_roles):
    assert privileges_held_by_api_roles(f.conn) == []


def test_api_roles_have_no_default_privileges_for_future_objects(f, api_roles):
    assert default_acl_entries_for_api_roles(f.conn) == []


def test_the_grants_section_of_the_migration_takes_supabase_style_grants_away_again(f, api_roles):
    """Recreate what Supabase grants by default, run the migration's grants section, expect nothing left."""
    section = MIGRATION.read_text(encoding="utf-8").split(GRANTS_MARKER)[1]
    sequence = f.conn.execute(
        "SELECT pg_get_serial_sequence('audit_log', 'id')"
    ).fetchone()[0]  # schema-qualified name of the identity sequence
    for role in API_ROLES:
        f.conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA {schema(f)} TO {role}")
        f.conn.execute(f"GRANT ALL ON ALL FUNCTIONS IN SCHEMA {schema(f)} TO {role}")
        f.conn.execute(f"GRANT ALL ON SEQUENCE {sequence} TO {role}")
        f.conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema(f)} GRANT ALL ON TABLES TO {role}")
        f.conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema(f)} GRANT ALL ON FUNCTIONS TO {role}")
    assert privileges_held_by_api_roles(f.conn) != []  # the setup really granted something
    assert default_acl_entries_for_api_roles(f.conn) != []

    f.conn.execute(section)

    assert privileges_held_by_api_roles(f.conn) == []
    assert default_acl_entries_for_api_roles(f.conn) == []


def test_the_backend_role_can_still_do_everything_it_needs(f, api_roles):
    """The connection role (postgres) keeps full access: it owns the objects."""
    client_id, fy_id = f.setup()
    f.posted(client_id, fy_id)
    for table in ("clients", "vouchers", "voucher_lines", "audit_log"):
        assert f.conn.execute(f"SELECT has_table_privilege(current_user, '{table}', 'SELECT, INSERT, UPDATE, DELETE')").fetchone()[0]


def schema(f: Factory) -> str:
    return f.conn.execute("SELECT quote_ident(current_schema())").fetchone()[0]
