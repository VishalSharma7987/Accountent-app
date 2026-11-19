"""Package B: fixed asset register and Companies Act book depreciation (F-20 .. F-27). Pure engine, no database.

Every expected value is typed literally (hand-calculated; see docs/PHASE6_PLAN.md "Book depreciation").
"""

from datetime import date
from decimal import Decimal

import pytest

from app.engine import final_assets as fa
from app.engine.final_types import AssetBookSetup, AssetEvent, EventKind, JournalLineDraft

D = Decimal
FY_START, FY_END = date(2026, 4, 1), date(2027, 3, 31)


def setup(events, *, method="slm", life="10", residual="0", depreciable=True, block="furniture_fittings", asset_id="A1"):
    return AssetBookSetup(asset_id, "FA-1", "Asset", depreciable, method, D(life), D(residual), block, tuple(events))


def opening(cost, acc="0", on=date(2026, 4, 1), use=date(2026, 4, 1)):
    return AssetEvent(EventKind.OPENING, on, D(cost), use, D(acc))


def purchase(cost, on, use=None):
    return AssetEvent(EventKind.PURCHASE, on, D(cost), use or on)


def addition(cost, on, use=None):
    return AssetEvent(EventKind.ADDITION, on, D(cost), use or on)


def disposal(proceeds, on):
    return AssetEvent(EventKind.DISPOSAL, on, D(proceeds))


# ------------------------------------------------------------------------------------------------ day counts


def test_F23_days_are_counted_inclusively_both_ends():
    assert fa.days_inclusive(date(2026, 10, 1), date(2027, 3, 31)) == 182
    assert fa.days_inclusive(date(2026, 11, 15), date(2027, 3, 31)) == 137
    assert fa.days_inclusive(date(2026, 4, 1), date(2026, 4, 1)) == 1


def test_F23_days_in_year_follows_the_leap_day():
    assert fa.days_in_year(date(2026, 4, 1), date(2027, 3, 31)) == 365
    assert fa.days_in_year(date(2027, 4, 1), date(2028, 3, 31)) == 366


# ------------------------------------------------------------------------------------------------ WDV rate


def test_F23_wdv_rate_cost_1_00_000_residual_4_000_life_2_is_80_percent():
    assert fa.wdv_rate_percent(D("100000"), D("4000"), D("2")) == D("80.00")


def test_F23_wdv_rate_is_rounded_half_up_to_two_decimals_known_tables():
    assert fa.wdv_rate_percent(D("100000"), D("5000"), D("15")) == D("18.10")
    assert fa.wdv_rate_percent(D("100000"), D("5000"), D("10")) == D("25.89")


def test_F23_wdv_rate_refuses_zero_residual():
    with pytest.raises(ValueError):
        fa.wdv_rate_percent(D("100000"), D("0"), D("10"))


# ------------------------------------------------------------------------------------------------ SLM


def test_F23_slm_furniture_1_00_000_life_10_full_year_is_10_000():
    [line] = fa.book_depreciation(setup([opening("100000")]), FY_START, FY_END)
    assert line.depreciation == D("10000.00")
    assert (line.cost, line.opening_accumulated, line.closing_accumulated) == (D("100000.00"), D("0.00"), D("10000.00"))
    assert (line.days_used, line.days_in_year, line.method) == (365, 365, "slm")
    assert line.wdv_rate_percent is None


def test_F23_slm_machine_put_to_use_01_10_2026_182_days_is_6_315_98():
    s = setup([purchase("200000", date(2026, 10, 1))], life="15", residual="10000", block="plant_machinery_general")
    [line] = fa.book_depreciation(s, FY_START, FY_END)
    assert line.depreciation == D("6315.98")
    assert line.days_used == 182
    assert line.closing_accumulated == D("6315.98")


def test_F23_each_addition_is_its_own_tranche_with_the_same_residual_percentage():
    # opening 1,00,000 (accumulated 20,000), residual 5,000 = 5%; addition 50,000 on 01-10-2026 gets residual 2,500
    # opening: (100000 - 5000) / 10 = 9,500.00 ; addition: (50000 - 2500) / 10 x 182 / 365 = 864500 / 365 = 2,368.49
    s = setup([opening("100000", "20000"), addition("50000", date(2026, 10, 1))], residual="5000")
    [line] = fa.book_depreciation(s, FY_START, FY_END)
    assert line.depreciation == D("11868.49")
    assert line.cost == D("150000.00")
    assert line.opening_accumulated == D("20000.00")
    assert line.closing_accumulated == D("31868.49")
    assert [t["depreciation"] for t in line.details["tranches"]] == ["9500.00", "2368.49"]


def test_F25_depreciation_never_exceeds_cost_less_residual():
    s = setup([opening("100000", "95000")])  # only 5,000 left to depreciate
    [line] = fa.book_depreciation(s, FY_START, FY_END)
    assert line.depreciation == D("5000.00")
    assert line.closing_accumulated == D("100000.00")


def test_F25_a_fully_depreciated_asset_gets_zero():
    [line] = fa.book_depreciation(setup([opening("100000", "100000")]), FY_START, FY_END)
    assert line.depreciation == D("0.00")


def test_F23_earlier_years_are_replayed_from_the_put_to_use_date():
    # cost 36,500 life 10 put to use 01-10-2025: FY 2025-26 = 182 days = 1,820.00; FY 2026-27 = 3,650.00
    s = setup([purchase("36500", date(2025, 10, 1))])
    [line] = fa.book_depreciation(s, FY_START, FY_END)
    assert (line.opening_accumulated, line.depreciation, line.closing_accumulated) == (D("1820.00"), D("3650.00"), D("5470.00"))


def test_F23_an_asset_put_to_use_after_the_year_end_has_no_line():
    s = setup([purchase("36500", date(2027, 4, 5))])
    assert fa.book_depreciation(s, FY_START, FY_END) == []


def test_F23_a_non_depreciable_asset_has_no_line():
    assert fa.book_depreciation(setup([opening("500000")], depreciable=False), FY_START, FY_END) == []


# ------------------------------------------------------------------------------------------------ WDV years


def test_F23_F25_wdv_cost_1_00_000_residual_4_000_life_2_three_years():
    s = setup([opening("100000")], method="wdv", life="2", residual="4000")
    [y1] = fa.book_depreciation(s, FY_START, FY_END)
    assert (y1.wdv_rate_percent, y1.depreciation, y1.closing_accumulated) == (D("80.00"), D("80000.00"), D("80000.00"))
    s2 = setup([opening("100000", "80000", on=date(2027, 4, 1), use=date(2026, 4, 1))], method="wdv", life="2", residual="4000")
    [y2] = fa.book_depreciation(s2, date(2027, 4, 1), date(2028, 3, 31))
    assert (y2.depreciation, y2.closing_accumulated) == (D("16000.00"), D("96000.00"))
    s3 = setup([opening("100000", "96000", on=date(2028, 4, 1), use=date(2026, 4, 1))], method="wdv", life="2", residual="4000")
    [y3] = fa.book_depreciation(s3, date(2028, 4, 1), date(2029, 3, 31))
    assert y3.depreciation == D("0.00")


# ------------------------------------------------------------------------------------------------ disposal


def test_F22_F23_disposal_stops_depreciation_on_the_disposal_date_both_days_counted():
    # cost 36,500 life 10 opening 01-04-2026, sold 30-09-2026: 183 days -> 3,650 x 183 / 365 = 1,830.00
    s = setup([opening("36500"), disposal("30000", date(2026, 9, 30))])
    [line] = fa.book_depreciation(s, FY_START, FY_END)
    assert (line.days_used, line.depreciation, line.closing_accumulated) == (183, D("1830.00"), D("1830.00"))
    w = fa.disposal_working(line.cost, line.closing_accumulated, D("30000"))
    assert (w.proceeds, w.book_value, w.profit_or_loss) == (D("30000.00"), D("34670.00"), D("-4670.00"))


def test_F22_profit_on_sale_is_proceeds_less_book_value():
    w = fa.disposal_working(D("100000"), D("40000"), D("65000.50"))
    assert (w.book_value, w.profit_or_loss) == (D("60000.00"), D("5000.50"))


def test_F23_an_asset_disposed_before_the_year_has_no_line():
    s = setup([opening("36500", on=date(2025, 4, 1)), disposal("1000", date(2026, 3, 31))])
    assert fa.book_depreciation(s, FY_START, FY_END) == []


# ------------------------------------------------------------------------------------------------ register


def test_F20_register_row_opening_additions_disposal_and_net_block():
    s = setup([opening("100000", "20000"), addition("50000", date(2026, 10, 1))], residual="5000")
    r = fa.register_row(s, FY_START, FY_END)
    assert (r.opening_cost, r.additions, r.disposals_cost, r.closing_cost) == (D("100000.00"), D("50000.00"), D("0.00"), D("150000.00"))
    assert (r.opening_accumulated, r.depreciation, r.disposal_accumulated, r.closing_accumulated) == (
        D("20000.00"), D("11868.49"), D("0.00"), D("31868.49"))
    assert r.net_block == D("118131.51")


def test_F22_register_row_with_a_disposal_removes_cost_and_accumulated():
    s = setup([opening("36500"), disposal("30000", date(2026, 9, 30))])
    r = fa.register_row(s, FY_START, FY_END)
    assert (r.closing_cost, r.disposals_cost, r.disposal_accumulated, r.closing_accumulated, r.net_block) == (
        D("0.00"), D("36500.00"), D("1830.00"), D("0.00"), D("0.00"))


def test_F20_a_purchase_dated_in_the_year_but_put_to_use_next_year_is_in_the_closing_cost_without_depreciation():
    s = setup([purchase("36500", date(2027, 3, 25), date(2027, 4, 5))])
    r = fa.register_row(s, FY_START, FY_END)
    assert (r.additions, r.closing_cost, r.depreciation, r.net_block) == (D("36500.00"), D("36500.00"), D("0.00"), D("36500.00"))


# ------------------------------------------------------------------------------------------------ journal


def test_F26_journal_has_one_debit_and_credits_summed_per_accumulated_ledger_zero_lines_left_out():
    from app.engine.final_types import BookDepreciationLine as L

    def line(asset, dep):
        return L(asset, "slm", D("1"), D("0"), None, 365, 365, D(dep), D(dep))

    lines = [line("A1", "10000.00"), line("A2", "6315.98"), line("A3", "0.00"), line("A4", "500.00")]
    journal = fa.depreciation_journal_lines(lines, "EXP", {"A1": "ACC", "A2": "ACC", "A3": "ACC", "A4": "ASSET4"})
    assert journal == [
        JournalLineDraft("EXP", debit=D("16815.98")),
        JournalLineDraft("ACC", credit=D("16315.98")),
        JournalLineDraft("ASSET4", credit=D("500.00")),
    ]


# ------------------------------------------------------------------------------------------------ F-20 / F-24 setup rules


CLASS = fa.Sched2Rule("furniture_fittings", "Furniture", D("10"), D("5"), date(2014, 4, 1), None, "pending", "Sched II")


def ids(findings, severity=None):
    return sorted(f.rule_id for f in findings if severity is None or f.severity == severity)


def test_F20_depreciable_asset_needs_block_life_method_and_a_class_or_override_reason():
    f = fa.validate_asset_setup(is_depreciable=True, it_block_key=None, method=None, life=None, residual=D("0"), class_rule=None,
                                override_reason=None)
    assert ids(f, "error") == ["F-20", "F-20", "F-20", "F-20"]


def test_F20_a_non_depreciable_asset_needs_nothing_else():
    assert fa.validate_asset_setup(is_depreciable=False, it_block_key=None, method=None, life=None, residual=D("0"), class_rule=None,
                                   override_reason=None) == []


def test_F24_a_life_different_from_the_class_needs_an_override_reason():
    f = fa.validate_asset_setup(is_depreciable=True, it_block_key="furniture_fittings", method="slm", life=D("8"),
                                residual=D("0"), class_rule=CLASS, override_reason=None)
    assert ids(f, "error") == ["F-24"]
    ok = fa.validate_asset_setup(is_depreciable=True, it_block_key="furniture_fittings", method="slm", life=D("8"),
                                 residual=D("0"), class_rule=CLASS, override_reason="Used in two shifts")
    assert ids(ok, "error") == [] and ids(ok, "warning") == ["F-24"]


def test_F23_wdv_needs_a_residual_value():
    f = fa.validate_asset_setup(is_depreciable=True, it_block_key="furniture_fittings", method="wdv", life=D("10"),
                                residual=D("0"), class_rule=CLASS, override_reason=None)
    assert ids(f, "error") == ["F-23"]


def test_F24_residual_above_the_class_ceiling_is_a_warning():
    assert [x.severity for x in fa.residual_findings(D("100000"), D("6000"), CLASS)] == ["warning"]
    assert fa.residual_findings(D("100000"), D("5000"), CLASS) == []
    assert [x.severity for x in fa.residual_findings(D("100000"), D("100000"), None)] == ["error"]


# ------------------------------------------------------------------------------------------------ F-21 events


def ev(findings):
    return ids(findings, "error")


def test_F21_cost_must_be_positive_and_proceeds_not_negative():
    assert ev(fa.validate_event([], purchase("0", date(2026, 5, 1)))) == ["F-21"]
    start = [purchase("1000", date(2026, 5, 1))]
    assert ev(fa.validate_event(start, disposal("-1", date(2026, 6, 1)))) == ["F-22"]
    assert ev(fa.validate_event(start, disposal("0", date(2026, 6, 1)))) == []


def test_F21_put_to_use_cannot_be_before_the_purchase_date():
    bad = AssetEvent(EventKind.PURCHASE, date(2026, 5, 1), D("1000"), date(2026, 4, 30))
    assert ev(fa.validate_event([], bad)) == ["F-21"]


def test_F21_an_addition_needs_an_earlier_opening_or_purchase():
    assert ev(fa.validate_event([], addition("500", date(2026, 6, 1)))) == ["F-21"]
    assert ev(fa.validate_event([purchase("1000", date(2026, 7, 1))], addition("500", date(2026, 6, 1)))) == ["F-21"]
    assert ev(fa.validate_event([purchase("1000", date(2026, 5, 1))], addition("500", date(2026, 6, 1)))) == []


def test_F21_only_one_start_event_and_one_disposal():
    start = [purchase("1000", date(2026, 5, 1))]
    assert ev(fa.validate_event(start, opening("900"))) == ["F-21"]
    sold = start + [disposal("10", date(2026, 8, 1))]
    assert ev(fa.validate_event(sold, disposal("5", date(2026, 9, 1)))) == ["F-21"]


def test_F21_no_event_after_a_disposal_and_a_disposal_not_before_put_to_use():
    sold = [purchase("1000", date(2026, 5, 1)), disposal("10", date(2026, 8, 1))]
    assert ev(fa.validate_event(sold, addition("500", date(2026, 9, 1)))) == ["F-21"]
    assert ev([purchase("1000", date(2026, 5, 1), date(2026, 6, 15))] and
              fa.validate_event([purchase("1000", date(2026, 5, 1), date(2026, 6, 15))], disposal("10", date(2026, 6, 1)))) == ["F-21"]


def test_F21_an_opening_event_must_be_the_first_day_of_a_financial_year():
    assert ev(fa.validate_event([], opening("1000", on=date(2026, 10, 1), use=date(2020, 1, 1)))) == ["F-21"]
    assert ev(fa.validate_event([], opening("1000", on=date(2026, 4, 1), use=date(2020, 1, 1)))) == []


def test_F21_messages_use_indian_format_and_dd_mm_yyyy():
    [e] = fa.validate_event([purchase("100000", date(2026, 6, 15))], disposal("5", date(2026, 5, 1)))
    assert "01-05-2026" in e.message


# ------------------------------------------------------------------------------------------------ rule picker (law is data)


def test_F23_pick_rule_chooses_the_row_in_force_on_the_date_and_refuses_two():
    old = fa.Sched2Rule("x", "x", D("5"), D("5"), date(2014, 4, 1), date(2020, 3, 31), "pending", "s")
    new = fa.Sched2Rule("x", "x", D("8"), D("5"), date(2020, 4, 1), None, "pending", "s")
    assert fa.pick_rule([old, new], date(2019, 1, 1)) is old
    assert fa.pick_rule([old, new], date(2026, 1, 1)) is new
    assert fa.pick_rule([old], date(2026, 1, 1)) is None
    with pytest.raises(fa.AmbiguousRule):
        fa.pick_rule([old, old], date(2019, 1, 1))
