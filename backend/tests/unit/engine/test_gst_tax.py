"""Pure tax engine (G-10 .. G-17, G-20, G-21). Expected figures are hand-calculated and typed literally."""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest
from gst_helpers import RULES, item

from app.engine.gst_tax import GstRuleError, compute_item, head_for, pick_rate_rule

D0 = D("0.00")


def calc(it, *, on=date(2026, 5, 10), head="intra", charge=True, category="b2b"):
    return compute_item(1, it, RULES, on, head, charge_tax=charge, supply_category=category)


# ---- head / place of supply (G-13, G-19) ---------------------------------------------------------------
def test_G13_same_state_gives_cgst_sgst():
    assert head_for("27", "27", "b2b") == "intra"


def test_G13_different_state_gives_igst():
    assert head_for("27", "29", "b2b") == "inter"


def test_G19_export_and_sez_are_always_igst_even_in_same_state():
    assert head_for("27", "27", "sez_with_payment") == "inter"
    assert head_for("27", "96", "export_with_payment") == "inter"


# ---- rounding (G-15) --------------------------------------------------------------------------------------
def test_G15_intra_state_18_percent_on_1000():
    t = calc(item())
    assert (t.gross_amount, t.taxable_value, t.cgst, t.sgst, t.igst) == (D("1000.00"), D("1000.00"), D("90.00"), D("90.00"), D0)


def test_G15_inter_state_18_percent_on_1000():
    t = calc(item(), head="inter")
    assert (t.cgst, t.sgst, t.igst) == (D0, D0, D("180.00"))


def test_G15_odd_paise_half_up_per_head():
    # taxable 1.00 at 5%: 1.00 x 5 / 200 = 0.025 -> 0.03 each (half up); IGST 1.00 x 5 / 100 = 0.05
    t = calc(item(hsn="1701", rate="1.00"))
    assert (t.cgst, t.sgst) == (D("0.03"), D("0.03"))
    assert calc(item(hsn="1701", rate="1.00"), head="inter").igst == D("0.05")


def test_G15_tiny_amount_rounds_down_below_half_paisa():
    # taxable 0.05 at 5%: 0.05 x 5 / 200 = 0.00125 -> 0.00
    t = calc(item(hsn="1701", rate="0.05"))
    assert (t.cgst, t.sgst) == (D0, D0)


def test_G15_quantity_times_rate_and_half_up_gross():
    assert calc(item(qty="3", rate="10.01")).gross_amount == D("30.03")
    assert calc(item(qty="2.5", rate="10.25")).gross_amount == D("25.63")  # 25.625 half up


def test_G15_discount_reduces_taxable_value_before_tax():
    t = calc(item(discount="100.00"))
    assert (t.gross_amount, t.discount, t.taxable_value, t.cgst, t.sgst) == (
        D("1000.00"), D("100.00"), D("900.00"), D("81.00"), D("81.00"))


def test_G15_cess_percentage():
    # 8703 test rule: 28% + cess 1% before 22-09-2025; taxable 1,00,000.00 -> 14,000.00 + 14,000.00 + cess 1,000.00
    t = calc(item(hsn="8703", rate="100000.00"), on=date(2025, 9, 21))
    assert (t.cgst, t.sgst, t.cess, t.gst_rate, t.cess_rate) == (
        D("14000.00"), D("14000.00"), D("1000.00"), D("28.0000"), D("1.0000"))


def test_G15_specific_cess_per_unit_added():
    # qty 4 x 100.00 = 400.00 at 28%: 56.00 + 56.00; specific cess 2.50 x 4 = 10.00
    t = calc(item(hsn="2402", qty="4", rate="100.00"), on=date(2025, 9, 21))
    assert (t.cgst, t.sgst, t.cess, t.cess_specific_amount) == (D("56.00"), D("56.00"), D("10.00"), D("10.00"))


def test_G15_specific_cess_needs_matching_uqc():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="2402", qty="4", rate="100.00", uqc="KGS"), on=date(2025, 9, 21))
    assert e.value.rule_id == "G-15"


# ---- rate rule by date (G-10, G-11) ---------------------------------------------------------------------
def test_G10_old_rate_before_and_new_rate_after_22_09_2025():
    assert calc(item(hsn="3004"), on=date(2025, 9, 21)).cgst == D("60.00")   # 12%: 1000 x 12 / 200
    assert calc(item(hsn="3004"), on=date(2025, 9, 22)).cgst == D("25.00")   # 5%


def test_G10_longest_prefix_wins_and_history_by_date():
    assert calc(item(hsn="85171200"), on=date(2020, 3, 31)).gst_rate == D("12.0000")
    assert calc(item(hsn="85171200"), on=date(2020, 4, 1)).gst_rate == D("18.0000")
    assert calc(item(hsn="85171900")).gst_rate == D("18.0000")  # falls back to the 8517 prefix


def test_G10_no_rule_for_goods_is_rejected_with_code_and_date():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="9018"))
    assert e.value.rule_id == "G-10"
    assert "9018" in e.value.message and "10-05-2026" in e.value.message


def test_G10_default_services_rule_used_with_flag():
    t = calc(item(hsn="998899", ledger="svc"))
    assert t.rate_is_default is True and t.gst_rate == D("18.0000")


def test_G10_pick_rate_rule_returns_flag():
    r, is_default = pick_rate_rule(RULES.rate_rules, "998899", "services", date(2026, 5, 10))
    assert r.rule_key == "default_services" and is_default is True


def test_G11_rate_not_in_slab_is_rejected():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="7777"))
    assert e.value.rule_id == "G-11"


# ---- treatments (G-21) -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("hsn", "treatment"), [("0713", "exempt"), ("0401", "nil_rated"), ("2208", "non_gst")])
def test_G21_exempt_nil_non_gst_carry_no_tax(hsn, treatment):
    t = calc(item(hsn=hsn))
    assert (t.treatment, t.cgst, t.sgst, t.igst, t.cess, t.gst_rate) == (treatment, D0, D0, D0, D0, D("0.0000"))


def test_G19_export_without_payment_is_zero_rated():
    t = calc(item(), head="inter", category="export_without_payment")
    assert (t.treatment, t.igst, t.cgst) == ("zero_rated", D0, D0)


def test_G19_export_with_payment_charges_igst():
    t = calc(item(), head="inter", category="export_with_payment")
    assert (t.treatment, t.igst) == ("taxable", D("180.00"))


def test_G18_tax_not_charged_gives_zero_tax():
    t = calc(item(), charge=False)
    assert (t.cgst, t.sgst, t.igst, t.gst_rate) == (D0, D0, D0, D("0.0000"))


# ---- G-17 inputs -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [{"qty": "0"}, {"qty": "1.0001"}, {"rate": "10.005"}, {"discount": "1.001"}, {"rate": "-1.00"}, {"discount": "2000.00"}],
)
def test_G17_bad_quantity_rate_discount_rejected(kw):
    with pytest.raises(GstRuleError) as e:
        calc(item(**kw))
    assert e.value.rule_id == "G-17"


def test_G17_float_rate_rejected():
    with pytest.raises(GstRuleError) as e:
        calc(replace(item(), unit_rate=1.5))
    assert e.value.rule_id == "G-17"


# ---- RCM (G-20) ------------------------------------------------------------------------------------------
def test_G20_rcm_line_gets_tax_and_flag():
    t = calc(item(hsn="996511", ledger="freight", rate="10000.00", rcm_category_key="gta_services"), category="unregistered_supplier")
    assert (t.rcm, t.cgst, t.sgst) == (True, D("250.00"), D("250.00"))


def test_G20_category_not_in_force_rejected():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="996511", rcm_category_key="future_cat"), category="unregistered_supplier")
    assert e.value.rule_id == "G-20"


def test_G20_unknown_category_rejected():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="996511", rcm_category_key="nope"), category="b2b")
    assert e.value.rule_id == "G-20"


def test_G20_section_9_4_needs_unregistered_supplier():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="998311", rcm_category_key="sec_9_4"), category="b2b")
    assert e.value.rule_id == "G-20"
    assert calc(item(hsn="998311", rcm_category_key="sec_9_4"), category="unregistered_supplier").rcm is True


def test_G20_hsn_prefix_of_the_category_must_match():
    with pytest.raises(GstRuleError) as e:
        calc(item(hsn="998311", rcm_category_key="gta_services"), category="b2b")
    assert e.value.rule_id == "G-20"
