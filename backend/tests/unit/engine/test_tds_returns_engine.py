"""Package D engine: quarters, form choice by quarter-end date, return working, certificate data (T-30 .. T-34).

Literal rule objects and hand-calculated expected values; no database.
"""

from datetime import date
from decimal import Decimal as D

from app.engine.tds_returns import (
    AllocRow,
    ChallanRow,
    ItemRow,
    build_certificate,
    build_return_working,
    pick_form,
    quarter_of,
    quarter_period,
    return_kind_of,
)
from app.engine.tds_types import FormRule


def form(key, act, no, frm, to, status="pending"):
    return FormRule(key, act, no, "d", None, frm, to, status)


FORMS = [
    form("return_non_salary_resident", "it_act_1961", "Form 26Q", date(2025, 4, 1), date(2026, 3, 31)),
    form("return_non_salary_resident", "it_act_2025", "Form 140", date(2026, 4, 1), None, "secondary_verified"),
    form("return_salary", "it_act_1961", "Form 24Q", date(2025, 4, 1), date(2026, 3, 31)),
    form("return_salary", "it_act_2025", "Form 138", date(2026, 4, 1), None, "secondary_verified"),
    form("return_tcs", "it_act_1961", "Form 27EQ", date(2025, 4, 1), date(2026, 3, 31)),
    form("return_tcs", "it_act_2025", "Form 143", date(2026, 4, 1), None, "secondary_verified"),
]


def item(item_id, name, pan_status, pan, paid, rate, tds, event=date(2026, 5, 10), nature="contractor", rate_mode="flat",
         kind="tds", reason="normal", cert=None):
    return ItemRow(
        item_id=item_id, voucher_number=f"PAY/2026-27/{item_id}", deductee_ledger_id=f"L-{item_id}", deductee_name=name,
        pan=pan, pan_status=pan_status, nature_key=nature, rate_mode=rate_mode, kind=kind, section_ref="194C",
        payment_code=None, act="it_act_2025" if event >= date(2026, 4, 1) else "it_act_1961", event_date=event,
        payment_amount=D(paid), taxable_base=D(paid), rate_applied=D(rate), rate_reason=reason, tds_amount=D(tds),
        certificate_no=cert)


def challan(cid, tax, in_quarter=True, interest="0", fee="0", status="entered"):
    t, i, f = D(tax), D(interest), D(fee)
    return ChallanRow(cid, "0510308", date(2026, 6, 7), "00041", t, i, f, D(0), t + i + f, status, in_quarter)


# ---- T-31 quarters and forms -----------------------------------------------------------------------------------------


def test_T31_quarter_of_dates():
    assert quarter_of(date(2026, 4, 1)) == (1, 2026)
    assert quarter_of(date(2026, 6, 30)) == (1, 2026)
    assert quarter_of(date(2026, 12, 31)) == (3, 2026)
    assert quarter_of(date(2027, 1, 1)) == (4, 2026)
    assert quarter_of(date(2026, 3, 31)) == (4, 2025)


def test_T31_quarter_period_q4_is_in_next_calendar_year():
    assert quarter_period(date(2025, 4, 1), 4) == (date(2026, 1, 1), date(2026, 3, 31))
    assert quarter_period(date(2026, 4, 1), 1) == (date(2026, 4, 1), date(2026, 6, 30))
    assert quarter_period(date(2026, 4, 1), 2) == (date(2026, 7, 1), date(2026, 9, 30))


def test_T31_form_by_quarter_end_q4_fy2025_26_is_old_form():
    assert pick_form(FORMS, "return_non_salary_resident", date(2026, 3, 31)).form_no == "Form 26Q"
    assert pick_form(FORMS, "return_salary", date(2026, 3, 31)).form_no == "Form 24Q"
    assert pick_form(FORMS, "return_tcs", date(2026, 3, 31)).form_no == "Form 27EQ"


def test_T31_form_by_quarter_end_q1_fy2026_27_is_new_form_with_status():
    f = pick_form(FORMS, "return_non_salary_resident", date(2026, 6, 30))
    assert (f.form_no, f.verification_status) == ("Form 140", "secondary_verified")
    assert pick_form(FORMS, "return_salary", date(2026, 6, 30)).form_no == "Form 138"
    assert pick_form(FORMS, "return_tcs", date(2026, 6, 30)).form_no == "Form 143"


def test_T31_no_form_in_force_returns_none():
    assert pick_form(FORMS, "return_tcs", date(2025, 3, 31)) is None


def test_T31_return_kind_of_item():
    assert return_kind_of(item("1", "A", "valid", "AAAPA1111A", "100", "1", "1")) == "non_salary_resident"
    assert return_kind_of(item("2", "B", "valid", "AAAPB1111A", "100", "1", "1", rate_mode="slab_manual", nature="salary")) == "salary"
    assert return_kind_of(item("3", "C", "valid", "AAAPC1111A", "100", "1", "1", kind="tcs")) == "tcs"


# ---- T-30 / T-32 working ---------------------------------------------------------------------------------------------

A = item("1", "Alpha Contractors", "valid", "AAAPA1111A", "100000.00", "1", "1000.00")
B = item("2", "Beta Works", "missing", None, "50000.00", "20", "10000.00", event=date(2026, 5, 20))


def test_T30_missing_tan_is_a_blocking_error():
    w = build_return_working("non_salary_resident", None, [A], [], [])
    errs = [e for e in w.errors if e["blocking"]]
    assert [e["rule_id"] for e in errs] == ["T-30"]
    assert "TAN" in errs[0]["message"]


def test_T30_row_without_valid_pan_is_listed_as_error_row_with_higher_rate_reason():
    w = build_return_working("non_salary_resident", "DELA12345B", [A, B], [], [])
    row = next(r for r in w.deductee_rows if r["deductee_name"] == "Beta Works")
    assert row["pan"] is None and row["pan_status"] == "missing" and row["error_row"] is True
    errs = [e for e in w.errors if not e["blocking"]]
    assert len(errs) == 1
    assert errs[0]["rule_id"] == "T-30" and errs[0]["line_no"] == 2
    assert "Beta Works" in errs[0]["message"] and "20.00%" in errs[0]["message"]
    ok = next(r for r in w.deductee_rows if r["deductee_name"] == "Alpha Contractors")
    assert ok["error_row"] is False


def test_T32_short_deposit_warns_per_item_and_totals_match_hand_working():
    challans = [challan("C1", "7000.00")]
    allocs = [AllocRow("C1", "1", D("1000.00")), AllocRow("C1", "2", D("6000.00"))]
    w = build_return_working("non_salary_resident", "DELA12345B", [A, B], challans, allocs)
    assert w.totals["amount_paid"] == D("150000.00")
    assert w.totals["tax_deducted"] == D("11000.00")
    assert w.totals["tax_deposited"] == D("7000.00")
    assert w.totals["short_deposit"] == D("4000.00")
    assert w.totals["challan_tax"] == D("7000.00")
    assert w.totals["challan_total"] == D("7000.00")
    short = [x for x in w.warnings if x["rule_id"] == "T-32"]
    assert len(short) == 1
    assert "Beta Works" in short[0]["message"] and "4,000.00" in short[0]["message"]
    beta = next(r for r in w.deductee_rows if r["deductee_name"] == "Beta Works")
    assert beta["tax_deposited"] == D("6000.00")


def test_T32_fully_deposited_has_no_short_warning_and_challan_row_is_listed():
    challans = [challan("C1", "11000.00", interest="150.00", fee="200.00")]
    allocs = [AllocRow("C1", "1", D("1000.00")), AllocRow("C1", "2", D("10000.00"))]
    w = build_return_working("non_salary_resident", "DELA12345B", [A, B], challans, allocs)
    assert [x for x in w.warnings if x["rule_id"] == "T-32"] == []
    assert w.totals["short_deposit"] == D("0.00")
    assert w.challan_rows == [{
        "bsr_code": "0510308", "deposit_date": date(2026, 6, 7), "serial_no": "00041", "tax": D("11000.00"),
        "interest": D("150.00"), "fee": D("200.00"), "other": D("0.00"), "total": D("11350.00"), "status": "entered",
    }]
    assert w.totals["challan_total"] == D("11350.00")


def test_T32_unallocated_challan_of_the_quarter_is_listed_with_a_warning():
    challans = [challan("C9", "500.00")]
    w = build_return_working("non_salary_resident", "DELA12345B", [A], challans, [])
    assert len(w.challan_rows) == 1
    assert any(x["rule_id"] == "T-32" and "500.00" in x["message"] and "not allocated" in x["message"] for x in w.warnings)


def test_T32_challan_allocated_only_to_other_items_or_other_quarter_is_not_in_this_working():
    challans = [challan("C1", "900.00"), challan("C2", "300.00", in_quarter=False)]
    allocs = [AllocRow("C1", "99", D("900.00"))]  # item 99 is not in this return
    w = build_return_working("non_salary_resident", "DELA12345B", [A], challans, allocs)
    assert w.challan_rows == []


def test_T30_salary_items_are_not_in_a_non_salary_working():
    s = item("5", "Employee", "valid", "AAAPE1111A", "30000.00", "0", "2500.00", rate_mode="slab_manual", nature="salary")
    w = build_return_working("non_salary_resident", "DELA12345B", [A, s], [], [])
    assert [r["deductee_name"] for r in w.deductee_rows] == ["Alpha Contractors"]
    ws = build_return_working("salary", "DELA12345B", [A, s], [], [])
    assert [r["deductee_name"] for r in ws.deductee_rows] == ["Employee"]
    assert ws.totals["tax_deducted"] == D("2500.00")


def test_T30_nil_item_is_listed_but_gets_no_short_warning():
    z = item("6", "Gamma", "valid", "AAAPG1111A", "20000.00", "0", "0.00", reason="below_threshold")
    w = build_return_working("non_salary_resident", "DELA12345B", [z], [], [])
    assert len(w.deductee_rows) == 1 and w.deductee_rows[0]["rate_reason"] == "below_threshold"
    assert [x for x in w.warnings if x["rule_id"] == "T-32"] == []


def test_T30_rows_are_sorted_by_name_then_date():
    a2 = item("3", "Alpha Contractors", "valid", "AAAPA1111A", "10.00", "1", "0.10", event=date(2026, 4, 2))
    w = build_return_working("non_salary_resident", "DELA12345B", [B, A, a2], [], [])
    assert [(r["deductee_name"], r["event_date"]) for r in w.deductee_rows] == [
        ("Alpha Contractors", date(2026, 4, 2)), ("Alpha Contractors", date(2026, 5, 10)), ("Beta Works", date(2026, 5, 20))]


# ---- T-34 certificate ------------------------------------------------------------------------------------------------

DEDUCTOR = {"name": "Acme Traders", "tan": "DELA12345B", "pan": "AAACA1234A"}
DEDUCTEE = {"name": "Alpha Contractors", "pan": "AAAPA1111A", "pan_status": "valid"}
F131 = form("certificate_non_salary", "it_act_2025", "Form 131", date(2026, 4, 1), None, "secondary_verified")


def test_T34_certificate_data_for_fully_deposited_items():
    a2 = item("3", "Alpha Contractors", "valid", "AAAPA1111A", "40000.00", "1", "400.00", event=date(2026, 6, 15))
    challans = [challan("C1", "1400.00")]
    allocs = [AllocRow("C1", "1", D("1000.00")), AllocRow("C1", "3", D("400.00"))]
    data, errors = build_certificate(F131, DEDUCTOR, DEDUCTEE, [A, a2], challans, allocs, "2026-27 Q1")
    assert errors == []
    assert data["form_no"] == "Form 131"
    assert data["total_deducted"] == D("1400.00")
    assert data["total_deposited"] == D("1400.00")
    assert data["total_amount_paid"] == D("140000.00")
    assert len(data["items"]) == 2
    assert data["challans"] == [{"bsr_code": "0510308", "deposit_date": date(2026, 6, 7), "serial_no": "00041", "tax_deposited": D("1400.00")}]
    assert data["deductor"] == DEDUCTOR and data["deductee"]["pan"] == "AAAPA1111A"


def test_T34_item_not_fully_allocated_is_refused_with_amounts():
    challans = [challan("C1", "600.00")]
    allocs = [AllocRow("C1", "1", D("600.00"))]
    data, errors = build_certificate(F131, DEDUCTOR, DEDUCTEE, [A], challans, allocs, "2026-27 Q1")
    assert data is None
    assert [e["rule_id"] for e in errors] == ["T-34"]
    assert "400.00" in errors[0]["message"] and "1,000.00" in errors[0]["message"]


def test_T34_nothing_deducted_is_refused():
    z = item("6", "Gamma", "valid", "AAAPG1111A", "20000.00", "0", "0.00", reason="below_threshold")
    data, errors = build_certificate(F131, DEDUCTOR, DEDUCTEE, [z], [], [], "2026-27 Q1")
    assert data is None and errors[0]["rule_id"] == "T-34"


def test_T30_certificate_needs_deductor_tan():
    data, errors = build_certificate(
        F131, {**DEDUCTOR, "tan": None}, DEDUCTEE, [A], [challan("C1", "1000.00")], [AllocRow("C1", "1", D("1000.00"))], "p")
    assert data is None and errors[0]["rule_id"] == "T-30"


def test_T34_challan_amounts_are_only_what_went_to_this_deductee():
    challans = [challan("C1", "11000.00")]
    allocs = [AllocRow("C1", "1", D("1000.00")), AllocRow("C1", "2", D("10000.00"))]
    data, errors = build_certificate(F131, DEDUCTOR, DEDUCTEE, [A], challans, allocs, "p")
    assert errors == []
    assert data["challans"][0]["tax_deposited"] == D("1000.00")
