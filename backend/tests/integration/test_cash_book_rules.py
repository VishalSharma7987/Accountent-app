"""Phase 2 steps 2.4-2.5 against the database: Cash/Bank Book, C-01, D-01, MSME report, MSME rule seed."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.models import OpenBill, VoucherDraft, VoucherLine
from app.main import app
from app.services import cashbook, client_setup, msme, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration
D = Decimal


@dataclass
class World:
    client_id: object
    ids: dict


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    """One committed client: Cash opening 1,000 Dr against Capital 1,000 Cr. Cleaned when the module ends."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("Cash Test Co", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
        )
        ids = dict(created.ledger_ids)
        for name, group in (("HDFC Bank", "bank_accounts"), ("Sharma Suppliers", "sundry_creditors")):
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, group, actor="setup")
        client_setup.set_opening_balance(conn, created.client_id, created.financial_year_id, ids["Cash"], "1000", None, actor="setup")
        client_setup.set_opening_balance(
            conn, created.client_id, created.financial_year_id, ids["Owner Capital A/c"], None, "1000", actor="setup"
        )
    yield World(created.client_id, ids)
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def vd(w, vtype, lines, on, party=None, override=None, reference_no=None):
    return VoucherDraft(
        w.client_id, vtype, on, "Test voucher", reference_no, w.ids[party] if party else None,
        tuple(VoucherLine(w.ids[n], dr, cr) for n, dr, cr in lines), override,
    )


def receipt(w, amount, on):
    return vd(w, "receipt", [("Cash", amount, None), ("Sales", None, amount)], on)


def cash_payment(w, amount, on):
    return vd(w, "payment", [("Rent", amount, None), ("Cash", None, amount)], on)


def posted(conn, draft):
    result = vouchers.create_draft(conn, draft, actor="tester")
    assert result.errors == []
    vouchers.approve(conn, result.voucher_id, actor="approver")
    vouchers.post(conn, result.voucher_id, actor="poster")
    return result.voucher_id


def test_cash_book_from_database_and_bank_book(svc_conn, world):
    posted(svc_conn, receipt(world, "500", date(2026, 4, 3)))
    posted(svc_conn, cash_payment(world, "300", date(2026, 4, 4)))
    book = cashbook.cash_book(svc_conn, world.client_id, world.ids["Cash"], date(2026, 4, 1), date(2026, 4, 30))
    assert (book.opening.amount, book.opening.side) == (D("1000.00"), "Dr")
    assert [(d.date, d.receipts, d.payments, d.closing.amount) for d in book.days] == [
        (date(2026, 4, 3), D("500.00"), D("0.00"), D("1500.00")),
        (date(2026, 4, 4), D("0.00"), D("300.00"), D("1200.00")),
    ]
    assert book.days[0].entries[0].counter_ledgers == ("Sales",)
    assert (book.total_receipts, book.total_payments, book.closing.amount) == (D("500.00"), D("300.00"), D("1200.00"))
    bank = cashbook.cash_book(svc_conn, world.client_id, world.ids["HDFC Bank"], date(2026, 4, 1), date(2026, 4, 30))
    assert bank.days == () and bank.closing.amount == D("0.00")
    with pytest.raises(ServiceError) as info:
        cashbook.cash_book(svc_conn, world.client_id, world.ids["Rent"], date(2026, 4, 1), date(2026, 4, 30))
    assert info.value.code == "not_a_book_ledger"


def test_C01_payment_beyond_cash_blocked_on_approve_then_allowed_after_a_receipt(svc_conn, world):
    draft = vouchers.create_draft(svc_conn, cash_payment(world, "1500", date(2026, 4, 5)), actor="tester")
    with pytest.raises(VoucherRuleError) as info:
        vouchers.approve(svc_conn, draft.voucher_id, actor="approver")
    assert [e.rule_id for e in info.value.errors] == ["C-01"]
    assert "Cash would be negative on 05-04-2026: Cr 500.00" in info.value.errors[0].message
    posted(svc_conn, receipt(world, "700", date(2026, 4, 2)))
    vouchers.approve(svc_conn, draft.voucher_id, actor="approver")
    vouchers.post(svc_conn, draft.voucher_id, actor="poster")  # 1000 + 700 - 1500 = 200


def test_C01_reversing_a_receipt_that_funded_a_payment_is_refused(svc_conn, world):
    funding = posted(svc_conn, receipt(world, "700", date(2026, 4, 2)))
    posted(svc_conn, cash_payment(world, "1500", date(2026, 4, 5)))
    with pytest.raises(VoucherRuleError) as info:
        vouchers.reverse(svc_conn, funding, date(2026, 4, 10), "wrong party", actor="poster")
    assert info.value.errors[0].rule_id == "C-01"
    assert "10-04-2026: Cr 500.00" in info.value.errors[0].message


def test_C01_bank_ledger_may_go_negative(svc_conn, world):
    posted(svc_conn, vd(world, "payment", [("Rent", "9999", None), ("HDFC Bank", None, "9999")], date(2026, 4, 5)))


def pay_supplier(w, amount, on, override=None):
    return vd(w, "payment", [("Sharma Suppliers", amount, None), ("HDFC Bank", None, amount)], on,
              party="Sharma Suppliers", override=override)


def test_D01_duplicate_payment_blocked_unless_overridden(svc_conn, world):
    first = vouchers.create_draft(svc_conn, pay_supplier(world, "10000", date(2026, 4, 4)), actor="tester")
    assert first.errors == []
    again = vouchers.create_draft(svc_conn, pay_supplier(world, "10000", date(2026, 4, 7)), actor="tester")
    assert again.voucher_id is None and [e.rule_id for e in again.errors] == ["D-01"]
    assert "10,000.00" in again.errors[0].message
    assert vouchers.create_draft(svc_conn, pay_supplier(world, "10000.01", date(2026, 4, 7)), actor="tester").errors == []
    assert vouchers.create_draft(svc_conn, pay_supplier(world, "10000", date(2026, 4, 12)), actor="tester").errors == []  # 8 days
    forced = vouchers.create_draft(
        svc_conn, pay_supplier(world, "10000", date(2026, 4, 7), override="Second instalment"), actor="tester"
    )
    assert forced.errors == [] and forced.voucher_id is not None


def test_M01_rule_seed_is_present_and_every_row_is_secondary_verified(svc_conn):
    rows = svc_conn.execute(
        text("SELECT category, applies, verification_status, covered_activities, rule_key FROM msme_payment_rules")
    ).all()
    assert len(rows) == 6
    assert {r[2] for r in rows} == {"secondary_verified"}
    assert {(r[0], r[1]) for r in rows} == {("micro", True), ("small", True), ("medium", False)}
    assert {(r[0], tuple(r[3])) for r in rows if r[1]} == {("micro", ("manufacturing", "services")), ("small", ("manufacturing", "services"))}
    assert all(r[3] == [] for r in rows if not r[1])
    assert {r[4] for r in rows} == {"msme_43bh_1961", "msme_37_2_g_2025"}


def set_msme_party(conn, w, name, *, cat="micro", activity="manufacturing", udyam_date=date(2020, 1, 1), days=30, agreement=True):
    conn.execute(text("DELETE FROM parties WHERE ledger_id = :l"), {"l": w.ids[name]})
    conn.execute(
        text(
            "INSERT INTO parties (ledger_id, client_id, msme_category, udyam_no, msme_written_agreement, msme_agreed_days, "
            "msme_activity, udyam_registration_date, bill_wise) VALUES (:l, :c, :cat, 'UDYAM-MH-12-0000001', :agr, :days, :act, :ud, false)"
        ),
        {"l": w.ids[name], "c": w.client_id, "cat": cat, "agr": agreement, "days": days if agreement else None,
         "act": activity, "ud": udyam_date},
    )


def sharma_bill(w, on=date(2026, 4, 10), accepted=None):
    return [OpenBill(
        w.ids["Sharma Suppliers"], "Sharma Suppliers", "SUP/889", "bill", on, None, D("-10000.00"), D("-10000.00"),
        accepted or on, "bill date" if accepted is None else "goods received date",
    )]


def test_M01_msme_report_with_injected_bills(svc_conn, world):
    set_msme_party(svc_conn, world, "Sharma Suppliers")
    report = msme.msme_report(svc_conn, world.client_id, date(2026, 5, 30), open_bills=sharma_bill(world))
    assert report.rule_status == "secondary_verified" and "37(2)(g)" in report.rule_source
    [item] = report.items
    # 10-04-2026 + 30 days = 10-05-2026; 20 days overdue on 30-05-2026
    assert (item.legal_days, item.legal_due_date, item.days_overdue, item.outstanding) == (30, date(2026, 5, 10), 20, D("10000.00"))
    assert (item.acceptance_date, item.acceptance_basis) == (date(2026, 4, 10), "bill date")
    assert report.total_outstanding == D("10000.00")
    assert item.rule_status == "secondary_verified"


def test_M01_report_uses_goods_received_date_trader_and_udyam_date_rules(svc_conn, world):
    on = date(2026, 5, 30)
    set_msme_party(svc_conn, world, "Sharma Suppliers")
    # goods received 20-04-2026 + 30 = 20-05-2026; 10 days overdue on 30-05
    [item] = msme.msme_report(svc_conn, world.client_id, on, open_bills=sharma_bill(world, accepted=date(2026, 4, 20))).items
    assert (item.acceptance_date, item.acceptance_basis, item.legal_due_date, item.days_overdue) == (
        date(2026, 4, 20), "goods received date", date(2026, 5, 20), 10)
    set_msme_party(svc_conn, world, "Sharma Suppliers", activity="trading")
    assert msme.msme_report(svc_conn, world.client_id, on, open_bills=sharma_bill(world)).items == ()
    set_msme_party(svc_conn, world, "Sharma Suppliers", cat="medium")
    assert msme.msme_report(svc_conn, world.client_id, on, open_bills=sharma_bill(world)).items == ()
    set_msme_party(svc_conn, world, "Sharma Suppliers", udyam_date=date(2026, 4, 11))  # registered a day after the bill
    assert msme.msme_report(svc_conn, world.client_id, on, open_bills=sharma_bill(world)).items == ()


def test_M01_database_checks_the_new_party_columns(svc_conn, world):
    with pytest.raises(Exception, match="parties_msme_agreed_days_range"), svc_conn.begin_nested():
        set_msme_party(svc_conn, world, "Sharma Suppliers", days=46)
    with pytest.raises(Exception, match="parties_msme_agreement_days"), svc_conn.begin_nested():
        set_msme_party(svc_conn, world, "Sharma Suppliers", agreement=False)  # fine ...
        svc_conn.execute(text("UPDATE parties SET msme_agreed_days = 20 WHERE ledger_id = :l"), {"l": world.ids["Sharma Suppliers"]})
    with pytest.raises(Exception, match="parties_msme_needs_activity"), svc_conn.begin_nested():
        set_msme_party(svc_conn, world, "Sharma Suppliers", activity=None)


def test_api_cash_book(svc_conn, world):
    posted(svc_conn, receipt(world, "500", date(2026, 4, 3)))
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        r = TestClient(app).get(
            f"/clients/{world.client_id}/reports/cash-book",
            params={"ledger_id": str(world.ids["Cash"]), "from": "2026-04-01", "to": "2026-04-30"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["ledger_name"] == "Cash" and body["opening"] == {"amount": "1000.00", "side": "Dr"}
    assert body["total_receipts"] == "500.00" and body["closing"] == {"amount": "1500.00", "side": "Dr"}
    entry = body["days"][0]["entries"][0]
    assert (entry["receipt"], entry["payment"], entry["counter_ledgers"]) == ("500.00", "0.00", ["Sales"])
