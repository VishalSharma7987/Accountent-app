"""Package F engine: form selection by FY end date and clause derivation (A-xx findings -> Form 3CD clause data). Literal expected values."""

from datetime import date
from decimal import Decimal

from app.engine import audit_form as f

D = Decimal
DEFS = [
    f.FormDef("form_3cd", "Form 3CD", "it_act_1961", "44AB", date(1900, 1, 1), date(2026, 3, 31), "secondary_verified"),
    f.FormDef("form_26", "Form 26", "it_act_2025", "63", date(2026, 4, 1), None, "secondary_verified"),
]


def clause(no, derivability="partly_books", form="form_3cd"):
    return f.ClauseDef(form, no, f"Clause {no}", derivability, None, "pending")


def row(i, check, amount, disallow=None, status=None):
    return f.FindingRow(i, check, D(amount), None if disallow is None else D(disallow), status)


def test_A_form_fy_2025_26_uses_form_3cd_and_fy_2026_27_uses_form_26():
    assert f.select_form(DEFS, date(2026, 3, 31)).form_key == "form_3cd"
    assert f.select_form(DEFS, date(2027, 3, 31)).form_key == "form_26"


def test_A_form_boundary_days_and_no_definition():
    assert f.select_form(DEFS, date(2026, 4, 1)).form_key == "form_26"
    assert f.select_form(DEFS, date(2026, 3, 30)).form_key == "form_3cd"
    assert f.select_form(DEFS[1:], date(2026, 3, 31)) is None


def test_A_form_clause_21_sums_cash_payment_findings_and_carries_the_pending_status():
    res = f.derive([clause("21")], [row("f1", "A-05", "11000.00", "11000.00", "pending"), row("f2", "A-05", "25000.50", "25000.50", "pending"),
                                    row("f3", "A-06", "999999.00")], ["A-05", "A-06"])
    got = {e.field_key: e.value for e in res.entries}
    assert got == {"cash_payment_exception_count": "2", "cash_payment_total_amount": "36000.50",
                   "cash_payment_disallowable_amount": "36000.50", "legal_rule_status": "pending", "source_finding_ids": ["f1", "f2"]}
    assert res.skipped == ()


def test_A_form_clause_31_zero_findings_gives_zero_when_the_check_ran():
    res = f.derive([clause("31")], [], ["A-06"])
    got = {e.field_key: e.value for e in res.entries}
    assert got == {"cash_receipts_count": "0", "cash_receipts_amount": "0.00", "source_finding_ids": []}


def test_A_form_a_check_missing_from_the_run_is_reported_not_guessed():
    res = f.derive([clause("34")], [row("f1", "A-09", "500.00")], ["A-09", "A-10"])
    assert res.entries == ()
    assert [s.clause_no for s in res.skipped] == ["34"] and "A-11" in res.skipped[0].reason


def test_A_form_a_check_that_failed_inside_the_run_counts_as_missing():
    res = f.derive([clause("31")], [], ["A-06"], failed_check_ids=["A-06"])
    assert res.entries == () and res.skipped[0].clause_no == "31"


def test_A_form_clause_34_adds_the_three_tds_checks():
    res = f.derive([clause("34")], [row("a", "A-09", "100.00"), row("b", "A-10", "50.25"), row("c", "A-11", "10.00")],
                   ["A-09", "A-10", "A-11"])
    got = {e.field_key: e.value for e in res.entries}
    assert got["tds_count"] == "3" and got["tds_amount"] == "160.25" and got["source_finding_ids"] == ["a", "b", "c"]
    assert "legal_rule_status" not in got


def test_A_form_clauses_without_a_derivation_or_manual_stay_for_hand_entry():
    res = f.derive([clause("18"), clause("35", "books"), clause("99", "manual")], [], ["A-05"])
    assert res.entries == ()
    assert [s.clause_no for s in res.skipped] == ["18", "35", "99"]


def test_A_form_form_26_clauses_are_never_derived_even_with_a_matching_number():
    res = f.derive([clause("21", form="form_26")], [row("f1", "A-05", "11000.00", "11000.00")], ["A-05"])
    assert res.entries == () and res.skipped[0].clause_no == "21"


def test_A_form_only_limits_the_clauses_and_the_weakest_rule_status_is_shown():
    res = f.derive([clause("21"), clause("31")], [row("x", "A-05", "1.00", "1.00", "verified"), row("y", "A-05", "2.00", "2.00", "pending")],
                   ["A-05", "A-06"], only=["21"])
    assert {e.clause_no for e in res.entries} == {"21"}
    assert [e.value for e in res.entries if e.field_key == "legal_rule_status"] == ["pending"]


def test_A_form_derivable_here_tells_which_clauses_can_be_derived():
    assert [f.derivable_here(c) for c in (clause("21"), clause("18"), clause("21", form="form_26"))] == [True, False, False]
