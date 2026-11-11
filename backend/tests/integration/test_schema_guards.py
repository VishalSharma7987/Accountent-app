"""Step 1.1: prove every database-level guard of 0003_accounting_core.sql blocks what it should.

Runs only in the ledgermind_test schema. Each test builds its own rows inside a transaction that is rolled back.
Expected values are typed literally.
"""

from decimal import Decimal

import pytest
from chart_fixture import EXPECTED_GROUPS
from dbfactory import Factory, check_deferred, rejected, swapped

from app.db import connection, migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def count(f: Factory, table: str) -> int:
    return f.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def voucher_in_status(f: Factory, status: str):
    """(client_id, fy_id, voucher_id, lines) with a balanced voucher in the given status."""
    client_id, fy_id = f.setup()
    lines = f.balanced_lines(client_id)
    vid = f.draft(client_id, fy_id, lines)
    if status == "draft":
        return client_id, fy_id, vid, lines
    f.approve(vid)
    if status == "approved":
        return client_id, fy_id, vid, lines
    f.post(vid)
    check_deferred(f.conn)
    if status == "posted":
        return client_id, fy_id, vid, lines
    assert status == "reversed"
    f.reverse(client_id, fy_id, vid, lines)
    return client_id, fy_id, vid, lines


# =====================================================================================================
# Row-level security and table list
# =====================================================================================================


def test_every_table_has_row_level_security_and_no_policies(f):
    rows = f.conn.execute(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c "
        "WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'r'"
    ).fetchall()
    assert sorted(rows) == [
        ("account_groups", True),
        ("audit_log", True),
        ("clients", True),
        ("financial_years", True),
        ("ledgers", True),
        ("opening_balances", True),
        ("periods", True),
        ("schema_migrations", True),
        ("voucher_lines", True),
        ("voucher_number_sequences", True),
        ("vouchers", True),
    ]
    policies = f.conn.execute("SELECT count(*) FROM pg_policies WHERE schemaname = current_schema()").fetchone()[0]
    assert policies == 0


# =====================================================================================================
# Seed: system account groups
# =====================================================================================================



def test_seed_creates_the_23_system_groups_exactly(f):
    rows = f.conn.execute(
        "SELECT g.code, g.name, p.code, g.nature, g.report FROM account_groups g "
        "LEFT JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id IS NULL AND g.is_system"
    ).fetchall()
    assert sorted(rows) == EXPECTED_GROUPS  # sorted in Python: independent of the database collation
    assert len(rows) == 23
    assert count(f, "account_groups") == 23


def test_seed_can_run_again_without_changing_anything(f):
    migrate.apply_seed_sql(f.conn)
    assert count(f, "account_groups") == 23


def test_system_group_cannot_be_edited(f):
    with rejected(f.conn, message="system groups cannot be edited"):
        f.conn.execute("UPDATE account_groups SET name = 'Renamed' WHERE code = 'sundry_debtors'")


def test_system_group_cannot_be_deleted(f):
    with rejected(f.conn, message="system groups cannot be deleted"):
        f.conn.execute("DELETE FROM account_groups WHERE code = 'provisions'")


def test_system_group_flag_must_match_client_id(f):
    client_id = f.client()
    parent = f.group("current_assets")
    with rejected(f.conn, constraint="account_groups_system_flag"):
        f.conn.execute(
            "INSERT INTO account_groups (client_id, code, name, parent_id, nature, report, is_system) "
            "VALUES (%s, 'x', 'X', %s, 'asset', 'balance_sheet', true)",
            (client_id, parent),
        )


# =====================================================================================================
# Custom (client) account groups
# =====================================================================================================


def custom_group(f, client_id, code, name, parent_code="current_assets", nature="asset", report="balance_sheet"):
    return f.conn.execute(
        "INSERT INTO account_groups (client_id, code, name, parent_id, nature, report) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (client_id, code, name, f.group(parent_code), nature, report),
    ).fetchone()[0]


def test_custom_group_with_matching_parent_is_accepted(f):
    client_id = f.client()
    gid = custom_group(f, client_id, "petty_cash", "Petty Cash Boxes")
    row = f.conn.execute("SELECT is_system, client_id FROM account_groups WHERE id = %s", (gid,)).fetchone()
    assert row == (False, client_id)


def test_custom_group_must_have_a_parent(f):
    client_id = f.client()
    with rejected(f.conn, constraint="account_groups_custom_needs_parent"):
        f.conn.execute(
            "INSERT INTO account_groups (client_id, code, name, nature, report) "
            "VALUES (%s, 'orphan', 'Orphan', 'asset', 'balance_sheet')",
            (client_id,),
        )


@pytest.mark.parametrize(
    ("nature", "report"),
    [("liability", "balance_sheet"), ("asset", "profit_loss"), ("expense", "trading")],
)
def test_custom_group_nature_and_report_must_equal_the_parents(f, nature, report):
    client_id = f.client()
    with rejected(f.conn, message="same nature and report as its parent"):
        custom_group(f, client_id, "wrong", "Wrong", parent_code="current_assets", nature=nature, report=report)


def test_custom_group_name_is_unique_inside_one_client_ignoring_case(f):
    client_id = f.client()
    custom_group(f, client_id, "g1", "Petty Cash Boxes")
    with rejected(f.conn, constraint="account_groups_client_name_key"):
        custom_group(f, client_id, "g2", "petty cash boxes")


def test_custom_group_code_is_unique_inside_one_client(f):
    client_id = f.client()
    custom_group(f, client_id, "g1", "First")
    with rejected(f.conn, constraint="account_groups_client_code_key"):
        custom_group(f, client_id, "g1", "Second")


def test_two_clients_may_use_the_same_custom_group_name(f):
    a, b = f.client(), f.client()
    custom_group(f, a, "g1", "Petty Cash Boxes")
    custom_group(f, b, "g1", "Petty Cash Boxes")
    assert count(f, "account_groups") == 25


@pytest.mark.parametrize(("code", "name"), [("g9", "Sundry Debtors"), ("g9", "sundry debtors"), ("sundry_debtors", "Mine")])
def test_custom_group_cannot_reuse_a_system_group_name_or_code(f, code, name):
    client_id = f.client()
    with rejected(f.conn, message="cannot reuse the name or code of a system group"):
        custom_group(f, client_id, code, name)


def test_custom_group_parent_cannot_be_another_clients_custom_group(f):
    a, b = f.client(), f.client()
    parent = custom_group(f, a, "g1", "A's group")
    with rejected(f.conn, message="parent must be a system group or a group of the same client"):
        f.conn.execute(
            "INSERT INTO account_groups (client_id, code, name, parent_id, nature, report) "
            "VALUES (%s, 'g2', 'B child', %s, 'asset', 'balance_sheet')",
            (b, parent),
        )


def test_custom_group_can_be_renamed_but_not_moved_or_reclassified(f):
    client_id = f.client()
    gid = custom_group(f, client_id, "g1", "Old name")
    f.conn.execute("UPDATE account_groups SET name = 'New name' WHERE id = %s", (gid,))
    for change in ("nature = 'liability'", "report = 'profit_loss'", f"parent_id = '{f.group('bank_accounts')}'"):
        with rejected(f.conn, message="only the name and code of a custom group can be changed"):
            f.conn.execute(f"UPDATE account_groups SET {change} WHERE id = %s", (gid,))
    assert f.conn.execute("SELECT name FROM account_groups WHERE id = %s", (gid,)).fetchone()[0] == "New name"


def test_custom_group_can_be_deleted_while_unused(f):
    client_id = f.client()
    gid = custom_group(f, client_id, "g1", "Temp")
    f.conn.execute("DELETE FROM account_groups WHERE id = %s", (gid,))
    assert count(f, "account_groups") == 23


# =====================================================================================================
# Ledgers
# =====================================================================================================


def test_ledger_name_is_unique_per_client_ignoring_case(f):
    client_id = f.client()
    f.ledger(client_id, "Cash")
    with rejected(f.conn, constraint="ledgers_client_name_key"):
        f.ledger(client_id, "CASH")


def test_two_clients_may_have_ledgers_with_the_same_name(f):
    f.ledger(f.client(), "Cash")
    f.ledger(f.client(), "Cash")
    assert count(f, "ledgers") == 2


def test_ledger_can_use_a_system_group_or_its_own_clients_custom_group(f):
    client_id = f.client()
    gid = custom_group(f, client_id, "g1", "Mine")
    f.conn.execute(
        "INSERT INTO ledgers (client_id, group_id, name) VALUES (%s, %s, 'In custom group')", (client_id, gid)
    )
    f.ledger(client_id, "In system group", "bank_accounts")
    assert count(f, "ledgers") == 2


def test_ledger_cannot_use_another_clients_custom_group(f):
    a, b = f.client(), f.client()
    gid = custom_group(f, a, "g1", "A's group")
    with rejected(f.conn, message="system group or a group of its own client"):
        f.conn.execute("INSERT INTO ledgers (client_id, group_id, name) VALUES (%s, %s, 'Sneaky')", (b, gid))


def test_ledger_name_cannot_be_blank(f):
    with rejected(f.conn, constraint="ledgers_name_not_blank"):
        f.ledger(f.client(), "   ")


# =====================================================================================================
# Clients
# =====================================================================================================


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("entity_type", "trust", "clients_entity_type_check"),
        ("business_type", "farming", "clients_business_type_check"),
        ("gst_type", "exempt", "clients_gst_type_check"),
    ],
)
def test_client_profile_values_are_checked(f, column, value, constraint):
    values = {"entity_type": "company", "business_type": "service", "gst_type": "regular"}
    values[column] = value
    with rejected(f.conn, constraint=constraint):
        f.conn.execute(
            "INSERT INTO clients (name, entity_type, business_type, gst_type) VALUES ('C', %s, %s, %s)",
            (values["entity_type"], values["business_type"], values["gst_type"]),
        )


# =====================================================================================================
# Financial years: 1 April - 31 March
# =====================================================================================================


def test_financial_year_1_apr_to_31_mar_is_accepted_including_leap_year(f):
    client_id = f.client()
    f.fy(client_id, 2026)
    f.fy(client_id, 2027)  # ends 2028-03-31, a leap year
    ends = [r[0].isoformat() for r in f.conn.execute("SELECT end_date FROM financial_years ORDER BY start_date")]
    assert ends == ["2027-03-31", "2028-03-31"]


@pytest.mark.parametrize(
    ("start", "end"),  # each end is start + 1 year - 1 day, so only the 1-April rule is broken
    [
        ("2026-01-01", "2026-12-31"),
        ("2026-04-02", "2027-04-01"),
        ("2026-05-01", "2027-04-30"),
        ("2026-03-31", "2027-03-30"),
    ],
)
def test_financial_year_must_start_on_1_april(f, start, end):
    client_id = f.client()
    with rejected(f.conn, constraint="financial_years_start_is_1_april"):
        f.conn.execute(
            "INSERT INTO financial_years (client_id, start_date, end_date) VALUES (%s, %s, %s)",
            (client_id, start, end),
        )


@pytest.mark.parametrize("end", ["2027-03-30", "2027-04-01", "2026-12-31", "2028-03-31"])
def test_financial_year_must_end_on_the_next_31_march(f, end):
    client_id = f.client()
    with rejected(f.conn, constraint="financial_years_end_is_start_plus_1y_minus_1d"):
        f.conn.execute(
            "INSERT INTO financial_years (client_id, start_date, end_date) VALUES (%s, '2026-04-01', %s)",
            (client_id, end),
        )


def test_client_cannot_have_the_same_financial_year_twice(f):
    client_id = f.client()
    f.fy(client_id, 2026)
    with rejected(f.conn, constraint="financial_years_client_start_key"):
        f.fy(client_id, 2026)


# =====================================================================================================
# Periods
# =====================================================================================================


def test_monthly_periods_that_touch_but_do_not_overlap_are_accepted(f):
    client_id, fy_id = f.setup()
    f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    f.period(client_id, fy_id, "2026-05-01", "2026-05-31")
    f.period(client_id, fy_id, "2027-03-01", "2027-03-31")
    assert count(f, "periods") == 3


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-04-30", "2026-05-15"),  # shares 30 April
        ("2026-04-10", "2026-04-20"),  # inside an existing period
        ("2026-03-31", "2026-04-01"),  # overlaps the first day (and starts outside the year)
        ("2026-04-01", "2026-06-30"),  # contains an existing period
    ],
)
def test_overlapping_periods_of_the_same_year_are_rejected(f, start, end):
    client_id, fy_id = f.setup()
    f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    f.period(client_id, fy_id, "2026-05-01", "2026-05-31")
    with rejected(f.conn):
        f.period(client_id, fy_id, start, end)


def test_period_overlap_message_names_the_problem(f):
    client_id, fy_id = f.setup()
    f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    with rejected(f.conn, message="overlaps another period"):
        f.period(client_id, fy_id, "2026-04-30", "2026-05-31")


def test_moving_a_period_onto_another_is_rejected(f):
    client_id, fy_id = f.setup()
    f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    may = f.period(client_id, fy_id, "2026-05-01", "2026-05-31")
    with rejected(f.conn, message="overlaps another period"):
        f.conn.execute("UPDATE periods SET period_start = '2026-04-15' WHERE id = %s", (may,))


def test_period_must_lie_inside_its_financial_year(f):
    client_id, fy_id = f.setup()
    with rejected(f.conn, message="is outside its financial year"):
        f.period(client_id, fy_id, "2027-03-15", "2027-04-15")


def test_period_with_the_same_start_as_another_is_rejected(f):
    client_id, fy_id = f.setup()
    f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    # an identical start date is caught by the overlap trigger before the unique key
    with rejected(f.conn):
        f.period(client_id, fy_id, "2026-04-01", "2026-04-10")


def test_period_end_cannot_be_before_start(f):
    client_id, fy_id = f.setup()
    with rejected(f.conn, constraint="periods_end_not_before_start"):
        f.period(client_id, fy_id, "2026-04-30", "2026-04-01")


def test_period_cannot_belong_to_another_clients_financial_year(f):
    a, b = f.client(), f.client()
    fy_of_a = f.fy(a)
    with rejected(f.conn, constraint="periods_financial_year_fk"):
        f.period(b, fy_of_a, "2026-04-01", "2026-04-30")


def test_period_can_be_locked_and_unlocked(f):
    client_id, fy_id = f.setup()
    pid = f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    f.conn.execute("UPDATE periods SET status = 'locked', locked_at = now(), locked_by = 'tester' WHERE id = %s", (pid,))
    f.conn.execute("UPDATE periods SET status = 'open' WHERE id = %s", (pid,))
    assert f.conn.execute("SELECT status FROM periods WHERE id = %s", (pid,)).fetchone()[0] == "open"


def test_period_status_is_checked(f):
    client_id, fy_id = f.setup()
    pid = f.period(client_id, fy_id, "2026-04-01", "2026-04-30")
    with rejected(f.conn, constraint="periods_status_check"):
        f.conn.execute("UPDATE periods SET status = 'closed' WHERE id = %s", (pid,))


# =====================================================================================================
# Opening balances
# =====================================================================================================


def test_opening_balance_one_side_only_and_not_negative(f):
    client_id, fy_id = f.setup()
    cash = f.ledger(client_id, "Cash", "cash_in_hand")
    insert = (
        "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) "
        "VALUES (%s, %s, %s, %s, %s)"
    )
    with rejected(f.conn, constraint="opening_balances_one_side"):
        f.conn.execute(insert, (client_id, cash, fy_id, "10.00", "5.00"))
    with rejected(f.conn, constraint="opening_balances_debit_nonneg"):
        f.conn.execute(insert, (client_id, cash, fy_id, "-1.00", "0.00"))
    with rejected(f.conn, constraint="opening_balances_credit_nonneg"):
        f.conn.execute(insert, (client_id, cash, fy_id, "0.00", "-1.00"))
    f.conn.execute(insert, (client_id, cash, fy_id, "10.00", "0.00"))
    assert count(f, "opening_balances") == 1


def test_opening_balance_is_unique_per_ledger_and_year(f):
    client_id, fy_id = f.setup()
    cash = f.ledger(client_id, "Cash", "cash_in_hand")
    insert = "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit) VALUES (%s, %s, %s, 1.00)"
    f.conn.execute(insert, (client_id, cash, fy_id))
    with rejected(f.conn, constraint="opening_balances_ledger_year_key"):
        f.conn.execute(insert, (client_id, cash, fy_id))


def test_opening_balance_cannot_use_another_clients_ledger_or_year(f):
    a_client, a_fy = f.setup()
    b_client, b_fy = f.setup()
    a_cash = f.ledger(a_client, "Cash", "cash_in_hand")
    insert = "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit) VALUES (%s, %s, %s, 1.00)"
    with rejected(f.conn, constraint="opening_balances_ledger_fk"):
        f.conn.execute(insert, (b_client, a_cash, b_fy))
    b_cash = f.ledger(b_client, "Cash", "cash_in_hand")
    with rejected(f.conn, constraint="opening_balances_financial_year_fk"):
        f.conn.execute(insert, (b_client, b_cash, a_fy))


# =====================================================================================================
# Voucher creation and the status path draft -> approved -> posted -> reversed
# =====================================================================================================


@pytest.mark.parametrize("status", ["approved", "posted", "reversed"])
def test_voucher_must_be_created_as_draft(f, status):
    client_id, fy_id = f.setup()
    with rejected(f.conn, message="must be created as draft"):
        f.conn.execute(
            "INSERT INTO vouchers (client_id, financial_year_id, voucher_type, voucher_date, narration, created_by, "
            "status) VALUES (%s, %s, 'journal', '2026-04-05', 'n', 'tester', %s)",
            (client_id, fy_id, status),
        )


def test_full_lifecycle_is_accepted(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "reversed")
    assert f.status(vid) == "reversed"
    assert count(f, "vouchers") == 2


def test_voucher_narration_cannot_be_blank_and_type_is_checked(f):
    client_id, fy_id = f.setup()
    with rejected(f.conn, constraint="vouchers_narration_not_blank"):
        f.draft(client_id, fy_id, [], narration="  ")
    with rejected(f.conn, constraint="vouchers_type_check"):
        f.draft(client_id, fy_id, [], vtype="expense")


@pytest.mark.parametrize("target", ["posted", "reversed"])
def test_draft_cannot_skip_to_posted_or_reversed(f, target):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    with rejected(f.conn, message="a draft voucher can only move to approved"):
        f.conn.execute("UPDATE vouchers SET status = %s WHERE id = %s", (target, vid))


def test_approved_voucher_can_only_move_to_draft_or_posted(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "approved")
    with rejected(f.conn, message="an approved voucher can only move to draft or posted"):
        f.conn.execute("UPDATE vouchers SET status = 'reversed' WHERE id = %s", (vid,))
    with rejected(f.conn, message="an approved voucher can only move to draft or posted"):
        f.conn.execute("UPDATE vouchers SET status = 'approved' WHERE id = %s", (vid,))


def test_approved_voucher_header_cannot_be_edited_in_place(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "approved")
    with rejected(f.conn, message="an approved voucher can only move to draft or posted"):
        f.conn.execute("UPDATE vouchers SET narration = 'edited' WHERE id = %s", (vid,))


def test_approved_voucher_goes_back_to_draft_and_can_then_be_edited(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "approved")
    f.conn.execute(
        "UPDATE vouchers SET status = 'draft', approved_by = NULL, approved_at = NULL WHERE id = %s", (vid,)
    )
    f.conn.execute("UPDATE vouchers SET narration = 'edited while draft' WHERE id = %s", (vid,))
    f.conn.execute("UPDATE voucher_lines SET debit = 150.00 WHERE voucher_id = %s AND line_no = 1", (vid,))
    f.conn.execute("UPDATE voucher_lines SET credit = 150.00 WHERE voucher_id = %s AND line_no = 2", (vid,))
    assert f.status(vid) == "draft"


def test_moving_back_to_draft_cannot_smuggle_in_other_changes(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "approved")
    with rejected(f.conn, message="back to draft can only change status and approval fields"):
        f.conn.execute("UPDATE vouchers SET status = 'draft', narration = 'sneaky' WHERE id = %s", (vid,))


def test_posting_can_only_change_status_number_and_posted_fields(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "approved")
    with rejected(f.conn, message="posting can only change status, voucher_number, posted_by and posted_at"):
        f.conn.execute(
            "UPDATE vouchers SET status = 'posted', voucher_number = 'JRN/2026-27/0001', narration = 'sneaky' "
            "WHERE id = %s",
            (vid,),
        )


@pytest.mark.parametrize("target", ["draft", "approved"])
def test_posted_voucher_cannot_go_back(f, target):
    client_id, fy_id, vid, lines = voucher_in_status(f, "posted")
    with rejected(f.conn, message="a posted voucher can only change to reversed"):
        f.conn.execute("UPDATE vouchers SET status = %s WHERE id = %s", (target, vid))


@pytest.mark.parametrize(
    "change",
    ["narration = 'edited'", "voucher_date = '2026-04-06'", "voucher_number = 'JRN/2026-27/9999'", "reference_no = 'x'"],
)
def test_posted_voucher_cannot_be_edited(f, change):
    client_id, fy_id, vid, lines = voucher_in_status(f, "posted")
    with rejected(f.conn, message="a posted voucher can only change to reversed"):
        f.conn.execute(f"UPDATE vouchers SET {change} WHERE id = %s", (vid,))


def test_posted_voucher_cannot_change_other_columns_together_with_the_reversal(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "posted")
    reversal = f.draft(client_id, fy_id, swapped(lines), narration="Reversal", reverses=vid)
    f.approve(reversal)
    f.post(reversal)
    check_deferred(f.conn)
    with rejected(f.conn, message="a posted voucher can only change status and reversed_by_voucher_id"):
        f.conn.execute(
            "UPDATE vouchers SET status = 'reversed', reversed_by_voucher_id = %s, narration = 'edited' WHERE id = %s",
            (reversal, vid),
        )


def test_reversed_voucher_is_immutable(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "reversed")
    for change in ("narration = 'edited'", "status = 'posted'", "status = 'draft'"):
        with rejected(f.conn, message="a reversed voucher cannot be changed"):
            f.conn.execute(f"UPDATE vouchers SET {change} WHERE id = %s", (vid,))


def test_voucher_id_and_client_id_cannot_change(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    other = f.client()
    with rejected(f.conn, message="id and client_id of a voucher cannot be changed"):
        f.conn.execute("UPDATE vouchers SET client_id = %s WHERE id = %s", (other, vid))


# ---- deleting vouchers -------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["approved", "posted", "reversed"])
def test_only_a_draft_voucher_can_be_deleted(f, status):
    client_id, fy_id, vid, lines = voucher_in_status(f, status)
    with rejected(f.conn, message="only a draft voucher can be deleted"):
        f.conn.execute("DELETE FROM vouchers WHERE id = %s", (vid,))


def test_draft_voucher_can_be_deleted_after_its_lines(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    f.conn.execute("DELETE FROM voucher_lines WHERE voucher_id = %s", (vid,))
    f.conn.execute("DELETE FROM vouchers WHERE id = %s", (vid,))
    assert count(f, "vouchers") == 0


def test_draft_voucher_with_lines_cannot_be_deleted_directly(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    with rejected(f.conn, constraint="voucher_lines_voucher_fk"):
        f.conn.execute("DELETE FROM vouchers WHERE id = %s", (vid,))


# ---- voucher lines: written only while the voucher is a draft -----------------------------------------


@pytest.mark.parametrize("status", ["approved", "posted", "reversed"])
def test_lines_cannot_be_inserted_updated_or_deleted_unless_the_voucher_is_draft(f, status):
    client_id, fy_id, vid, lines = voucher_in_status(f, status)
    ledger_id = lines[0][0]
    message = "voucher lines can only be changed while the voucher is draft"
    with rejected(f.conn, message=message):
        f.conn.execute(
            "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit) VALUES (%s, %s, 3, %s, 1.00)",
            (client_id, vid, ledger_id),
        )
    with rejected(f.conn, message=message):
        f.conn.execute("UPDATE voucher_lines SET debit = 999.00 WHERE voucher_id = %s AND line_no = 1", (vid,))
    with rejected(f.conn, message=message):
        f.conn.execute("DELETE FROM voucher_lines WHERE voucher_id = %s AND line_no = 1", (vid,))
    total = f.conn.execute("SELECT sum(debit) FROM voucher_lines WHERE voucher_id = %s", (vid,)).fetchone()[0]
    assert total == Decimal("100.00")  # unchanged by the rejected statements


def test_lines_can_be_inserted_updated_and_deleted_while_the_voucher_is_draft(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    ledger_id = lines[0][0]
    f.conn.execute(
        "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit) VALUES (%s, %s, 3, %s, 7.00)",
        (client_id, vid, ledger_id),
    )
    f.conn.execute("UPDATE voucher_lines SET debit = 8.00 WHERE voucher_id = %s AND line_no = 3", (vid,))
    f.conn.execute("DELETE FROM voucher_lines WHERE voucher_id = %s AND line_no = 3", (vid,))
    assert count(f, "voucher_lines") == 2


def test_a_line_cannot_be_moved_onto_a_posted_voucher(f):
    client_id, fy_id, posted_id, lines = voucher_in_status(f, "posted")
    draft_id = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    with rejected(f.conn, message="voucher lines can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE voucher_lines SET voucher_id = %s WHERE voucher_id = %s AND line_no = 1", (posted_id, draft_id))


# ---- voucher line values -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("debit", "credit", "constraint"),
    [
        ("10.00", "10.00", "voucher_lines_exactly_one_side"),
        ("0.00", "0.00", "voucher_lines_exactly_one_side"),
        ("-5.00", "0.00", "voucher_lines_debit_nonneg"),
        ("0.00", "-5.00", "voucher_lines_credit_nonneg"),
    ],
)
def test_voucher_line_needs_exactly_one_positive_side(f, debit, credit, constraint):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    with rejected(f.conn, constraint=constraint):
        f.conn.execute(
            "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit, credit) "
            "VALUES (%s, %s, 3, %s, %s, %s)",
            (client_id, vid, lines[0][0], debit, credit),
        )


def test_voucher_line_numbers_are_unique_and_positive(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "draft")
    insert = (
        "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit) VALUES (%s, %s, %s, %s, 1.00)"
    )
    with rejected(f.conn, constraint="voucher_lines_voucher_line_key"):
        f.conn.execute(insert, (client_id, vid, 1, lines[0][0]))
    with rejected(f.conn, constraint="voucher_lines_line_no_positive"):
        f.conn.execute(insert, (client_id, vid, 0, lines[0][0]))


# ---- posting checks (deferred until commit) ----------------------------------------------------------


def post_and_check(f, vid):
    f.approve(vid)
    f.post(vid)
    check_deferred(f.conn)


def test_balanced_voucher_posts(f):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    post_and_check(f, vid)
    assert f.status(vid) == "posted"


def test_unbalanced_voucher_cannot_be_posted(f):
    client_id, fy_id = f.setup()
    a = f.ledger(client_id, "Rent")
    b = f.ledger(client_id, "Cash", "cash_in_hand")
    vid = f.draft(client_id, fy_id, [(a, "10000.00", "0.00"), (b, "0.00", "9000.00")])
    with rejected(f.conn, message="is not balanced (debit 10000.00 vs credit 9000.00)"):
        post_and_check(f, vid)


def test_voucher_with_one_line_cannot_be_posted(f):
    client_id, fy_id = f.setup()
    a = f.ledger(client_id, "Rent")
    vid = f.draft(client_id, fy_id, [(a, "10.00", "0.00")])
    with rejected(f.conn, message="has 1 line(s); at least 2 are required"):
        post_and_check(f, vid)


def test_voucher_without_lines_cannot_be_posted(f):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, [])
    with rejected(f.conn, message="has 0 line(s); at least 2 are required"):
        post_and_check(f, vid)


@pytest.mark.parametrize("on", ["2026-03-31", "2027-04-01"])
def test_voucher_dated_outside_its_financial_year_cannot_be_posted(f, on):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id), on=on)
    with rejected(f.conn, message="is outside its financial year 2026-04-01 to 2027-03-31"):
        post_and_check(f, vid)


@pytest.mark.parametrize("on", ["2026-04-01", "2027-03-31"])
def test_voucher_dated_on_the_first_or_last_day_of_the_year_posts(f, on):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id), on=on)
    post_and_check(f, vid)
    assert f.status(vid) == "posted"


# ---- voucher numbers ---------------------------------------------------------------------------------


def test_posted_voucher_needs_a_number(f):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    f.approve(vid)
    with rejected(f.conn, constraint="vouchers_number_required_when_posted"):
        f.conn.execute("UPDATE vouchers SET status = 'posted' WHERE id = %s", (vid,))


def test_draft_and_approved_vouchers_must_not_have_a_number(f):
    client_id, fy_id = f.setup()
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    with rejected(f.conn, constraint="vouchers_no_number_before_posting"):
        f.conn.execute("UPDATE vouchers SET voucher_number = 'JRN/2026-27/0001' WHERE id = %s", (vid,))
    f.approve(vid)
    with rejected(f.conn):
        f.conn.execute("UPDATE vouchers SET voucher_number = 'JRN/2026-27/0001' WHERE id = %s", (vid,))


def test_voucher_number_is_unique_per_client_year_and_type(f):
    client_id, fy_id = f.setup()
    first = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    second = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    for vid in (first, second):
        f.approve(vid)
    f.post(first, "JRN/2026-27/0001")
    with rejected(f.conn, constraint="vouchers_number_key"):
        f.post(second, "JRN/2026-27/0001")


def test_same_number_is_allowed_for_another_type_or_another_client(f):
    client_id, fy_id = f.setup()
    other_client, other_fy = f.setup()
    journal = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    payment = f.draft(client_id, fy_id, f.balanced_lines(client_id), vtype="payment")
    theirs = f.draft(other_client, other_fy, f.balanced_lines(other_client))
    for vid in (journal, payment, theirs):
        f.approve(vid)
    f.post(journal, "X/2026-27/0001")
    f.post(payment, "X/2026-27/0001")
    f.post(theirs, "X/2026-27/0001")
    assert count(f, "vouchers WHERE status = 'posted'") == 3


# ---- reversal ----------------------------------------------------------------------------------------


def test_a_voucher_can_be_reversed_only_once(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "posted")
    f.reverse(client_id, fy_id, vid, lines)
    with rejected(f.conn, constraint="vouchers_reverses_once_key"):
        f.draft(client_id, fy_id, swapped(lines), narration="Second reversal", reverses=vid)


def test_original_can_be_marked_reversed_only_by_a_posted_reversal_that_reverses_it(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "posted")
    # 1) no reversal at all
    with rejected(f.conn, message="only by a posted reversal voucher that reverses it"):
        f.conn.execute("UPDATE vouchers SET status = 'reversed' WHERE id = %s", (vid,))
    # 2) a reversal that is still a draft
    reversal = f.draft(client_id, fy_id, swapped(lines), narration="Reversal", reverses=vid)
    with rejected(f.conn, message="only by a posted reversal voucher that reverses it"):
        f.conn.execute("UPDATE vouchers SET status = 'reversed', reversed_by_voucher_id = %s WHERE id = %s", (reversal, vid))
    # 3) a posted voucher that reverses a different voucher
    other = f.posted(client_id, fy_id)
    elsewhere = f.draft(client_id, fy_id, f.balanced_lines(client_id), narration="Not mine", reverses=other)
    f.approve(elsewhere)
    f.post(elsewhere)
    check_deferred(f.conn)
    with rejected(f.conn, message="only by a posted reversal voucher that reverses it"):
        f.conn.execute("UPDATE vouchers SET status = 'reversed', reversed_by_voucher_id = %s WHERE id = %s", (elsewhere, vid))
    assert f.status(vid) == "posted"


def test_a_reversed_voucher_always_carries_its_reversal_link(f):
    client_id, fy_id, vid, lines = voucher_in_status(f, "reversed")
    # the link and the status always go together
    row = f.conn.execute("SELECT status, reversed_by_voucher_id IS NOT NULL FROM vouchers WHERE id = %s", (vid,)).fetchone()
    assert row == ("reversed", True)


def test_a_reversal_voucher_cannot_reverse_another_clients_voucher(f):
    a_client, a_fy, a_vid, a_lines = voucher_in_status(f, "posted")
    b_client, b_fy = f.setup()
    with rejected(f.conn, constraint="vouchers_reverses_fk"):
        f.draft(b_client, b_fy, f.balanced_lines(b_client), narration="Cross-client", reverses=a_vid)


# ---- client isolation: composite foreign keys --------------------------------------------------------


def test_voucher_line_cannot_use_another_clients_ledger(f):
    a_client, a_fy = f.setup()
    b_client = f.client()
    b_ledger = f.ledger(b_client, "Their cash", "cash_in_hand")
    mine = f.ledger(a_client, "My rent")
    vid = f.draft(a_client, a_fy, [(mine, "10.00", "0.00")])
    with rejected(f.conn, constraint="voucher_lines_ledger_fk"):
        f.conn.execute(
            "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, credit) VALUES (%s, %s, 2, %s, 10.00)",
            (a_client, vid, b_ledger),
        )


def test_voucher_line_cannot_attach_to_another_clients_voucher(f):
    a_client, a_fy = f.setup()
    b_client, b_fy = f.setup()
    b_voucher = f.draft(b_client, b_fy, f.balanced_lines(b_client))
    mine = f.ledger(a_client, "My rent")
    with rejected(f.conn, constraint="voucher_lines_voucher_fk"):
        f.conn.execute(
            "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit) VALUES (%s, %s, 3, %s, 1.00)",
            (a_client, b_voucher, mine),
        )


def test_voucher_party_ledger_must_belong_to_the_same_client(f):
    a_client, a_fy = f.setup()
    b_client = f.client()
    theirs = f.ledger(b_client, "Their debtor", "sundry_debtors")
    mine = f.ledger(a_client, "My debtor", "sundry_debtors")
    insert = (
        "INSERT INTO vouchers (client_id, financial_year_id, voucher_type, voucher_date, narration, created_by, "
        "party_ledger_id) VALUES (%s, %s, 'sales', '2026-04-05', 'n', 'tester', %s)"
    )
    with rejected(f.conn, constraint="vouchers_party_ledger_fk"):
        f.conn.execute(insert, (a_client, a_fy, theirs))
    f.conn.execute(insert, (a_client, a_fy, mine))
    assert count(f, "vouchers") == 1


def test_voucher_cannot_use_another_clients_financial_year(f):
    a_client, a_fy = f.setup()
    b_client, b_fy = f.setup()
    with rejected(f.conn, constraint="vouchers_financial_year_fk"):
        f.draft(a_client, b_fy, [])


# =====================================================================================================
# Voucher number sequences
# =====================================================================================================


def test_sequence_counts_up_one_at_a_time(f):
    client_id, fy_id = f.setup()
    f.conn.execute(
        "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type, last_number) "
        "VALUES (%s, %s, 'sales', 1)",
        (client_id, fy_id),
    )
    for expected in (2, 3):
        f.conn.execute(
            "UPDATE voucher_number_sequences SET last_number = last_number + 1 WHERE client_id = %s", (client_id,)
        )
        got = f.conn.execute("SELECT last_number FROM voucher_number_sequences").fetchone()[0]
        assert got == expected


@pytest.mark.parametrize("new_value", [5, 3, 2, 0])  # skip ahead, repeat, go back, reset (4 would be legal)
def test_sequence_cannot_skip_repeat_or_go_back(f, new_value):
    client_id, fy_id = f.setup()
    # a sequence may only start at 0 or 1, so count up to 3 one step at a time
    f.conn.execute(
        "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type) VALUES (%s, %s, 'sales')",
        (client_id, fy_id),
    )
    for _ in range(3):
        f.conn.execute("UPDATE voucher_number_sequences SET last_number = last_number + 1")
    with rejected(f.conn, message="voucher numbers are issued one at a time"):
        f.conn.execute("UPDATE voucher_number_sequences SET last_number = %s", (new_value,))
    assert f.conn.execute("SELECT last_number FROM voucher_number_sequences").fetchone()[0] == 3


def test_sequence_cannot_start_above_one_or_be_deleted(f):
    client_id, fy_id = f.setup()
    with rejected(f.conn, message="must start at 0 or 1 (got 5)"):
        f.conn.execute(
            "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type, last_number) "
            "VALUES (%s, %s, 'sales', 5)",
            (client_id, fy_id),
        )
    f.conn.execute(
        "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type) VALUES (%s, %s, 'sales')",
        (client_id, fy_id),
    )
    with rejected(f.conn, message="voucher number sequences cannot be deleted"):
        f.conn.execute("DELETE FROM voucher_number_sequences")


def test_sequence_is_one_row_per_client_year_and_type_and_checks_the_type(f):
    client_id, fy_id = f.setup()
    insert = "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type) VALUES (%s, %s, %s)"
    f.conn.execute(insert, (client_id, fy_id, "sales"))
    f.conn.execute(insert, (client_id, fy_id, "purchase"))
    with rejected(f.conn, constraint="voucher_number_sequences_pkey"):
        f.conn.execute(insert, (client_id, fy_id, "sales"))
    with rejected(f.conn, constraint="voucher_number_sequences_type_check"):
        f.conn.execute(insert, (client_id, fy_id, "expense"))


def test_sequence_cannot_use_another_clients_financial_year(f):
    a_client, a_fy = f.setup()
    b_client, b_fy = f.setup()
    with rejected(f.conn, constraint="voucher_number_sequences_financial_year_fk"):
        f.conn.execute(
            "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type) VALUES (%s, %s, 'sales')",
            (a_client, b_fy),
        )


# =====================================================================================================
# Audit log: append only
# =====================================================================================================


def add_audit(f, client_id):
    return f.conn.execute(
        "INSERT INTO audit_log (client_id, actor, action, entity, entity_id, new_data) "
        "VALUES (%s, 'tester', 'create', 'client', %s, '{\"name\": \"x\"}') RETURNING id",
        (client_id, client_id),
    ).fetchone()[0]


def test_audit_log_accepts_new_rows(f):
    client_id = f.client()
    first, second = add_audit(f, client_id), add_audit(f, client_id)
    assert second == first + 1
    assert count(f, "audit_log") == 2


def test_audit_log_rows_cannot_be_updated(f):
    client_id = f.client()
    row_id = add_audit(f, client_id)
    with rejected(f.conn, message="audit_log is append-only"):
        f.conn.execute("UPDATE audit_log SET actor = 'someone else' WHERE id = %s", (row_id,))


def test_audit_log_rows_cannot_be_deleted(f):
    client_id = f.client()
    row_id = add_audit(f, client_id)
    with rejected(f.conn, message="audit_log is append-only"):
        f.conn.execute("DELETE FROM audit_log WHERE id = %s", (row_id,))
    with rejected(f.conn, message="audit_log is append-only"):
        f.conn.execute("DELETE FROM audit_log")
    assert count(f, "audit_log") == 1


def test_audit_log_needs_an_actor_and_an_existing_client(f):
    client_id = f.client()
    with rejected(f.conn, constraint="audit_log_actor_not_blank"):
        f.conn.execute(
            "INSERT INTO audit_log (client_id, actor, action, entity, entity_id) VALUES (%s, ' ', 'a', 'e', %s)",
            (client_id, client_id),
        )
    with rejected(f.conn, constraint="audit_log_client_id_fkey"):
        f.conn.execute(
            "INSERT INTO audit_log (client_id, actor, action, entity, entity_id) "
            "VALUES (gen_random_uuid(), 'tester', 'a', 'e', gen_random_uuid())"
        )


# =====================================================================================================
# Test infrastructure: cleanup works on the protected tables, and only there
# =====================================================================================================


def test_guarded_cleanup_empties_protected_tables_and_the_seed_is_restored(f):
    """TRUNCATE is not blocked by the row-level guards, so the guarded cleanup can reset the protected tables."""
    client_id, fy_id, vid, lines = voucher_in_status(f, "reversed")
    add_audit(f, client_id)
    f.conn.commit()  # cleanup works on committed data; this test cleans up after itself below

    emptied = connection.clean_test_tables(f.conn)
    assert "vouchers" in emptied and "audit_log" in emptied and "schema_migrations" not in emptied
    for table in ("clients", "vouchers", "voucher_lines", "audit_log", "ledgers", "account_groups"):
        assert count(f, table) == 0
    migrate.apply_seed_sql(f.conn)
    assert count(f, "account_groups") == 23
    names = [r[0] for r in f.conn.execute("SELECT filename FROM schema_migrations ORDER BY filename")]
    assert "0003_accounting_core.sql" in names  # the migrations table was left alone
