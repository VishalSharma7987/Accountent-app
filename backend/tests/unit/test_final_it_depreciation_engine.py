"""Package B: income-tax block WDV working with the half-rate rule (F-30 .. F-34). Pure engine, no database.

Hand-calculated expected values (docs/PHASE6_PLAN.md "Income-tax block"). The rate row and the half-rate scalars arrive as inputs
(read from the rule tables by the service); the tests pass 15 / 180 / 50 only as inputs, the engine owns no rate.
"""

from datetime import date
from decimal import Decimal

from app.engine.final_it_depreciation import it_block_depreciation
from app.engine.final_types import ItBlockInput

D = Decimal
FY_END = date(2027, 3, 31)


def block(opening, additions=(), disposals=(), *, rate="15", days=180, pct="50", status="pending"):
    return ItBlockInput("plant_machinery_general", D(rate), status, days, D(pct), D(opening),
                        tuple((a, D(c), p) for a, c, p in additions), tuple((a, D(x)) for a, x in disposals), FY_END)


def test_F31_F32_plan_example_depreciation_1_05_000_closing_wdv_6_45_000():
    r = it_block_depreciation(block(
        "500000",
        additions=[("A", "200000", date(2026, 10, 1)), ("B", "100000", date(2026, 11, 15))],
        disposals=[("X", "50000")]))
    assert r.additions_full == D("200000.00")      # 182 days >= 180
    assert r.additions_half == D("100000.00")      # 137 days < 180
    assert r.disposals == D("50000.00")
    assert r.depreciation == D("105000.00")        # 650000 x 15% = 97,500 + 100000 x 7.5% = 7,500
    assert r.closing_wdv == D("645000.00")
    assert r.flags == ()
    assert r.details["base_full"] == "650000.00" and r.details["base_half"] == "100000.00"
    assert r.details["rate_verification"] == "pending"


def test_F31_180_days_gets_the_full_rate_179_days_gets_half():
    full = it_block_depreciation(block("0", additions=[("A", "100000", date(2026, 10, 3))]))   # 03-10 .. 31-03 = 180 days
    half = it_block_depreciation(block("0", additions=[("A", "100000", date(2026, 10, 4))]))   # 179 days
    assert (full.additions_full, full.additions_half, full.depreciation) == (D("100000.00"), D("0.00"), D("15000.00"))
    assert (half.additions_full, half.additions_half, half.depreciation) == (D("0.00"), D("100000.00"), D("7500.00"))


def test_F31_the_rule_values_come_from_the_input_not_the_engine():
    # a different (hypothetical) rule row: 100 days and 25% -> an asset used 137 days is full rate
    r = it_block_depreciation(block("0", additions=[("B", "100000", date(2026, 11, 15))], days=100, pct="25"))
    assert (r.additions_full, r.depreciation) == (D("100000.00"), D("15000.00"))
    r2 = it_block_depreciation(block("0", additions=[("B", "100000", date(2027, 1, 15))], days=100, pct="25"))   # 76 days
    assert r2.depreciation == D("3750.00")


def test_F32_depreciation_is_rounded_half_up_once():
    assert it_block_depreciation(block("3.50")).depreciation == D("0.53")     # 3.50 x 15% = 0.525
    assert it_block_depreciation(block("3.30")).depreciation == D("0.50")     # 0.495


def test_F32_a_disposal_above_the_full_rate_base_is_set_against_half_rate_additions():
    r = it_block_depreciation(block("0", additions=[("B", "100000", date(2026, 11, 15))], disposals=[("X", "20000")]))
    assert r.depreciation == D("6000.00")          # (100000 - 20000) x 7.5%
    assert r.closing_wdv == D("74000.00")
    assert r.flags == ()


def test_F32_a_negative_block_is_flagged_no_depreciation_no_invented_number():
    r = it_block_depreciation(block("0", additions=[("B", "100000", date(2026, 11, 15))], disposals=[("X", "150000")]))
    assert r.flags == ("negative_block",)
    assert (r.depreciation, r.closing_wdv) == (D("0.00"), D("0.00"))
    assert r.details["excess_over_block"] == "50000.00"


def test_F32_a_block_that_nets_to_exactly_zero_is_not_negative():
    r = it_block_depreciation(block("100000", disposals=[("X", "100000")]))
    assert (r.depreciation, r.closing_wdv, r.flags) == (D("0.00"), D("0.00"), ())


def test_F33_no_asset_left_but_wdv_above_zero_is_flagged_only():
    r = it_block_depreciation(block("100000"), assets_remaining=0)
    assert r.flags == ("terminal_depreciation_review",)
    assert (r.depreciation, r.closing_wdv) == (D("15000.00"), D("85000.00"))     # still the normal working; nothing extra computed
    assert it_block_depreciation(block("100000"), assets_remaining=2).flags == ()
    assert it_block_depreciation(block("100000"), assets_remaining=None).flags == ()
    assert it_block_depreciation(block("0"), assets_remaining=0).flags == ()


def test_F34_the_result_is_a_working_with_the_rate_and_status_printed():
    r = it_block_depreciation(block("200000", rate="10", status="secondary_verified"))
    assert (r.rate_percent, r.depreciation, r.closing_wdv) == (D("10.0000"), D("20000.00"), D("180000.00"))
    assert r.details["rate_verification"] == "secondary_verified"
