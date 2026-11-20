"""Package D: A-15 unusual ledger movement and A-18 related-party transactions (pure engine, literal hand-calculated values)."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.engine import audit_checks_analytic as an
from app.engine import audit_types as t

PARAMS = t.AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31))


def _facts(totals=(), related=(), vouchers=()):
    return an.AnalyticFacts(ledger_totals=tuple(totals), related=tuple(related), vouchers=tuple(vouchers),
                            previous_from=date(2025, 4, 1), previous_to=date(2026, 3, 31))


def _tot(name, this, prev, lid=None):
    return an.LedgerTotals(lid or name, name, "sales_accounts", D(this), D(prev))


def test_registry_has_both_checks():
    assert set(an.CHECKS) == {"A-15", "A-18"}


def test_A15_doubling_flagged_with_ratio_71_43_and_evidence():
    # sales credit balance: Cr 12,00,000 this year vs Cr 7,00,000 last year (signed: debit positive)
    res = an.CHECKS["A-15"](_facts([_tot("Sales", "-1200000.00", "-700000.00")]), PARAMS, ())
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.check_id == "A-15" and f.severity == t.Severity.REVIEW
    assert f.finding_key == "A-15:Sales" and f.subject_kind == "ledger"
    assert f.amount == D("500000.00")
    assert f.evidence["this_year"] == "-1200000.00" and f.evidence["previous_year"] == "-700000.00"
    assert f.evidence["change"] == "-500000.00" and f.evidence["change_percent"] == "71.43"
    assert f.evidence["min_change"] == "100000.00" and f.evidence["band_percent"] == "50.00"
    assert f.evidence["previous_from"] == "2025-04-01" and f.evidence["previous_to"] == "2026-03-31"
    assert "12,00,000.00 Cr" in f.message and "7,00,000.00 Cr" in f.message and "71.43%" in f.message
    assert res.population == ("Sales",)


def test_A15_14_29_percent_not_flagged():
    res = an.CHECKS["A-15"](_facts([_tot("Sales", "-800000.00", "-700000.00")]), PARAMS, ())
    assert res.findings == () and res.population == ("Sales",)


def test_A15_exactly_at_band_not_flagged_and_just_over_flagged():
    # 50.00% exactly: 10,50,000 vs 7,00,000 -> 3,50,000 / 7,00,000 = 50% (not outside the band)
    none = an.CHECKS["A-15"](_facts([_tot("S", "1050000.00", "700000.00")]), PARAMS, ())
    assert none.findings == ()
    over = an.CHECKS["A-15"](_facts([_tot("S", "1050000.01", "700000.00")]), PARAMS, ())
    assert len(over.findings) == 1 and over.findings[0].evidence["change_percent"] == "50.00"


def test_A15_below_minimum_amount_not_flagged_even_when_ratio_huge():
    # 20,000 -> 90,000: +350% but the change 70,000.00 is below the minimum 1,00,000.00
    res = an.CHECKS["A-15"](_facts([_tot("Rent", "90000.00", "20000.00")]), PARAMS, ())
    assert res.findings == ()


def test_A15_minimum_is_at_or_above():
    # 1,00,000 -> 2,00,000: change exactly 1,00,000.00 (flag, 100%)
    res = an.CHECKS["A-15"](_facts([_tot("Rent", "200000.00", "100000.00")]), PARAMS, ())
    assert len(res.findings) == 1


def test_A15_fall_is_flagged_too():
    # 9,00,000 -> 3,00,000: change -6,00,000, 66.67%
    res = an.CHECKS["A-15"](_facts([_tot("Salary", "300000.00", "900000.00")]), PARAMS, ())
    f = res.findings[0]
    assert f.evidence["change"] == "-600000.00" and f.evidence["change_percent"] == "66.67" and f.amount == D("600000.00")
    assert "fell" in f.message


def test_A15_no_previous_movement_flagged_without_percent():
    res = an.CHECKS["A-15"](_facts([_tot("New Loan Interest", "250000.00", "0.00")]), PARAMS, ())
    f = res.findings[0]
    assert f.evidence["change_percent"] is None and "no movement in the previous year" in f.message


def test_A15_both_zero_not_in_population():
    res = an.CHECKS["A-15"](_facts([_tot("Idle", "0.00", "0.00")]), PARAMS, ())
    assert res.findings == () and res.population == ()


def test_A15_parameters_come_from_params_not_constants():
    p = t.AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31), variance_min_amount=D("50000.00"), variance_band_percent=D("10.00"))
    res = an.CHECKS["A-15"](_facts([_tot("Sales", "-800000.00", "-700000.00")]), p, ())
    assert len(res.findings) == 1 and res.findings[0].evidence["band_percent"] == "10.00"
    assert res.findings[0].evidence["min_change"] == "50000.00"


def test_A15_negative_parameters_refused():
    p = t.AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31), variance_band_percent=D(-1))
    with pytest.raises(ValueError):
        an.CHECKS["A-15"](_facts([]), p, ())


def _v(vid, vtype, on, lines, status="posted", reverses=None, number=None):
    return t.VoucherFact(vid, vtype, number or f"N-{vid}", on, status, "n", None, None,
                         tuple(t.LineFact(lid, D(d), D(c)) for lid, d, c in lines), reverses_voucher_id=reverses)


REL = an.RelatedLedger("L1", "Rahul Sharma (Director)", "Director", True)


def test_A18_totals_voucher_ids_and_relationship():
    vs = [
        _v("v1", "payment", date(2026, 5, 1), [("L1", "40000.00", "0"), ("BANK", "0", "40000.00")]),
        _v("v2", "receipt", date(2026, 6, 1), [("L1", "0", "15000.50"), ("BANK", "15000.50", "0")]),
        _v("v3", "journal", date(2026, 7, 1), [("X", "5.00", "0"), ("Y", "0", "5.00")]),
    ]
    res = an.CHECKS["A-18"](_facts(related=[REL], vouchers=vs), PARAMS, ())
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.check_id == "A-18" and f.severity == t.Severity.INFO and f.finding_key == "A-18:L1"
    assert f.evidence["voucher_ids"] == ["v1", "v2"] and f.evidence["total_debit"] == "40000.00" and f.evidence["total_credit"] == "15000.50"
    assert f.evidence["relationship"] == "Director" and f.evidence["voucher_count"] == 2
    assert f.amount == D("55000.50")
    assert "Rahul Sharma (Director)" in f.message and "40,000.00" in f.message and "15,000.50" in f.message
    assert res.population == ("v1", "v2")


def test_A18_inactive_flag_and_out_of_period_and_reversed_pairs_ignored():
    inactive = an.RelatedLedger("L2", "Old Relative", "Relative", False)
    vs = [
        _v("v1", "payment", date(2026, 5, 1), [("L2", "100.00", "0"), ("B", "0", "100.00")]),
        _v("v2", "payment", date(2025, 3, 31), [("L1", "100.00", "0"), ("B", "0", "100.00")]),    # before period
        _v("v3", "payment", date(2026, 8, 1), [("L1", "700.00", "0"), ("B", "0", "700.00")], status="reversed"),
        _v("v4", "payment", date(2026, 8, 2), [("L1", "0", "700.00"), ("B", "700.00", "0")], reverses="v3"),
        _v("v5", "payment", date(2026, 9, 1), [("L1", "900.00", "0"), ("B", "0", "900.00")]),
    ]
    res = an.CHECKS["A-18"](_facts(related=[REL, inactive], vouchers=vs), PARAMS, ())
    assert len(res.findings) == 1 and res.findings[0].evidence["voucher_ids"] == ["v5"]
    assert res.findings[0].evidence["total_debit"] == "900.00"


def test_A18_flagged_without_postings_gives_note_not_finding():
    res = an.CHECKS["A-18"](_facts(related=[REL], vouchers=[]), PARAMS, ())
    assert res.findings == () and any("Rahul Sharma (Director)" in n for n in res.notes)


def test_A18_two_lines_same_voucher_counts_voucher_once():
    vs = [_v("v1", "journal", date(2026, 5, 1), [("L1", "100.00", "0"), ("L1", "0", "30.00"), ("Z", "0", "70.00")])]
    f = an.CHECKS["A-18"](_facts(related=[REL], vouchers=vs), PARAMS, ()).findings[0]
    assert f.evidence["voucher_count"] == 1 and f.evidence["total_debit"] == "100.00" and f.evidence["total_credit"] == "30.00"


def test_previous_period_shift_one_year():
    assert an.previous_period(date(2026, 4, 1), date(2027, 3, 31)) == (date(2025, 4, 1), date(2026, 3, 31))
    assert an.previous_period(date(2028, 2, 29), date(2028, 3, 31)) == (date(2027, 2, 28), date(2027, 3, 31))
