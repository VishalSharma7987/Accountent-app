"""Pure helpers of the Phase 2 runner and loader (no database). Expected values are typed literally."""

from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pack_loader_p2 import PackFormatError, load_pack_p2, parse_amount, parse_bool, parse_date
from pack_runner_p2 import (
    RunReport,
    brs_rows,
    cash_book_rows,
    diff_keyed,
    format_report,
    judge_wrong,
    outstanding_rows,
    reconcile_not_due_days,
    signed,
    split_refs,
)

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "abc-traders-phase2-jun-2026"


def test_loader_reads_the_phase2_pack():
    pack = load_pack_p2(PACK)
    assert len(pack.vouchers) == 49 and len(pack.wrong_vouchers) == 6 and len(pack.wrong_parties) == 3
    v29 = next(v for v in pack.vouchers if v.ref_id == "V29")
    assert [(a.kind, a.amount, a.bill_ref) for a in v29.lines[0].allocations] == [
        ("new_ref", "88000.00", "INV-2026-006"), ("against_ref", "30000.00", "ADV-SR-01")]
    dates = [v.date for v in pack.vouchers]
    assert dates == sorted(dates)
    assert pack.client["pack_end_date"] == date(2026, 6, 30)


def test_parsers_reject_loose_formats():
    assert parse_amount("10.50") == D("10.50")
    for bad in ("10.5", "1,000.00", "-1.00"):
        with pytest.raises(PackFormatError):
            parse_amount(bad)
    with pytest.raises(PackFormatError):
        parse_date("02-04-2026")
    assert parse_bool("TRUE") is True
    with pytest.raises(PackFormatError):
        parse_bool("maybe")


def test_split_refs():
    assert split_refs("V24+V25+V26") == {"V24", "V25", "V26"}
    assert split_refs("") == frozenset()
    assert split_refs("OPENING:000451") == {"OPENING:000451"}


def test_diff_keyed_reports_missing_extra_and_field_differences():
    want = {("a",): {"x": "1.00"}, ("b",): {"x": "2.00"}}
    got = {("a",): {"x": "1.50"}, ("c",): {"x": "3.00"}}
    assert diff_keyed(want, got, ("x",), label=lambda k: k[0]) == [
        "a: x expected 1.00, tool says 1.50",
        "b: expected but the tool has no such row",
        "c: the tool has this row but the pack does not",
    ]
    assert diff_keyed(want, want, ("x",)) == []


def test_signed_balance():
    assert signed(NS(amount=D("40000.00"), side="Dr")) == "40000.00"
    assert signed(NS(amount=D("5.00"), side="Cr")) == "-5.00"
    assert signed(NS(amount=D("0.00"), side=None)) == "0.00"


def _item(ref, kind, outstanding, original, due, bucket, days):
    return NS(bill_ref=ref, kind=kind, bill_date=date(2026, 6, 26), due_date=due, original=D(original),
              outstanding=D(outstanding), days_past_due=days, bucket=bucket)


def test_outstanding_rows_show_an_on_account_item_on_the_opposite_side_of_a_payable():
    # Mehta: bill 39,000 Cr plus 30,000 paid on account (Dr, negative in the payable direction); total 9,000
    party = NS(party_name="Mehta Agencies", total=D("9000.00"), items=[
        _item("MA-502", "bill", "39000.00", "59000.00", date(2026, 6, 4), "0-30", 26),
        _item(None, "on_account", "-30000.00", "-30000.00", date(2026, 6, 26), "0-30", 4)])
    rows = outstanding_rows(NS(parties=[party], total=D("9000.00")), "Cr")
    assert rows[("bill", "Mehta Agencies", "MA-502")]["side"] == "Cr"
    assert rows[("on_account", "Mehta Agencies", "")] == {
        "kind": "on_account", "side": "Dr", "bill_date": "2026-06-26", "due_date": "2026-06-26",
        "original": "30000.00", "outstanding": "30000.00", "days_past_due": "4", "bucket": "0-30"}
    assert rows[("party_total", "Mehta Agencies", "")] == {"side": "Cr", "outstanding": "9000.00"}
    assert rows[("grand_total", "", "")] == {"side": "Cr", "outstanding": "9000.00"}


def test_not_due_days_difference_is_a_note_only_when_it_is_the_only_difference():
    want = {("bill", "P", "B1"): {"bucket": "not_due", "days_past_due": "-19"},
            ("bill", "P", "B2"): {"bucket": "not_due", "days_past_due": "-5"}}
    got = {("bill", "P", "B1"): {"bucket": "not_due", "days_past_due": "0"},
           ("bill", "P", "B2"): {"bucket": "0-30", "days_past_due": "3"}}
    notes = reconcile_not_due_days(want, got)
    assert notes == ["P B1: pack shows -19 days (still to run), tool shows 0"]
    assert want[("bill", "P", "B2")]["days_past_due"] == "-5"  # a real difference stays visible


def test_brs_rows_shape():
    def item(d, r, a):
        return NS(date=d, reference=r, amount=D(a))

    result = NS(
        as_on=date(2026, 6, 30), balance_per_books=D("448000.00"),
        issued_not_presented=[item(date(2026, 6, 26), "000471", "30000.00"), item(date(2026, 6, 29), "000472", "36500.00")],
        deposited_not_cleared=[], bank_only_credits=[item(date(2026, 6, 30), None, "1875.00")],
        bank_only_debits=[], computed_bank_balance=D("465549.00"), balance_per_bank=D("465549.00"),
        difference=D("0.00"))
    rows = brs_rows(result)
    assert rows[("total_issued_not_presented", "", "")]["amount"] == "66500.00"
    assert rows[("bank_only_credit", "2026-06-30", "")]["amount"] == "1875.00"
    assert rows[("total_bank_only_credits", "", "")]["amount"] == "1875.00"
    assert rows[("difference", "", "")]["amount"] == "0.00"


def test_judge_wrong_wrong_rule_extra_rule_and_message_warning():
    def err(rule, msg):
        return NS(rule_id=rule, message=msg)

    assert judge_wrong("x", "B-01", "allocated", [err("B-01", "Not fully Allocated")]) == (None, None)
    problem, _ = judge_wrong("x", "B-01", None, [err("B-02", "m")])
    assert problem.startswith("x: expected rule B-01, the tool reported B-02: m")
    problem, _ = judge_wrong("x", "B-01", None, [err("B-01", "m"), err("V-04", "n")])
    assert "wrong in more than one way" in problem
    problem, warning = judge_wrong("x", "B-01", "side", [err("B-01", "m")])
    assert problem is None and "does not contain 'side'" in warning


def test_format_report_lists_sections():
    r = RunReport("p")
    r.add("brs", "something differs")
    text = format_report(r)
    assert "1 difference(s)" in text and "[FAIL] brs" in text and "[ok  ] setup" in text


def test_cash_book_rows_opening_row_is_keyed_by_the_period_start_like_the_pack():
    book = NS(
        from_date=date(2026, 4, 1), opening=NS(amount=D("40000.00"), side="Dr"),
        days=[NS(date=date(2026, 4, 3), receipts=D("23600.00"), payments=D("0.00"), closing=NS(amount=D("63600.00"), side="Dr"))],
        total_receipts=D("23600.00"), total_payments=D("0.00"), closing=NS(amount=D("63600.00"), side="Dr"))
    rows = cash_book_rows(book)
    assert rows[("opening", "2026-04-01")] == {"receipts": "0.00", "payments": "0.00", "closing_dr": "40000.00"}
    assert rows[("day", "2026-04-03")]["closing_dr"] == "63600.00"
    assert rows[("total", "")]["receipts"] == "23600.00"
