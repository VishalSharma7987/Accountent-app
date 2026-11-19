"""Step 6.0: the Phase 6 tables of migration 0017 and seeds 0012 / 0013 (database guards hold).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_final_accounts_schema.py`.

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import uuid

import pytest
from dbfactory import Factory, rejected

pytestmark = pytest.mark.integration


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def _asset(f, client_id, no="A-1", **kw):
    ledger = f.ledger(client_id, f"Furniture {no}", "fixed_assets")
    aid = uuid.uuid4()
    cols = {"it_block_key": "furniture_fittings", "sched2_class_key": "furniture_fittings", "useful_life_years": "10",
            "book_method": "slm", **kw}
    f.conn.execute(
        "INSERT INTO fixed_assets (id, client_id, asset_no, name, asset_ledger_id, it_block_key, sched2_class_key, "
        "useful_life_years, life_override_reason, book_method, is_depreciable, created_by) "
        "VALUES (%s, %s, %s, 'Chair', %s, %s, %s, %s, %s, %s, %s, 'tester')",
        (aid, client_id, no, ledger, cols["it_block_key"], cols["sched2_class_key"], cols["useful_life_years"],
         cols.get("life_override_reason"), cols["book_method"], cols.get("is_depreciable", True)))
    return aid


def _event(f, client_id, asset_id, kind, on, use=None, amount="1000.00"):
    f.conn.execute(
        "INSERT INTO fixed_asset_events (client_id, asset_id, kind, event_date, put_to_use_date, amount, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'tester')", (client_id, asset_id, kind, on, use, amount))


def test_F00_seeds_are_loaded_and_no_legal_value_claims_to_be_verified(f):
    c = f.conn
    assert c.execute("SELECT count(*) FROM dep_it_block_rates").fetchone()[0] == 20
    assert c.execute("SELECT count(*) FROM dep_sched2_classes").fetchone()[0] == 13
    assert c.execute("SELECT count(*) FROM fs_lines").fetchone()[0] == 33
    assert c.execute("SELECT count(*) FROM fs_group_map").fetchone()[0] == 18
    assert c.execute("SELECT rule_value FROM dep_it_rules WHERE rule_key = 'half_rate_days' AND act = 'it_act_1961'").fetchone()[0] == 180
    for table in ("dep_it_block_rates", "dep_it_rules", "dep_sched2_classes", "fs_lines", "fs_group_map"):
        assert c.execute(f"SELECT count(*) FROM {table} WHERE verification_status = 'verified'").fetchone()[0] == 0, table
    # every 2025-Act depreciation row is pending (section numbers of the 2025 Act are not verified)
    assert c.execute("SELECT count(*) FROM dep_it_block_rates WHERE act = 'it_act_2025' AND verification_status <> 'pending'").fetchone()[0] == 0


def test_F01_money_and_rates_are_rejected_not_rounded(f):
    client_id, fy_id = f.setup()
    cap = f.ledger(client_id, "A Capital", "capital_account")
    pid = uuid.uuid4()
    f.conn.execute("INSERT INTO partners (id, client_id, name, capital_ledger_id) VALUES (%s, %s, 'A', %s)", (pid, client_id, cap))
    insert = ("INSERT INTO partner_fy_terms (partner_id, client_id, financial_year_id, profit_share_percent, remuneration_annual, "
              "interest_on_capital_rate, deed_reference, set_by) VALUES (%s, %s, %s, %s, %s, %s, 'Deed cl. 7', 't')")
    with rejected(f.conn, constraint="partner_fy_terms_rem_two_decimals"):
        f.conn.execute(insert, (pid, client_id, fy_id, "60", "1000.005", "10"))
    with rejected(f.conn, constraint="partner_fy_terms_ioc_four_decimals"):
        f.conn.execute(insert, (pid, client_id, fy_id, "60", "1000.00", "12.34567"))
    with rejected(f.conn, constraint="partner_fy_terms_share_range"):
        f.conn.execute(insert, (pid, client_id, fy_id, "100.5", "1000.00", "10"))
    f.conn.execute(insert, (pid, client_id, fy_id, "33.3333", "1000.00", "12.5"))
    with rejected(f.conn, constraint="partner_fy_terms_deed_needed"):
        f.conn.execute("INSERT INTO partner_fy_terms (partner_id, client_id, financial_year_id, profit_share_percent, "
                       "remuneration_annual, set_by) VALUES (%s, %s, %s, 10, 5.00, 't')",
                       (pid, client_id, f.fy(client_id, 2027)))
    with rejected(f.conn, message='violates check constraint "final_closing_stock_c'):
        f.conn.execute("INSERT INTO final_closing_stock (client_id, financial_year_id, as_on_date, source, cost_value, carrying_value, "
                       "basis_note, approved_by) VALUES (%s, %s, '2027-03-31', 'manual', 10.005, 10.005, 'count', 't')", (client_id, fy_id))


def test_F20_a_depreciable_asset_needs_block_life_method_and_a_class_or_a_reason(f):
    client_id, _ = f.setup()
    with rejected(f.conn, constraint="fixed_assets_depreciable_needs_setup"):
        _asset(f, client_id, "A-1", sched2_class_key=None)  # no class and no override reason
    _asset(f, client_id, "A-2", sched2_class_key=None, life_override_reason="Life fixed by the board after a technical report")
    with rejected(f.conn, constraint="fixed_assets_client_no_key"):
        _asset(f, client_id, " a-2 ")
    land = f.ledger(client_id, "Land", "fixed_assets")
    f.conn.execute("INSERT INTO fixed_assets (client_id, asset_no, name, asset_ledger_id, is_depreciable, created_by) "
                   "VALUES (%s, 'L-1', 'Land', %s, false, 't')", (client_id, land))


def test_F21_asset_events_keep_their_chronology(f):
    client_id, _ = f.setup()
    a = _asset(f, client_id)
    with rejected(f.conn, message="needs an earlier opening or purchase"):
        _event(f, client_id, a, "addition", "2026-06-01", "2026-06-02")
    with rejected(f.conn, constraint="fixed_asset_events_cost_rules"):
        _event(f, client_id, a, "purchase", "2026-05-10", "2026-05-01")  # put to use before purchase
    _event(f, client_id, a, "purchase", "2026-05-01", "2026-05-10")
    with rejected(f.conn, constraint="fixed_asset_events_one_start_key"):
        _event(f, client_id, a, "purchase", "2026-05-02", "2026-05-12")
    _event(f, client_id, a, "addition", "2026-06-01", "2026-06-02", "500.00")
    with rejected(f.conn, message="before the asset was put to use"):
        _event(f, client_id, a, "disposal", "2026-06-01", None, "100.00")
    _event(f, client_id, a, "disposal", "2026-09-30", None, "100.00")
    with rejected(f.conn, constraint="fixed_asset_events_one_disposal_key"):
        _event(f, client_id, a, "disposal", "2026-10-01", None, "50.00")
    with rejected(f.conn, message="after the asset was disposed of"):
        _event(f, client_id, a, "addition", "2026-12-01", "2026-12-02", "500.00")


def test_F10_an_adjustment_needs_a_draft_journal_of_the_same_year(f):
    client_id, fy_id = f.setup()
    other_fy = f.fy(client_id, 2027)
    lines = f.balanced_lines(client_id)
    insert = ("INSERT INTO adjustment_entries (client_id, financial_year_id, adj_type, as_on_date, amount, basis_note, voucher_id, created_by) "
              "VALUES (%s, %s, 'outstanding_expense', '2027-03-31', 100.00, 'rent for March', %s, 't')")
    payment = f.draft(client_id, fy_id, lines, vtype="payment")
    with rejected(f.conn, message="must be a Journal"):
        f.conn.execute(insert, (client_id, fy_id, payment))
    vid = f.draft(client_id, fy_id, lines)
    with rejected(f.conn, message="same financial year"):
        f.conn.execute(insert, (client_id, other_fy, vid))
    f.conn.execute(insert, (client_id, fy_id, vid))
    f.approve(vid)
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE adjustment_entries SET basis_note = 'changed' WHERE voucher_id = %s", (vid,))
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("DELETE FROM adjustment_entries WHERE voucher_id = %s", (vid,))


def test_F27_one_active_depreciation_run_per_year_and_lines_follow_the_draft(f):
    client_id, fy_id = f.setup()
    a = _asset(f, client_id)
    lines = f.balanced_lines(client_id)
    v1 = f.draft(client_id, fy_id, lines)
    run1 = uuid.uuid4()
    run = ("INSERT INTO depreciation_runs (id, client_id, financial_year_id, as_on_date, total_depreciation, voucher_id, engine_version, "
           "created_by) VALUES (%s, %s, %s, '2027-03-31', 100.00, %s, 'fin-1', 't')")
    f.conn.execute(run, (run1, client_id, fy_id, v1))
    f.conn.execute(
        "INSERT INTO depreciation_run_lines (run_id, voucher_id, client_id, asset_id, method, cost, opening_accumulated, days_used, "
        "days_in_year, depreciation, closing_accumulated) VALUES (%s, %s, %s, %s, 'slm', 1000.00, 0, 365, 365, 100.00, 100.00)",
        (run1, v1, client_id, a))
    with rejected(f.conn, constraint="depreciation_run_lines_close_sum"):
        f.conn.execute("UPDATE depreciation_run_lines SET closing_accumulated = 150.00 WHERE run_id = %s", (run1,))
    v2 = f.draft(client_id, fy_id, lines)
    with rejected(f.conn, message="already has a depreciation run"):
        f.conn.execute(run, (uuid.uuid4(), client_id, fy_id, v2))
    f.approve(v1)
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE depreciation_run_lines SET depreciation = 90.00, closing_accumulated = 90.00 WHERE run_id = %s", (run1,))
    f.post(v1)  # still counts as the year's run until it is reversed
    with rejected(f.conn, message="already has a depreciation run"):
        f.conn.execute(run, (uuid.uuid4(), client_id, fy_id, v2))


def test_F43_snapshots_are_append_only(f):
    client_id, fy_id = f.setup()
    sha = "a" * 64
    sid = uuid.uuid4()
    insert = ("INSERT INTO statement_snapshots (id, client_id, financial_year_id, statement_key, format_key, payload, payload_sha256, "
              "engine_version, is_final, generated_by) VALUES (%s, %s, %s, 'balance_sheet', 'vertical', '{}'::jsonb, %s, 'fin-1', true, 't')")
    f.conn.execute(insert, (sid, client_id, fy_id, sha))
    with rejected(f.conn, constraint="statement_snapshots_sha_check"):
        f.conn.execute(insert, (uuid.uuid4(), client_id, fy_id, "xyz"))
    with rejected(f.conn, constraint="statement_snapshots_final_key"):
        f.conn.execute(insert, (uuid.uuid4(), client_id, fy_id, sha))
    with rejected(f.conn, message="append-only"):
        f.conn.execute("UPDATE statement_snapshots SET payload = '[1]'::jsonb WHERE id = %s", (sid,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM statement_snapshots WHERE id = %s", (sid,))
    f.conn.execute("UPDATE statement_snapshots SET superseded_at = now() WHERE id = %s", (sid,))
    with rejected(f.conn, message="append-only"):
        f.conn.execute("UPDATE statement_snapshots SET superseded_at = now() WHERE id = %s", (sid,))
    f.conn.execute(insert, (uuid.uuid4(), client_id, fy_id, sha))  # a new final one is allowed once the old is superseded


def test_F64_a_closed_year_is_frozen_and_reopens_only_after_every_closing_voucher_is_reversed(f):
    client_id, fy_id = f.setup()
    next_fy = f.fy(client_id, 2027)
    lines = f.balanced_lines(client_id)
    closing = f.draft(client_id, fy_id, lines, on="2027-03-31", narration="Year-end close: trading")
    f.approve(closing)
    f.post(closing)
    close_id = uuid.uuid4()
    f.conn.execute("INSERT INTO year_end_closes (id, client_id, financial_year_id, next_financial_year_id, status, net_profit, closed_by) "
                   "VALUES (%s, %s, %s, %s, 'closed', 190000.00, 't')", (close_id, client_id, fy_id, next_fy))
    with rejected(f.conn, constraint="year_end_closes_one_closed_key"):
        f.conn.execute("INSERT INTO year_end_closes (client_id, financial_year_id, next_financial_year_id, status, net_profit, closed_by) "
                       "VALUES (%s, %s, %s, 'closed', 1.00, 't')", (client_id, fy_id, next_fy))
    link = "INSERT INTO year_end_close_vouchers (close_id, client_id, step, kind, voucher_id) VALUES (%s, %s, 'trading', %s, %s)"
    f.conn.execute(link, (close_id, client_id, "closing", closing))
    # frozen: closing stock and the opening balances of the closed year cannot be written
    stock = ("INSERT INTO final_closing_stock (client_id, financial_year_id, as_on_date, source, cost_value, carrying_value, basis_note, approved_by) "
             "VALUES (%s, %s, '2027-03-31', 'manual', 10.00, 10.00, 'count', 't')")
    with rejected(f.conn, message="closed financial year cannot be changed"):
        f.conn.execute(stock, (client_id, fy_id))
    opening = "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (%s, %s, %s, 5.00, 0)"
    with rejected(f.conn, message="closed financial year cannot be changed"):
        f.conn.execute(opening, (client_id, lines[0][0], fy_id))
    f.conn.execute(opening, (client_id, lines[0][0], next_fy))  # the NEXT year takes the carried openings
    with rejected(f.conn, message="can only change from closed to reopened"):
        f.conn.execute("UPDATE year_end_closes SET net_profit = 1.00 WHERE id = %s", (close_id,))
    reopen = ("UPDATE year_end_closes SET status = 'reopened', reopened_by = 'owner', reopened_at = now(), "
              "reopen_reason = 'wrong closing stock' WHERE id = %s")
    with rejected(f.conn, message="every closing voucher to be reversed"):
        f.conn.execute(reopen, (close_id,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM year_end_closes WHERE id = %s", (close_id,))
    reversal = f.reverse(client_id, fy_id, closing, lines)
    with rejected(f.conn, message="reversal voucher of the same step"):
        f.conn.execute(link, (close_id, client_id, "reversal", f.posted(client_id, fy_id)))
    f.conn.execute(link, (close_id, client_id, "reversal", reversal))
    f.conn.execute(reopen, (close_id,))
    f.conn.execute(stock, (client_id, fy_id))  # editable again
    with rejected(f.conn, message="cannot be changed or deleted"):
        f.conn.execute("DELETE FROM year_end_close_vouchers WHERE close_id = %s", (close_id,))


def test_F66_the_same_open_bill_reference_can_open_two_financial_years(f):
    client_id, fy_id = f.setup()
    next_fy = f.fy(client_id, 2027)
    party = f.ledger(client_id, "Debtor", "sundry_debtors")
    f.conn.execute("INSERT INTO parties (ledger_id, client_id) VALUES (%s, %s)", (party, client_id))
    bill = ("INSERT INTO opening_bills (client_id, financial_year_id, party_ledger_id, bill_ref, bill_date, due_date, debit) "
            "VALUES (%s, %s, %s, 'INV-1', '2026-03-01', '2026-03-31', 100.00)")
    f.conn.execute(bill, (client_id, fy_id, party))
    f.conn.execute(bill, (client_id, next_fy, party))
    with rejected(f.conn, constraint="opening_bills_ref_key"):
        f.conn.execute(bill, (client_id, next_fy, party))
