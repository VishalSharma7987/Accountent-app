"""Step 1.6: period lock/unlock and the reports services, on the Step 1.3 mini case loaded through the services
(create -> approve -> post). The expected numbers are the hand-calculated ones of PHASE_PROMPTS step 1.3.

Opening:  Cash 50,000 Dr | HDFC Bank 3,00,000 Dr | Opening Stock 1,00,000 Dr | Owner Capital 4,50,000 Cr
1) 02-04 Payment  Rent Dr 20,000 / Cash Cr          5) 12-04 Payment  Sharma Dr 15,000 / Bank Cr
2) 03-04 Purchase Purchases Dr 50,000 / Sharma Cr    6) 15-04 Contra   Bank Dr 10,000 / Cash Cr
3) 05-04 Sales    Rahul Dr 80,000 / Sales Cr         7) 20-04 Payment  Drawings Dr 5,000 / Cash Cr
4) 10-04 Receipt  Bank Dr 30,000 / Rahul Cr
Closing:  Cash 15,000 Dr | Bank 3,25,000 Dr | Stock 1,00,000 Dr | Rahul 50,000 Dr | Sharma 35,000 Cr |
          Capital 4,50,000 Cr | Drawings 5,000 Dr | Rent 20,000 Dr | Purchases 50,000 Dr | Sales 80,000 Cr
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db import connection, migrate
from app.engine.models import Balance, VoucherDraft, VoucherLine
from app.services import client_setup, periods, reports, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

D = Decimal


@dataclass
class Books:
    client_id: object
    fy_id: object
    ids: dict
    period_ids: dict  # "2026-04" -> period id
    voucher_ids: dict  # "v1" -> voucher id


def build_books(conn, name="ABC Traders") -> Books:
    created = client_setup.create_client(
        conn, ClientProfile(name, "proprietorship", "trading", "regular"),
        fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
    )
    ids = dict(created.ledger_ids)
    for ledger, group in (("HDFC Bank", "bank_accounts"), ("Rahul Enterprises", "sundry_debtors"),
                          ("Sharma Suppliers", "sundry_creditors")):
        ids[ledger] = client_setup.add_ledger(conn, created.client_id, ledger, group, actor="setup")
    for ledger, debit, credit in (("Cash", "50000", None), ("HDFC Bank", "300000", None),
                                  ("Opening Stock", "100000", None), ("Owner Capital A/c", None, "450000")):
        client_setup.set_opening_balance(conn, created.client_id, created.financial_year_id, ids[ledger],
                                         debit, credit, actor="setup")
    period_ids = {
        start.strftime("%Y-%m"): pid for pid, start in conn.execute(
            text("SELECT id, period_start FROM periods WHERE financial_year_id = :fy"), {"fy": created.financial_year_id})
    }
    return Books(created.client_id, created.financial_year_id, ids, period_ids, {})


def draft(b, vtype, on, narration, lines, reference_no=None, party=None):
    return VoucherDraft(b.client_id, vtype, on, narration, reference_no, b.ids[party] if party else None,
                        tuple(VoucherLine(b.ids[n], dr, cr) for n, dr, cr in lines))


def mini_case(b):
    return {
        "v1": draft(b, "payment", date(2026, 4, 2), "April rent", [("Rent", "20000", None), ("Cash", None, "20000")]),
        "v2": draft(b, "purchase", date(2026, 4, 3), "Goods from Sharma", [("Purchases", "50000", None), ("Sharma Suppliers", None, "50000")], "SUP/889", "Sharma Suppliers"),
        "v3": draft(b, "sales", date(2026, 4, 5), "Goods to Rahul", [("Rahul Enterprises", "80000", None), ("Sales", None, "80000")], None, "Rahul Enterprises"),
        "v4": draft(b, "receipt", date(2026, 4, 10), "Received from Rahul", [("HDFC Bank", "30000", None), ("Rahul Enterprises", None, "30000")], None, "Rahul Enterprises"),
        "v5": draft(b, "payment", date(2026, 4, 12), "Paid Sharma", [("Sharma Suppliers", "15000", None), ("HDFC Bank", None, "15000")]),
        "v6": draft(b, "contra", date(2026, 4, 15), "Cash deposited", [("HDFC Bank", "10000", None), ("Cash", None, "10000")]),
        "v7": draft(b, "payment", date(2026, 4, 20), "Owner withdrew cash", [("Drawings A/c", "5000", None), ("Cash", None, "5000")]),
    }


@pytest.fixture(scope="module")
def books(test_engine, test_conn):
    """The mini case, committed ONCE for the module (two clients); each test runs in a rolled-back transaction."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        mine = build_books(conn)
        for key, d in mini_case(mine).items():
            result = vouchers.create_draft(conn, d, actor="clerk")
            assert result.errors == [], (key, result.errors)
            vouchers.approve(conn, result.voucher_id, actor="partner")
            vouchers.post(conn, result.voucher_id, actor="partner")
            mine.voucher_ids[key] = result.voucher_id
        other = build_books(conn, "Other Client")
    yield mine, other
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def b(books):
    return books[0]


@pytest.fixture
def other(books):
    return books[1]


def dr(amount):
    return Balance(D(amount), "Dr")


def cr(amount):
    return Balance(D(amount), "Cr")


NIL = Balance(D("0.00"), None)
EXPECTED_CLOSING = {
    "Cash": (D("15000.00"), D("0.00")),
    "HDFC Bank": (D("325000.00"), D("0.00")),
    "Opening Stock": (D("100000.00"), D("0.00")),
    "Rahul Enterprises": (D("50000.00"), D("0.00")),
    "Sharma Suppliers": (D("0.00"), D("35000.00")),
    "Owner Capital A/c": (D("0.00"), D("450000.00")),
    "Drawings A/c": (D("5000.00"), D("0.00")),
    "Rent": (D("20000.00"), D("0.00")),
    "Purchases": (D("50000.00"), D("0.00")),
    "Sales": (D("0.00"), D("80000.00")),
}


def closing(result):
    return {r.ledger_name: (r.debit, r.credit) for s in result.sections for r in s.rows}


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


# ===================================================================================== the mini case, loaded


def test_the_mini_case_vouchers_were_numbered_by_posting(svc_conn, b):
    numbers = {k: scalar(svc_conn, "SELECT voucher_number FROM vouchers WHERE id = :id", id=v) for k, v in b.voucher_ids.items()}
    assert numbers == {
        "v1": "PAY/2026-27/0001", "v2": "PUR/2026-27/0001", "v3": "SAL/2026-27/0001", "v4": "REC/2026-27/0001",
        "v5": "PAY/2026-27/0002", "v6": "CON/2026-27/0001", "v7": "PAY/2026-27/0003",
    }


# =================================================================================================== trial balance


def test_trial_balance_of_the_mini_case_matches_the_hand_calculation(svc_conn, b):
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30), hide_zero=True)
    assert closing(result) == EXPECTED_CLOSING
    assert (result.total_debit, result.total_credit) == (D("565000.00"), D("565000.00"))
    assert result.difference == NIL and result.is_balanced is True


def test_trial_balance_group_subtotals_by_hand(svc_conn, b):
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30), hide_zero=True)
    assert [(s.group_name, s.debit, s.credit) for s in result.sections] == [
        ("Capital Account", D("5000.00"), D("450000.00")),
        ("Current Liabilities", D("0.00"), D("35000.00")),
        ("Current Assets", D("490000.00"), D("0.00")),
        ("Sales Accounts", D("0.00"), D("80000.00")),
        ("Purchase Accounts", D("50000.00"), D("0.00")),
        ("Indirect Expenses", D("20000.00"), D("0.00")),
    ]


def test_trial_balance_lists_nil_ledgers_unless_told_to_hide_them(svc_conn, b):
    everything = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30))
    assert len(closing(everything)) == 21  # 18 template ledgers + HDFC Bank, Rahul, Sharma
    assert closing(everything)["Telephone & Internet"] == (D("0.00"), D("0.00"))


def test_trial_balance_as_on_10_april_counts_only_vouchers_up_to_that_date(svc_conn, b):
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 10), hide_zero=True)
    assert (result.total_debit, result.total_credit) == (D("580000.00"), D("580000.00"))
    assert closing(result)["Cash"] == (D("30000.00"), D("0.00"))
    assert closing(result)["HDFC Bank"] == (D("330000.00"), D("0.00"))
    assert "Drawings A/c" not in closing(result)


def test_trial_balance_before_the_first_voucher_shows_the_openings(svc_conn, b):
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 1), hide_zero=True)
    assert (result.total_debit, result.total_credit) == (D("450000.00"), D("450000.00"))


def test_trial_balance_ignores_draft_and_approved_vouchers(svc_conn, b):
    d = draft(b, "payment", date(2026, 4, 22), "Not posted", [("Rent", "999", None), ("Cash", None, "999")])
    draft_id = vouchers.create_draft(svc_conn, d, actor="clerk").voucher_id
    approved_id = vouchers.create_draft(svc_conn, draft(b, "payment", date(2026, 4, 23), "Approved only", [("Rent", "888", None), ("Cash", None, "888")]), actor="clerk").voucher_id
    vouchers.approve(svc_conn, approved_id, actor="partner")
    assert draft_id and closing(reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30), hide_zero=True)) == EXPECTED_CLOSING


def test_reversing_voucher_1_leaves_cash_at_35000_and_rent_at_nil(svc_conn, b):
    vouchers.reverse(svc_conn, b.voucher_ids["v1"], date(2026, 4, 25), "wrong month", actor="partner")
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30))
    assert closing(result)["Cash"] == (D("35000.00"), D("0.00"))
    assert closing(result)["Rent"] == (D("0.00"), D("0.00"))
    assert (result.total_debit, result.total_credit) == (D("565000.00"), D("565000.00"))


def test_trial_balance_never_hides_a_difference(svc_conn, b):
    # the service refuses to change openings after posting, so insert one straight into the table
    svc_conn.execute(text("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit) VALUES (:c, :l, :fy, 1000)"),
                     {"c": b.client_id, "l": b.ids["Salary"], "fy": b.fy_id})
    result = reports.trial_balance(svc_conn, b.client_id, date(2026, 4, 30))
    assert (result.total_debit, result.total_credit) == (D("566000.00"), D("565000.00"))
    assert result.difference == dr("1000.00") and result.is_balanced is False


def test_trial_balance_of_another_client_is_separate(svc_conn, b, other):
    result = reports.trial_balance(svc_conn, other.client_id, date(2026, 4, 30), hide_zero=True)
    assert closing(result) == {"Cash": (D("50000.00"), D("0.00")), "HDFC Bank": (D("300000.00"), D("0.00")),
                               "Opening Stock": (D("100000.00"), D("0.00")), "Owner Capital A/c": (D("0.00"), D("450000.00"))}


def test_trial_balance_for_a_date_in_no_financial_year_is_refused(svc_conn, b):
    with pytest.raises(ServiceError) as info:
        reports.trial_balance(svc_conn, b.client_id, date(2027, 4, 1))
    assert (info.value.code, info.value.message) == ("no_financial_year", "No financial year of this client contains 01-04-2027.")
    with pytest.raises(ServiceError) as info:
        reports.trial_balance(svc_conn, "00000000-0000-0000-0000-000000000000", date(2026, 4, 30))
    assert info.value.code == "not_found"


# ================================================================================================ ledger statement


def statement_rows(result):
    return [(r.kind, r.date, r.voucher_number, r.particulars, r.debit, r.credit, r.balance) for r in result.rows]


def test_cash_statement_of_the_mini_case_by_hand(svc_conn, b):
    result = reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2026, 4, 1), date(2026, 4, 30))
    assert statement_rows(result) == [
        ("opening", date(2026, 4, 1), None, "Opening Balance", D("50000.00"), D("0.00"), dr("50000.00")),
        ("entry", date(2026, 4, 2), "PAY/2026-27/0001", "By Rent", D("0.00"), D("20000.00"), dr("30000.00")),
        ("entry", date(2026, 4, 15), "CON/2026-27/0001", "By HDFC Bank", D("0.00"), D("10000.00"), dr("20000.00")),
        ("entry", date(2026, 4, 20), "PAY/2026-27/0003", "By Drawings A/c", D("0.00"), D("5000.00"), dr("15000.00")),
        ("closing", date(2026, 4, 30), None, "Closing Balance", D("0.00"), D("0.00"), dr("15000.00")),
    ]
    assert (result.opening, result.closing) == (dr("50000.00"), dr("15000.00"))


def test_bank_statement_of_the_mini_case_by_hand(svc_conn, b):
    result = reports.ledger_statement(svc_conn, b.client_id, b.ids["HDFC Bank"], date(2026, 4, 1), date(2026, 4, 30))
    assert [(r.voucher_number, r.particulars, r.debit, r.credit, r.balance) for r in result.rows if r.kind == "entry"] == [
        ("REC/2026-27/0001", "To Rahul Enterprises", D("30000.00"), D("0.00"), dr("330000.00")),
        ("PAY/2026-27/0002", "By Sharma Suppliers", D("0.00"), D("15000.00"), dr("315000.00")),
        ("CON/2026-27/0001", "To Cash", D("10000.00"), D("0.00"), dr("325000.00")),
    ]


def test_creditor_statement_runs_on_the_credit_side(svc_conn, b):
    result = reports.ledger_statement(svc_conn, b.client_id, b.ids["Sharma Suppliers"], date(2026, 4, 1), date(2026, 4, 30))
    assert [r.balance for r in result.rows] == [NIL, cr("50000.00"), cr("35000.00"), cr("35000.00")]


def test_statement_from_a_later_date_folds_earlier_entries_into_the_opening_row(svc_conn, b):
    result = reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2026, 4, 10), date(2026, 4, 30))
    assert result.opening == dr("30000.00") and result.closing == dr("15000.00")
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == ["CON/2026-27/0001", "PAY/2026-27/0003"]


def test_statement_after_a_reversal_shows_both_vouchers(svc_conn, b):
    vouchers.reverse(svc_conn, b.voucher_ids["v1"], date(2026, 4, 25), "wrong month", actor="partner")
    result = reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2026, 4, 1), date(2026, 4, 30))
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == [
        "PAY/2026-27/0001", "CON/2026-27/0001", "PAY/2026-27/0003", "PAY/2026-27/0004"]
    assert result.closing == dr("35000.00")


def test_statement_refuses_bad_ranges_and_foreign_ledgers(svc_conn, b, other):
    with pytest.raises(ServiceError) as info:
        reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2026, 4, 30), date(2026, 4, 1))
    assert info.value.code == "invalid_range"
    with pytest.raises(ServiceError) as info:
        reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2026, 4, 1), date(2027, 4, 30))
    assert info.value.code == "invalid_range" and "01-04-2026 to 31-03-2027" in info.value.message
    with pytest.raises(ServiceError) as info:
        reports.ledger_statement(svc_conn, b.client_id, other.ids["Cash"], date(2026, 4, 1), date(2026, 4, 30))
    assert (info.value.code, info.value.message) == ("not_found", "Ledger not found for this client.")
    with pytest.raises(ServiceError) as info:
        reports.ledger_statement(svc_conn, b.client_id, b.ids["Cash"], date(2030, 4, 1), date(2030, 4, 30))
    assert info.value.code == "no_financial_year"


# ================================================================================================ lock / unlock


def draft_in(b, on, amount="100", narration="Test"):
    return draft(b, "payment", on, narration, [("Rent", amount, None), ("Cash", None, amount)])


def test_lock_period_locks_a_period_that_has_only_posted_vouchers_and_logs_it(svc_conn, b):
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-04"], actor="partner")
    assert svc_conn.execute(text("SELECT status, locked_by, locked_at IS NOT NULL FROM periods WHERE id = :id"),
                            {"id": b.period_ids["2026-04"]}).one() == ("locked", "partner", True)
    action, actor, old, new = svc_conn.execute(
        text("SELECT action, actor, old_data, new_data FROM audit_log WHERE entity_id = :id ORDER BY id DESC LIMIT 1"),
        {"id": b.period_ids["2026-04"]}).one()
    assert (action, actor, old, new) == ("lock", "partner", {"status": "open"}, {"status": "locked", "locked_by": "partner"})


def test_a_locked_period_refuses_new_vouchers_dated_in_it(svc_conn, b):
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-04"], actor="partner")
    result = vouchers.create_draft(svc_conn, draft_in(b, date(2026, 4, 28)), actor="clerk")
    assert [(e.rule_id, e.message) for e in result.errors] == [("V-07", "The period 01-04-2026 to 30-04-2026 is locked.")]
    assert vouchers.create_draft(svc_conn, draft_in(b, date(2026, 5, 2)), actor="clerk").errors == []  # May is still open


def test_lock_period_is_refused_while_draft_or_approved_vouchers_are_dated_in_it_and_lists_them(svc_conn, b):
    first = vouchers.create_draft(svc_conn, draft_in(b, date(2026, 5, 4), narration="May draft"), actor="clerk").voucher_id
    second = vouchers.create_draft(svc_conn, draft_in(b, date(2026, 5, 9), amount="200", narration="May approved"), actor="clerk").voucher_id
    vouchers.approve(svc_conn, second, actor="partner")
    with pytest.raises(ServiceError) as info:
        periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-05"], actor="partner")
    assert info.value.code == "period_has_open_vouchers"
    assert info.value.message == (
        "The period 01-05-2026 to 31-05-2026 cannot be locked: 2 draft or approved voucher(s) are dated in it "
        "(draft 04-05-2026 'May draft'; approved 09-05-2026 'May approved'). Post, delete or re-date them first."
    )
    assert [(x["voucher_id"], x["status"], x["voucher_date"], x["narration"]) for x in info.value.details] == [
        (first, "draft", date(2026, 5, 4), "May draft"), (second, "approved", date(2026, 5, 9), "May approved")]
    assert scalar(svc_conn, "SELECT status FROM periods WHERE id = :id", id=b.period_ids["2026-05"]) == "open"
    vouchers.delete_draft(svc_conn, first, actor="clerk")
    vouchers.post(svc_conn, second, actor="partner")
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-05"], actor="partner")


def test_lock_period_twice_and_unknown_or_foreign_periods(svc_conn, b, other):
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-06"], actor="partner")
    with pytest.raises(ServiceError) as info:
        periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-06"], actor="partner")
    assert (info.value.code, info.value.message) == ("already_locked", "The period 01-06-2026 to 30-06-2026 is already locked.")
    with pytest.raises(ServiceError) as info:
        periods.lock_period(svc_conn, b.client_id, other.period_ids["2026-06"], actor="partner")
    assert (info.value.code, info.value.message) == ("not_found", "Period not found for this client.")
    with pytest.raises(ServiceError) as info:
        periods.lock_period(svc_conn, b.client_id, "not-a-uuid", actor="partner")
    assert info.value.code == "not_found"


def test_unlock_period_needs_a_reason_logs_it_and_reopens_the_period(svc_conn, b):
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-04"], actor="partner")
    with pytest.raises(ServiceError) as info:
        periods.unlock_period(svc_conn, b.client_id, b.period_ids["2026-04"], "  ", actor="partner")
    assert (info.value.code, info.value.message) == ("reason_required", "A reason is required to unlock a period.")
    assert scalar(svc_conn, "SELECT status FROM periods WHERE id = :id", id=b.period_ids["2026-04"]) == "locked"

    periods.unlock_period(svc_conn, b.client_id, b.period_ids["2026-04"], "Auditor asked for a correction", actor="senior")
    assert svc_conn.execute(text("SELECT status, locked_by, locked_at FROM periods WHERE id = :id"),
                            {"id": b.period_ids["2026-04"]}).one() == ("open", None, None)
    action, actor, old, new = svc_conn.execute(
        text("SELECT action, actor, old_data, new_data FROM audit_log WHERE entity_id = :id ORDER BY id DESC LIMIT 1"),
        {"id": b.period_ids["2026-04"]}).one()
    assert (action, actor, old) == ("unlock", "senior", {"status": "locked", "locked_by": "partner"})
    assert new == {"status": "open", "reason": "Auditor asked for a correction"}
    assert vouchers.create_draft(svc_conn, draft_in(b, date(2026, 4, 28)), actor="clerk").errors == []


def test_unlock_a_period_that_is_not_locked_and_lock_unlock_need_an_actor(svc_conn, b):
    with pytest.raises(ServiceError) as info:
        periods.unlock_period(svc_conn, b.client_id, b.period_ids["2026-07"], "why not", actor="partner")
    assert (info.value.code, info.value.message) == ("not_locked", "The period 01-07-2026 to 31-07-2026 is not locked.")
    for call in (lambda: periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-07"], actor=" "),
                 lambda: periods.unlock_period(svc_conn, b.client_id, b.period_ids["2026-07"], "r", actor="")):
        with pytest.raises(ServiceError) as info:
            call()
        assert info.value.code == "invalid_actor"


def test_list_periods_returns_the_twelve_months_in_order_with_their_status(svc_conn, b):
    periods.lock_period(svc_conn, b.client_id, b.period_ids["2026-04"], actor="partner")
    rows = periods.list_periods(svc_conn, b.client_id, b.fy_id)
    assert [(p.start, p.end, p.status) for p in rows][:3] == [
        (date(2026, 4, 1), date(2026, 4, 30), "locked"), (date(2026, 5, 1), date(2026, 5, 31), "open"),
        (date(2026, 6, 1), date(2026, 6, 30), "open")]
    assert len(rows) == 12 and rows[-1].end == date(2027, 3, 31)
    assert len(periods.list_periods(svc_conn, b.client_id)) == 12
