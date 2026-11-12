"""Phase 2.1: Excel voucher import with bill allocation columns (bill_type, bill_ref, bill_amount, due_date).

One committed world (ABC Traders): Rahul Enterprises = bill-wise debtor (30 credit days) with ONE opening bill OB1
of 50,000.00 Dr; Sharma Suppliers = bill-wise creditor (45 days). Each test runs in a rolled-back transaction.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from xlsx_helpers import make_xlsx

from app.db import connection, migrate
from app.engine.bills import OpeningBillIn
from app.services import bills, client_setup, parties, voucher_import
from app.services.client_setup import ClientProfile

pytestmark = pytest.mark.integration

D = Decimal
RAHUL, SHARMA = "Rahul Enterprises", "Sharma Suppliers"


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("ABC Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
        )
        cid, fy = created.client_id, created.financial_year_id
        ids = dict(created.ledger_ids)
        for name, group in ((RAHUL, "sundry_debtors"), (SHARMA, "sundry_creditors"), ("HDFC Bank", "bank_accounts")):
            ids[name] = client_setup.add_ledger(conn, cid, name, group, actor="setup")
        client_setup.set_opening_balance(conn, cid, fy, ids[RAHUL], "50000", None, actor="setup")
        client_setup.set_opening_balance(conn, cid, fy, ids["Owner Capital A/c"], None, "50000", actor="setup")
        parties.set_party(conn, cid, ids[RAHUL], credit_days=30, bill_wise=False, actor="setup")
        bills.set_opening_bills(conn, cid, fy, ids[RAHUL], [OpeningBillIn("OB1", date(2026, 2, 1), "50000", "Dr")], actor="setup")
        parties.set_party(conn, cid, ids[RAHUL], credit_days=30, actor="setup")
        parties.set_party(conn, cid, ids[SHARMA], credit_days=45, actor="setup")
    yield cid
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def row(ref, vtype, ledger, dr=None, cr=None, *, reference=None, party=None, bill=(None, None, None, None), on="2026-04-05"):
    return [ref, on, vtype, ledger, dr, cr, "Test", reference, party, *bill]


def by_ref(result):
    return {v.ref_id: v for v in result.vouchers}


def errs(voucher):
    return [(e.rule_id, e.line_no, e.row) for e in voucher.errors]


def allocs(voucher):
    return [(a.line_no, a.row, a.kind, a.bill_ref, a.amount, a.due_date, a.auto) for a in voucher.allocations]


def test_dry_run_auto_new_ref_for_sales_and_purchase_and_none_for_the_others(svc_conn, world):
    rows = [
        row("S1", "sales", RAHUL, "5000.50", reference="INV-1", party=RAHUL),
        row("S1", "sales", "Sales", None, "5000.50", reference="INV-1", party=RAHUL),
        row("P1", "purchase", "Purchases", "2000", reference="SUP/1", party=SHARMA),
        row("P1", "purchase", SHARMA, None, "2000", reference="SUP/1", party=SHARMA),
        row("S2", "sales", RAHUL, "100", party=RAHUL),  # no reference_no
        row("S2", "sales", "Sales", None, "100", party=RAHUL),
        row("P2", "purchase", "Purchases", "300", party=SHARMA),  # no reference_no
        row("P2", "purchase", SHARMA, None, "300", party=SHARMA),
        row("R1", "receipt", "HDFC Bank", "1000", party=RAHUL),  # no allocation: never guessed
        row("R1", "receipt", RAHUL, None, "1000", party=RAHUL),
        row("J1", "journal", RAHUL, "10"),
        row("J1", "journal", "Sales", None, "10"),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, world, make_xlsx(rows)))
    assert (result["S1"].status, allocs(result["S1"])) == ("ok", [(1, 2, "new_ref", "INV-1", "5000.50", None, True)])
    assert (result["P1"].status, allocs(result["P1"])) == ("ok", [(2, 5, "new_ref", "SUP/1", "2000.00", None, True)])
    # sales without reference_no: B-03 naming the voucher; purchase: V-14 only (no extra B-01 for the same cause)
    assert errs(result["S2"]) == [("B-03", 1, 6)]
    assert "Voucher S2" in result["S2"].errors[0].message and "reference is required" in result["S2"].errors[0].message
    assert errs(result["P2"]) == [("V-14", None, 8)]
    # receipt and journal: no automatic allocation, the engine's B-01 stands
    assert errs(result["R1"]) == [("B-01", 2, 11)]
    assert result["R1"].errors[0].message == (
        "Line 2: 'Rahul Enterprises' is a bill-wise party; allocate the full amount 1,000.00 to bills "
        "(new reference, against reference, advance or on account).")
    assert errs(result["J1"]) == [("B-01", 1, 12)]
    assert allocs(result["R1"]) == [] and allocs(result["J1"]) == []


def test_commit_saves_the_auto_new_ref_as_a_draft_allocation_and_shows_it(svc_conn, world):
    rows = [
        row("S1", "sales", RAHUL, "5000.50", reference="INV-1", party=RAHUL),
        row("S1", "sales", "Sales", None, "5000.50", reference="INV-1", party=RAHUL),
        row("R1", "receipt", "HDFC Bank", "1000", party=RAHUL),
        row("R1", "receipt", RAHUL, None, "1000", party=RAHUL),
    ]
    result = voucher_import.commit(svc_conn, world, make_xlsx(rows), None, actor="clerk")
    assert [c.ref_id for c in result.created] == ["S1"]
    assert [(a.kind, a.bill_ref, a.amount, a.auto) for a in result.created[0].allocations] == [("new_ref", "INV-1", "5000.50", True)]
    assert result.skipped[0].ref_id == "R1" and "allocate the full amount 1,000.00" in result.skipped[0].reason
    assert svc_conn.execute(text("SELECT status FROM vouchers")).scalars().all() == ["draft"]
    saved = svc_conn.execute(text("SELECT kind, bill_ref, debit, credit, due_date FROM bill_allocations")).all()
    assert saved == [("new_ref", "INV-1", D("5000.50"), D("0.00"), date(2026, 5, 5))]  # 5 Apr + 30 credit days


def test_against_ref_settles_the_opening_bill_and_a_line_can_be_split_over_several_rows(svc_conn, world):
    rows = [
        row("R1", "receipt", "HDFC Bank", "1000", party=RAHUL),
        row("R1", "receipt", RAHUL, None, "1000", party=RAHUL, bill=("Against Ref", "OB1", "600.00", None)),
        row("R1", "receipt", None, party=RAHUL, bill=("on account", None, 400, None)),
        row("R2", "receipt", "HDFC Bank", "1000", party=RAHUL),
        row("R2", "receipt", RAHUL, None, "1000", party=RAHUL, bill=("Against Ref", "OB1", 600, None)),
        row("R2", "receipt", None, party=RAHUL, bill=("Against Ref", "OB1", 300, None)),
        row("N1", "payment", "Rent", "100"),  # allocations on a non-bill-wise ledger: passed on, the engine says B-01
        row("N1", "payment", "Cash", None, "100", bill=("New Ref", "X", 100, None)),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, world, make_xlsx(rows)))
    assert (result["R1"].status, allocs(result["R1"])) == ("ok", [
        (2, 3, "against_ref", "OB1", "600.00", None, False), (2, 4, "on_account", None, "400.00", None, False)])
    assert errs(result["R2"]) == [("B-01", 2, 6)]  # 600 + 300 = 900 against a line of 1,000.00
    assert result["R2"].errors[0].message == (
        "Line 2: bill allocations of 'Rahul Enterprises' add up to 900.00 but the line is 1,000.00 (difference 100.00).")
    assert errs(result["N1"]) == [("B-01", 2, 9)]

    committed = voucher_import.commit(svc_conn, world, make_xlsx(rows[:3]), ["R1"], actor="clerk")
    assert [c.ref_id for c in committed.created] == ["R1"]
    saved = svc_conn.execute(text("SELECT kind, bill_ref, debit, credit FROM bill_allocations ORDER BY line_no, id")).all()
    assert sorted(saved, key=lambda r: r[0]) == [
        ("against_ref", "OB1", D("0.00"), D("600.00")), ("on_account", None, D("0.00"), D("400.00"))]


def test_bad_allocation_amounts_and_kinds_are_rejected_not_rounded(svc_conn, world):
    rows = [
        row("A1", "receipt", "HDFC Bank", "10", party=RAHUL),
        row("A1", "receipt", RAHUL, None, "10", party=RAHUL, bill=("Against Ref", "OB1", "10.005", None)),
        row("A2", "receipt", "HDFC Bank", "10", party=RAHUL),
        row("A2", "receipt", RAHUL, None, "10", party=RAHUL, bill=("Settle", "OB1", "10", None)),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, world, make_xlsx(rows)))
    assert errs(result["A1"]) == [("B-05", 2, 3)]
    assert errs(result["A2"]) == [(None, None, 5)]
    assert result["A2"].errors[0].message.startswith("bill_type must be one of New Ref")


def test_a_file_with_the_old_nine_columns_still_works(svc_conn, world):
    from app.importers.voucher_excel import LEGACY_COLUMNS

    rows = [row("S1", "sales", RAHUL, "50", reference="INV-5", party=RAHUL)[:9], row("S1", "sales", "Sales", None, "50", reference="INV-5", party=RAHUL)[:9]]
    result = voucher_import.dry_run(svc_conn, world, make_xlsx(rows, header=LEGACY_COLUMNS))
    assert (result.ok_count, allocs(result.vouchers[0])) == (1, [(1, 2, "new_ref", "INV-5", "50.00", None, True)])


def test_a_due_date_on_a_new_ref_row_is_kept(svc_conn, world):
    rows = [
        row("S1", "sales", RAHUL, "50", reference="INV-6", party=RAHUL, bill=("New Ref", "INV-6", "50", date(2026, 6, 1))),
        row("S1", "sales", "Sales", None, "50", reference="INV-6", party=RAHUL),
    ]
    result = voucher_import.dry_run(svc_conn, world, make_xlsx(rows))
    assert (result.ok_count, allocs(result.vouchers[0])) == (1, [(1, 2, "new_ref", "INV-6", "50.00", date(2026, 6, 1), False)])
