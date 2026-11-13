"""TDS / TCS engine (T-01 .. T-17, T-50). Every expected figure is hand-calculated and typed as a literal."""

from datetime import date
from decimal import Decimal as D

from tds_helpers import FY, ctx, line, prior
from tds_helpers import cert as make_cert

from app.engine.tds_calc import compute_items, round_tax

Z = D("0.00")


def one(item, c=None):
    out = compute_items([item], c or ctx())
    assert out.errors == (), out.errors
    return out.items[0]


def errors_of(items, c=None):
    out = compute_items(items, c or ctx())
    return [(e.rule_id, e.line_no, e.message) for e in out.errors]


# ---- T-01 / T-02: the Act is chosen by the earlier date ------------------------------------------------------------
def test_T01_payment_on_31_March_2026_is_taxed_under_the_1961_act():
    r = one(line("co", "contractor", "100000", pay=date(2026, 3, 31)))
    assert (r.act, r.section_ref, r.table_ref, r.rate_rule_id) == ("it_act_1961", "194C", None, "c61-ot")
    assert (r.rate_applied, r.taxable_base, r.tds_amount) == (D(2), D("100000.00"), D("2000.00"))


def test_T01_payment_on_1_April_2026_is_taxed_under_the_2025_act():
    r = one(line("co", "contractor", "100000", pay=date(2026, 4, 1)))
    assert (r.act, r.section_ref, r.table_ref, r.rate_rule_id) == ("it_act_2025", "393(1)", "Sl.6(i)", "c25-ot")
    assert (r.rate_applied, r.tds_amount, r.verification_status, r.warnings) == (D("2.5"), D("2500.00"), "secondary_verified", ())


def test_T01_credit_in_March_paid_in_April_uses_the_earlier_date():
    r = one(line("co", "contractor", "100000", pay=date(2026, 4, 5), credit=date(2026, 3, 25)))
    assert (r.event_date, r.act, r.tds_amount) == (date(2026, 3, 25), "it_act_1961", D("2000.00"))


def test_T01_payment_in_March_credited_in_April_uses_the_earlier_date():
    r = one(line("co", "contractor", "100000", pay=date(2026, 3, 30), credit=date(2026, 4, 2)))
    assert (r.event_date, r.act, r.tds_amount) == (date(2026, 3, 30), "it_act_1961", D("2000.00"))


def test_T01_a_date_is_required():
    e = errors_of([line("co", "contractor", "100000")])
    assert [x[:2] for x in e] == [("T-01", 1)]
    assert e[0][2].startswith("Item 1: enter the payment date or the credit date")


def test_T01_date_outside_every_financial_year_is_refused():
    e = errors_of([line("co", "contractor", "100000", pay=date(2026, 4, 1))], ctx(fy=lambda d: None))
    assert [x[:2] for x in e] == [("T-01", 1)]
    assert "01-04-2026" in e[0][2]


def test_T02_no_rule_in_force_is_refused_with_the_section_and_date():
    e = errors_of([line("co", "contractor", "100000", pay=date(2025, 3, 10))])
    assert [x[:2] for x in e] == [("T-02", 1)]
    assert e[0][2].startswith("Item 1: no rule for 194C on 10-03-2025")


def test_T02_pending_rule_is_used_with_a_warning_and_status():
    r = one(line("co", "contractor", "100000", pay=date(2026, 3, 31)))
    assert r.verification_status == "pending"
    assert r.warnings[0].startswith("T-02: the rate rule for 194C is pending verification")


# ---- T-04: deductee group ------------------------------------------------------------------------------------------
def test_T04_individual_pays_the_lower_contractor_rate_company_the_higher():
    ind = one(line("ind", "contractor", "100000", pay=date(2026, 3, 31)))
    co = one(line("co", "contractor", "100000", pay=date(2026, 3, 31)))
    assert (ind.rate_applied, ind.tds_amount, ind.rate_rule_id) == (D(1), D("1000.00"), "c61-ih")
    assert (co.rate_applied, co.tds_amount, co.rate_rule_id) == (D(2), D("2000.00"), "c61-ot")


def test_T04_a_row_for_group_any_applies_to_every_deductee_type():
    a = one(line("ind", "technical_fees", "100000", pay=date(2026, 5, 1)))
    b = one(line("co", "technical_fees", "100000", pay=date(2026, 5, 1)))
    assert (a.tds_amount, b.tds_amount) == (D("2000.00"), D("2000.00"))


# ---- T-07: thresholds, threshold crossing in the year --------------------------------------------------------------
def test_T07_amount_equal_to_the_threshold_is_not_taxed():
    r = one(line("co", "contractor", "30000", pay=date(2025, 6, 10)))
    assert (r.tds_amount, r.rate_reason, r.taxable_base, r.threshold_crossed) == (Z, "below_threshold", Z, False)


def test_T07_annual_threshold_crossing_mid_year_catches_up_and_sets_off_earlier_tax():
    d = date(2025, 6, 10)
    out = compute_items([line("co", "contractor", a, pay=d) for a in ("20000", "25000", "40000", "30000")], ctx())
    assert out.errors == ()
    got = [(r.cumulative_before, r.cumulative_after, r.taxable_base, r.tax_already_on_base, r.tds_amount, r.threshold_crossed)
           for r in out.items]
    assert got == [
        (Z, D("20000.00"), Z, Z, Z, False),  # below every threshold
        (D("20000.00"), D("45000.00"), Z, Z, Z, False),
        (D("45000.00"), D("85000.00"), D("40000.00"), Z, D("800.00"), False),  # single payment above 30,000: 2% of 40,000
        (D("85000.00"), D("115000.00"), D("115000.00"), D("800.00"), D("1500.00"), True),  # 2% of 1,15,000 = 2,300 less 800
    ]
    assert [r.rate_reason for r in out.items] == ["below_threshold", "below_threshold", "normal", "normal"]


def test_T07_after_the_year_total_crossed_every_payment_is_taxed_in_full():
    r = one(line("co", "contractor", "10000", pay=date(2025, 6, 10)), ctx(priors=prior("co", "contractor", "115000", "2300")))
    assert (r.taxable_base, r.tax_already_on_base, r.tds_amount, r.threshold_crossed) == (D("10000.00"), Z, D("200.00"), False)


def test_T07_the_position_of_another_deductee_does_not_count():
    r = one(line("ind", "contractor", "20000", pay=date(2025, 6, 10)), ctx(priors=prior("co", "contractor", "500000", "10000")))
    assert (r.cumulative_before, r.tds_amount) == (Z, Z)


def test_T07_excess_only_taxes_the_part_above_the_threshold_once_crossed():
    # 194Q style: 0.1% of the part above 50,00,000 only. Before 40,00,000, this payment 30,00,000: excess = 20,00,000.
    c = ctx(priors=prior("co", "purchase_of_goods", "4000000"), flags={FY: True})
    r = one(line("co", "purchase_of_goods", "3000000", pay=date(2026, 6, 10)), c)
    assert (r.taxable_base, r.tds_amount, r.threshold_crossed, r.cumulative_after) == (D("2000000.00"), D("2000.00"), True, D("7000000.00"))
    again = one(line("co", "purchase_of_goods", "1000000", pay=date(2026, 6, 20)),
                ctx(priors=prior("co", "purchase_of_goods", "7000000", "2000"), flags={FY: True}))
    assert (again.taxable_base, again.tds_amount, again.threshold_crossed) == (D("1000000.00"), D("1000.00"), False)


def test_T07_excess_only_below_the_threshold_is_nil():
    c = ctx(priors=prior("co", "purchase_of_goods", "1000000"), flags={FY: True})
    r = one(line("co", "purchase_of_goods", "2000000", pay=date(2026, 6, 10)), c)
    assert (r.taxable_base, r.tds_amount, r.rate_reason) == (Z, Z, "below_threshold")


def test_T07_monthly_threshold_single_month_payment_above_it_is_taxed_in_full():
    r = one(line("co", "rent_land_building", "60000", pay=date(2026, 6, 15)))
    assert (r.taxable_base, r.tds_amount, r.threshold_crossed) == (D("60000.00"), D("6000.00"), True)


def test_T07_monthly_threshold_exact_amount_is_not_taxed():
    r = one(line("co", "rent_land_building", "50000", pay=date(2026, 6, 15)))
    assert (r.tds_amount, r.rate_reason) == (Z, "below_threshold")


def test_T07_monthly_amounts_add_up_inside_the_month_and_restart_next_month():
    items = [line("co", "rent_land_building", "30000", pay=date(2026, 6, 5)),
             line("co", "rent_land_building", "30000", pay=date(2026, 6, 25)),
             line("co", "rent_land_building", "10000", pay=date(2026, 6, 28)),
             line("co", "rent_land_building", "40000", pay=date(2026, 7, 5))]
    out = compute_items(items, ctx())
    assert out.errors == ()
    assert [(r.taxable_base, r.tds_amount) for r in out.items] == [
        (Z, Z), (D("60000.00"), D("6000.00")), (D("10000.00"), D("1000.00")), (Z, Z)]


def test_T07_prior_month_amounts_from_the_books_count():
    c = ctx(priors=prior("co", "rent_land_building", "30000", months={"2026-06": D(30000)}))
    r = one(line("co", "rent_land_building", "30000", pay=date(2026, 6, 25)), c)
    assert (r.taxable_base, r.tds_amount) == (D("60000.00"), D("6000.00"))


# ---- T-08: missing PAN ---------------------------------------------------------------------------------------------
def test_T08_missing_pan_uses_the_higher_rate():
    r = one(line("nopan", "contractor", "100000", pay=date(2025, 6, 10)))
    assert (r.rate_applied, r.rate_reason, r.tds_amount) == (D(20), "no_pan", D("20000.00"))
    assert any(w.startswith("T-08") for w in r.warnings)


def test_T08_invalid_pan_uses_the_higher_rate_and_valid_pan_the_normal_one():
    bad = one(line("badpan", "contractor", "100000", pay=date(2025, 6, 10)))
    ok = one(line("co", "contractor", "100000", pay=date(2025, 6, 10)))
    assert (bad.tds_amount, ok.tds_amount) == (D("20000.00"), D("2000.00"))


def test_T08_a_certificate_is_not_applied_when_the_pan_is_not_valid():
    cert = make_cert("c1", "nopan", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31))
    r = one(line("nopan", "contractor", "100000", pay=date(2026, 5, 5), cert="c1"), ctx(certs=[cert]))
    assert (r.rate_reason, r.lower_cert_id, r.tds_amount) == ("no_pan", None, D("20000.00"))
    assert any(w.startswith("T-12") for w in r.warnings)


# ---- T-12: lower / nil deduction certificate -----------------------------------------------------------------------
def test_T12_certificate_within_limit_applies_its_rate():
    cert = make_cert("c1", "co", "0.5", "200000", date(2026, 4, 1), date(2027, 3, 31))
    r = one(line("co", "contractor", "150000", pay=date(2026, 5, 5), cert="c1"), ctx(certs=[cert]))
    assert (r.rate_reason, r.lower_cert_id, r.rate_applied, r.taxable_base, r.tds_amount) == (
        "lower_certificate", "c1", D("0.5"), D("150000.00"), D("750.00"))


def test_T12_part_of_a_payment_above_the_certificate_limit_is_taxed_at_the_normal_rate():
    # limit 2,00,000, 1,50,000 already used: 50,000 at 0.5% = 250 and 50,000 at 2.5% = 1,250 -> 1,500
    cert = make_cert("c1", "co", "0.5", "200000", date(2026, 4, 1), date(2027, 3, 31), used="150000")
    r = one(line("co", "contractor", "100000", pay=date(2026, 6, 5), cert="c1"),
            ctx(certs=[cert], priors=prior("co", "contractor", "150000", "750")))
    assert (r.rate_reason, r.rate_applied, r.tds_amount) == ("lower_certificate", D("0.5"), D("1500.00"))
    assert any("covers 50,000.00 at 0.5%" in w for w in r.warnings)


def test_T12_an_exhausted_certificate_gives_way_to_the_normal_rate():
    cert = make_cert("c1", "co", "0.5", "200000", date(2026, 4, 1), date(2027, 3, 31), used="200000")
    r = one(line("co", "contractor", "100000", pay=date(2026, 6, 5), cert="c1"),
            ctx(certs=[cert], priors=prior("co", "contractor", "350000", "1000")))
    assert (r.rate_reason, r.lower_cert_id, r.tds_amount) == ("normal", None, D("2500.00"))
    assert any("used up" in w for w in r.warnings)


def test_T12_two_items_of_one_voucher_share_the_certificate_limit():
    cert = make_cert("c1", "co", "0.5", "100000", date(2026, 4, 1), date(2027, 3, 31))
    out = compute_items([line("co", "contractor", "60000", pay=date(2026, 6, 5), cert="c1"),
                         line("co", "contractor", "60000", pay=date(2026, 6, 6), cert="c1")], ctx(certs=[cert]))
    assert out.errors == ()
    # item 1: 60,000 at 0.5% = 300; item 2: total 1,20,000 crosses 1,00,000 -> base 1,20,000, covered 40,000:
    # 40,000 at 0.5% = 200 and 80,000 at 2.5% = 2,000 -> 2,200 less 300 already = 1,900
    assert [r.tds_amount for r in out.items] == [D("300.00"), D("1900.00")]


def test_T12_nil_certificate_gives_zero_tax_and_the_reason():
    cert = make_cert("c1", "co", "0", "500000", date(2026, 4, 1), date(2027, 3, 31))
    r = one(line("co", "contractor", "100000", pay=date(2026, 5, 5), cert="c1"), ctx(certs=[cert]))
    assert (r.rate_reason, r.lower_cert_id, r.tds_amount, r.taxable_base) == ("nil_certificate", "c1", Z, D("100000.00"))


def test_T12_certificate_is_valid_on_its_last_day_and_not_the_day_after():
    cert = make_cert("c1", "co", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31), no="N/26/9")
    ok = one(line("co", "contractor", "100000", pay=date(2027, 3, 31), cert="c1"), ctx(certs=[cert]))
    assert ok.tds_amount == D("500.00")
    e = errors_of([line("co", "contractor", "100000", pay=date(2027, 4, 1), cert="c1")], ctx(certs=[cert]))
    assert [x[:2] for x in e] == [("T-12", 1)]
    assert "N/26/9 is valid from 01-04-2026 to 31-03-2027" in e[0][2]


def test_T12_certificate_does_not_cover_a_date_before_its_start():
    cert = make_cert("c1", "co", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31))
    e = errors_of([line("co", "contractor", "100000", pay=date(2026, 3, 31), cert="c1")], ctx(certs=[cert]))
    assert [x[:2] for x in e] == [("T-12", 1)]


def test_T12_certificate_rate_must_be_lower_than_the_normal_rate():
    cert = make_cert("c1", "co", "2.5", "500000", date(2026, 4, 1), date(2027, 3, 31))
    e = errors_of([line("co", "contractor", "100000", pay=date(2026, 5, 5), cert="c1")], ctx(certs=[cert]))
    assert [x[:2] for x in e] == [("T-12", 1)]
    assert "not lower than the normal rate 2.5%" in e[0][2]


def test_T12_certificate_of_another_deductee_or_nature_or_unknown_is_refused():
    other = make_cert("c1", "ind", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31))
    wrong_nature = make_cert("c2", "co", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31), nature="technical_fees")
    c = ctx(certs=[other, wrong_nature])
    for cid in ("c1", "c2", "nope"):
        e = errors_of([line("co", "contractor", "100000", pay=date(2026, 5, 5), cert=cid)], c)
        assert [x[:2] for x in e] == [("T-12", 1)], cid


def test_T12_certificate_on_a_payment_below_the_threshold_is_not_used():
    cert = make_cert("c1", "co", "0.5", "500000", date(2026, 4, 1), date(2027, 3, 31))
    r = one(line("co", "contractor", "20000", pay=date(2026, 5, 5), cert="c1"), ctx(certs=[cert]))
    assert (r.rate_reason, r.lower_cert_id, r.tds_amount) == ("below_threshold", None, Z)


# ---- T-06: rounding ------------------------------------------------------------------------------------------------
def test_T06_round_tax_is_nearest_rupee_halves_up():
    assert [round_tax(D(x)) for x in ("0.49", "0.50", "2.50", "1499.50", "1500.49", "0")] == [
        D("0.00"), D("1.00"), D("3.00"), D("1500.00"), D("1500.00"), D("0.00")]


def test_T06_tax_of_half_a_rupee_rounds_up():
    r = one(line("co", "technical_fees", "75025", pay=date(2026, 5, 1)))  # 2% of 75,025.00 = 1,500.50
    assert r.tds_amount == D("1501.00")


def test_T06_tax_below_half_a_rupee_rounds_down():
    r = one(line("co", "technical_fees", "75024", pay=date(2026, 5, 1)))  # 2% of 75,024.00 = 1,500.48
    assert r.tds_amount == D("1500.00")


# ---- T-03 / T-09 / T-15 / T-16 / T-17 ------------------------------------------------------------------------------
def test_T03_salary_needs_the_typed_tax_and_is_rounded_to_the_rupee():
    r = one(line("ind", "salary", "50000", pay=date(2026, 4, 10), manual="12345.40"))
    assert (r.act, r.section_ref, r.rate_reason, r.tds_amount, r.rate_rule_id) == ("it_act_2025", "392", "manual_salary", D("12345.00"), None)
    e = errors_of([line("ind", "salary", "50000", pay=date(2026, 4, 10))])
    assert [x[:2] for x in e] == [("T-03", 1)]


def test_T03_flat_natures_refuse_a_typed_tax():
    e = errors_of([line("co", "contractor", "100000", pay=date(2026, 4, 10), manual="500")])
    assert [x[:2] for x in e] == [("T-03", 1)]


def test_T03_unknown_nature_and_tcs_nature_in_a_tds_block_are_refused():
    assert [x[:2] for x in errors_of([line("co", "magic", "1000", pay=date(2026, 4, 10))])] == [("T-03", 1)]
    assert [x[:2] for x in errors_of([line("co", "tcs_motor_vehicle", "1000", pay=date(2026, 4, 10))])] == [("T-03", 1)]


def test_T09_party_without_a_deductee_row_is_refused():
    assert [x[:2] for x in errors_of([line("ghost", "contractor", "100000", pay=date(2026, 4, 10))])] == [("T-09", 1)]


def test_T15_purchase_of_goods_needs_the_buyer_flag_for_the_year():
    e = errors_of([line("co", "purchase_of_goods", "6000000", pay=date(2026, 6, 10))])
    assert [x[:2] for x in e] == [("T-15", 1)]


def test_T15_buyer_flag_no_means_no_deduction_with_a_warning():
    r = one(line("co", "purchase_of_goods", "6000000", pay=date(2026, 6, 10)), ctx(flags={FY: False}))
    assert (r.tds_amount, r.rate_reason) == (Z, "below_threshold")
    assert r.warnings[0].startswith("T-15")


def test_T15_purchase_of_goods_without_pan_uses_the_higher_rate_on_the_excess():
    r = one(line("nopan", "purchase_of_goods", "1000000", pay=date(2026, 6, 10)),
            ctx(priors=prior("nopan", "purchase_of_goods", "7000000"), flags={FY: True}))
    assert (r.rate_applied, r.tds_amount) == (D(5), D("50000.00"))


def test_T16_amount_must_be_positive_with_two_decimals():
    for bad in ("0", "-5", "100.005"):
        e = errors_of([line("co", "contractor", bad, pay=date(2026, 4, 10))])
        assert [x[:2] for x in e] == [("T-16", 1)], bad


def test_T16_salary_tax_cannot_exceed_the_amount():
    e = errors_of([line("ind", "salary", "1000", pay=date(2026, 4, 10), manual="2000")])
    assert [x[:2] for x in e] == [("T-16", 1)]


def test_T17_tcs_on_the_part_above_the_limit_only():
    # motor vehicle: 1% of the value above 10,00,000: (15,00,000 - 10,00,000) * 1% = 5,000
    r = one(line("co", "tcs_motor_vehicle", "1500000", pay=date(2026, 6, 10)), ctx(kind="tcs"))
    assert (r.taxable_base, r.tds_amount) == (D("500000.00"), D("5000.00"))


def test_T17_a_tds_nature_in_a_tcs_block_is_refused():
    e = errors_of([line("co", "contractor", "100000", pay=date(2026, 6, 10))], ctx(kind="tcs"))
    assert [x[:2] for x in e] == [("T-17", 1)]


# ---- T-50: rule status ----------------------------------------------------------------------------------------------
def test_T50_status_lists_pending_sources():
    out = compute_items([line("co", "rent_land_building", "60000", pay=date(2026, 6, 15))], ctx())
    assert out.rule_status == {
        "worst": "pending", "tables": {"rate": "pending", "section": "pending"},
        "pending_sources": ["src rent25", "src rent_land_building it_act_2025"],
    }


def test_T50_all_secondary_verified_has_no_pending_source():
    out = compute_items([line("co", "contractor", "100000", pay=date(2026, 4, 1))], ctx())
    assert out.rule_status == {
        "worst": "secondary_verified", "tables": {"rate": "secondary_verified", "section": "secondary_verified"},
        "pending_sources": [],
    }


# ---- T-14 / T-16: the generated tax line ------------------------------------------------------------------------------
def _res(item_no, who, nature, tax):
    from app.engine.tds_types import TdsItemResult

    return TdsItemResult(item_no, who, nature, "it_act_2025", "393(1)", None, "r", date(2026, 6, 1), D("100000.00"), Z, D("100000.00"),
                         False, D("100000.00"), D(2), "normal", None, Z, D(tax), "secondary_verified")


def test_T16_payment_reduces_the_bank_line_and_adds_the_payable_line():
    from app.engine.tds_calc import expand_lines

    lines = [("co", D("100000.00"), Z), ("bank", Z, D("100000.00"))]
    new, line_of, errs = expand_lines("payment", "tds", lines, [_res(1, "co", "contractor", "2000.00")], {"contractor": "tdsp"}, {"bank"})
    assert errs == []
    assert new == [("co", D("100000.00"), Z), ("bank", Z, D("98000.00")), ("tdsp", Z, D("2000.00"))]
    assert line_of == {1: 3}


def test_T16_purchase_reduces_the_party_credit_line():
    from app.engine.tds_calc import expand_lines

    lines = [("exp", D("100000.00"), Z), ("co", Z, D("100000.00"))]
    new, line_of, errs = expand_lines("purchase", "tds", lines, [_res(1, "co", "contractor", "2000.00")], {"contractor": "tdsp"})
    assert errs == []
    assert new == [("exp", D("100000.00"), Z), ("co", Z, D("98000.00")), ("tdsp", Z, D("2000.00"))]
    assert line_of == {1: 3}


def test_T16_item_without_tax_adds_no_line():
    from app.engine.tds_calc import expand_lines

    lines = [("exp", D("10.00"), Z), ("co", Z, D("10.00"))]
    new, line_of, errs = expand_lines("journal", "tds", lines, [_res(1, "co", "contractor", "0.00")], {})
    assert (new, line_of, errs) == (lines, {}, [])


def test_T16_tax_larger_than_the_party_line_is_refused():
    from app.engine.tds_calc import expand_lines

    lines = [("exp", D("1000.00"), Z), ("co", Z, D("1000.00"))]
    _, _, errs = expand_lines("purchase", "tds", lines, [_res(1, "co", "contractor", "2000.00")], {"contractor": "tdsp"})
    assert [(e.rule_id, e.line_no) for e in errs] == [("T-16", 1)]


def test_T16_tds_on_a_sales_voucher_is_refused():
    from app.engine.tds_calc import expand_lines

    _, _, errs = expand_lines("sales", "tds", [("co", D("1.00"), Z), ("s", Z, D("1.00"))], [], {})
    assert [e.rule_id for e in errs] == ["T-16"]


def test_T14_missing_payable_ledger_is_refused():
    from app.engine.tds_calc import expand_lines

    lines = [("exp", D("100000.00"), Z), ("co", Z, D("100000.00"))]
    _, _, errs = expand_lines("purchase", "tds", lines, [_res(1, "co", "contractor", "2000.00")], {})
    assert [(e.rule_id, e.line_no) for e in errs] == [("T-14", 1)]


def test_T17_tcs_on_sales_adds_the_tax_to_the_party_debit_line():
    from app.engine.tds_calc import expand_lines

    lines = [("buyer", D("1500000.00"), Z), ("sales", Z, D("1500000.00"))]
    new, line_of, errs = expand_lines("sales", "tcs", lines, [_res(1, "buyer", "tcs_motor_vehicle", "5000.00")], {"tcs_motor_vehicle": "tcsp"})
    assert errs == []
    assert new == [("buyer", D("1505000.00"), Z), ("sales", Z, D("1500000.00")), ("tcsp", Z, D("5000.00"))]
    assert line_of == {1: 3}
