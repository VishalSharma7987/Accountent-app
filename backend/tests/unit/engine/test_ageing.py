"""Ageing and outstanding report: bucket boundaries by days past the DUE date, direction, tie check."""

from datetime import date
from decimal import Decimal

from app.engine.bills import PartyInfo, ageing
from app.engine.models import OpenBill

D = Decimal
AS_ON = date(2026, 6, 30)
PARTIES = {
    "rahul": PartyInfo("Rahul Enterprises", "debtor", True, 30),
    "sharma": PartyInfo("Sharma Suppliers", "creditor", True, 45),
}


def bill(due, outstanding="1000", party="rahul", ref="B", kind="bill", bill_date=date(2026, 1, 1)):
    name = PARTIES[party].name
    return OpenBill(party, name, ref, kind, bill_date, due, D(outstanding), D(outstanding))


def bucket_of(due):
    report = ageing([bill(due)], AS_ON, "receivable", PARTIES, {"rahul": D("1000")})
    (item,) = report.parties[0].items
    return item.bucket, item.days_past_due


def test_ageing_boundaries_days_past_due_date():
    cases = [
        (date(2026, 7, 1), ("not_due", 0)),
        (date(2026, 6, 30), ("0-30", 0)),    # due today
        (date(2026, 5, 31), ("0-30", 30)),
        (date(2026, 5, 30), ("31-60", 31)),
        (date(2026, 5, 1), ("31-60", 60)),
        (date(2026, 4, 30), ("61-90", 61)),
        (date(2026, 4, 1), ("61-90", 90)),
        (date(2026, 3, 31), ("90+", 91)),
    ]
    for due, expected in cases:
        assert bucket_of(due) == expected, due


def test_ageing_receivable_totals_per_bucket_and_party():
    open_ = [
        bill(date(2026, 7, 15), "1000", ref="A"),
        bill(date(2026, 6, 20), "2000", ref="B"),
        bill(date(2026, 5, 20), "3000", ref="C"),
        bill(date(2026, 4, 20), "4000", ref="D"),
        bill(date(2026, 1, 20), "5000", ref="E"),
        bill(date(2026, 1, 20), "-500", ref="ADV", kind="advance"),
        bill(date(2026, 6, 25), "-7000", party="sharma", ref="PB"),  # a creditor item is not in a receivable report
    ]
    report = ageing(open_, AS_ON, "receivable", PARTIES, {"rahul": D("14500"), "sharma": D("-7000")})
    assert [p.party_name for p in report.parties] == ["Rahul Enterprises"]
    assert report.buckets == {"not_due": D("1000.00"), "0-30": D("2000.00"), "31-60": D("3000.00"),
                              "61-90": D("4000.00"), "90+": D("4500.00")}
    assert report.total == D("14500.00")
    assert report.parties[0].total == D("14500.00") and report.parties[0].ties and report.ties


def test_ageing_payable_shows_credit_balances_as_positive():
    open_ = [bill(date(2026, 6, 10), "-35000", party="sharma", ref="PB1"),
             bill(date(2026, 6, 10), "8000", party="sharma", ref="SADV", kind="advance")]
    report = ageing(open_, AS_ON, "payable", PARTIES, {"sharma": D("-27000")})
    p = report.parties[0]
    assert [(i.bill_ref, i.original, i.outstanding) for i in p.items] == [
        ("PB1", D("35000.00"), D("35000.00")), ("SADV", D("-8000.00"), D("-8000.00"))]
    assert p.buckets["0-30"] == D("27000.00") and p.total == D("27000.00")
    assert p.ledger_balance == D("27000.00") and p.ties


def test_ageing_ties_false_when_ledger_balance_differs_and_party_without_bills_is_listed():
    open_ = [bill(date(2026, 6, 10), "1000", ref="A")]
    report = ageing(open_, AS_ON, "receivable", PARTIES, {"rahul": D("1200")})
    assert not report.parties[0].ties and not report.ties
    assert report.parties[0].ledger_balance == D("1200.00")
    nothing = ageing([], AS_ON, "receivable", PARTIES, {"rahul": D("300")})
    assert [(p.party_name, p.total, p.ledger_balance, p.ties) for p in nothing.parties] == [
        ("Rahul Enterprises", D("0.00"), D("300.00"), False)]


def test_ageing_party_with_zero_everything_is_not_listed():
    report = ageing([], AS_ON, "receivable", PARTIES, {"rahul": D("0")})
    assert report.parties == () and report.ties and report.total == D("0.00")


def test_ageing_item_without_due_date_ages_from_its_bill_date():
    open_ = [bill(None, "100", ref="ADV", kind="advance", bill_date=date(2026, 3, 1))]
    report = ageing(open_, AS_ON, "receivable", PARTIES, {"rahul": D("100")})
    assert report.parties[0].items[0].bucket == "90+"
