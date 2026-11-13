"""Rule-table pickers of rules/gst_rules.py (pure part). Law is data: the rule in force on the date wins.
Expected values typed literally."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.gst_types import (
    BlockedRule,
    CompositionRule,
    ItcCondition,
    RateRule,
    RateSlab,
    RcmRule,
    StateCode,
    Threshold,
)
from app.rules.gst_rules import (
    AmbiguousRuleError,
    find_overlaps,
    pick_blocked,
    pick_by_date,
    pick_composition,
    pick_condition,
    pick_rate,
    pick_rcm,
    pick_threshold,
    slab_in_force,
    states_in_force,
    status_summary,
)

Z = Decimal(0)


def rr(rid, prefix, rate, frm, to=None, *, kind="hsn", supply="goods", key=None, status="pending",
       treatment="taxable"):
    return RateRule(rid, key or rid, kind if prefix else "default", prefix, supply, treatment, Decimal(rate), Z, Z,
                    None, frm, to, "t", status)


# 3004 medicaments: 12% until 21-09-2025, 5% from 22-09-2025 (example data; see the legal values register)
RULES = [
    rr("m12", "3004", "12", date(2017, 7, 1), date(2025, 9, 21)),
    rr("m5", "3004", "5", date(2025, 9, 22)),
    rr("t", "85", "18", date(2017, 7, 1)),
    rr("p", "851712", "12", date(2017, 7, 1), date(2020, 3, 31)),
    rr("p2", "851712", "18", date(2020, 4, 1)),
    rr("svc", "9983", "18", date(2017, 7, 1), kind="sac", supply="services"),
    rr("dsvc", None, "18", date(2017, 7, 1), supply="services"),
]


def test_G10_rate_changes_on_22_09_2025():
    assert pick_rate(RULES, "30049099", "goods", date(2025, 9, 21))[0].rate == Decimal(12)
    assert pick_rate(RULES, "30049099", "goods", date(2025, 9, 22))[0].rate == Decimal(5)


def test_G10_rate_changes_between_31_03_2020_and_01_04_2020():
    assert pick_rate(RULES, "851712", "goods", date(2020, 3, 31))[0].id == "p"
    assert pick_rate(RULES, "851712", "goods", date(2020, 4, 1))[0].id == "p2"


def test_G10_longest_prefix_wins():
    rule, is_default = pick_rate(RULES, "85171290", "goods", date(2021, 1, 1))
    assert (rule.id, is_default) == ("p2", False)
    assert pick_rate(RULES, "85011000", "goods", date(2021, 1, 1))[0].id == "t"


def test_G10_no_rule_for_goods_returns_none_no_default_for_goods():
    assert pick_rate(RULES, "9999", "goods", date(2021, 1, 1)) == (None, False)
    assert pick_rate(RULES, "1001", "goods", date(2021, 1, 1)) == (None, False)


def test_G10_before_first_rule_date_returns_none():
    assert pick_rate(RULES, "3004", "goods", date(2017, 6, 30)) == (None, False)


def test_G10_default_rule_only_for_services_and_flagged():
    rule, is_default = pick_rate(RULES, "998399", "services", date(2021, 1, 1))
    assert (rule.id, is_default) == ("svc", False)
    rule, is_default = pick_rate(RULES, "995411", "services", date(2021, 1, 1))
    assert (rule.id, is_default) == ("dsvc", True)


def test_G10_goods_rule_does_not_apply_to_services_and_vice_versa():
    assert pick_rate(RULES, "8517", "services", date(2021, 1, 1))[0].id == "dsvc"
    assert pick_rate(RULES, "998314", "goods", date(2021, 1, 1)) == (None, False)


def test_G10_two_rules_in_force_for_same_prefix_is_ambiguous_not_guessed():
    clash = [rr("a", "1001", "5", date(2020, 1, 1)), rr("b", "1001", "12", date(2020, 6, 1))]
    with pytest.raises(AmbiguousRuleError):
        pick_rate(clash, "1001", "goods", date(2021, 1, 1))
    assert pick_rate(clash, "1001", "goods", date(2020, 3, 1))[0].id == "a"


def test_G10_overlap_detection_per_key():
    rules = [
        rr("a", "1001", "5", date(2020, 1, 1), date(2020, 12, 31), key="wheat"),
        rr("b", "1001", "12", date(2020, 12, 31), None, key="wheat"),
        rr("c", "1002", "5", date(2020, 1, 1), key="rye"),
        rr("d", "1002", "5", date(2022, 1, 1), key="other"),
    ]
    assert find_overlaps(rules, lambda r: r.rule_key) == [("wheat", "a", "b")]


def test_G10_adjacent_periods_are_not_an_overlap():
    rules = [rr("a", "1001", "5", date(2020, 1, 1), date(2020, 12, 31), key="w"),
             rr("b", "1001", "12", date(2021, 1, 1), None, key="w")]
    assert find_overlaps(rules, lambda r: r.rule_key) == []


def slab(rate, frm, to=None, special=False):
    return RateSlab(Decimal(rate), special, frm, to, "t", "secondary_verified")


SLABS = [slab("0", date(2017, 7, 1)), slab("5", date(2017, 7, 1)), slab("12", date(2017, 7, 1), date(2025, 9, 21)),
         slab("18", date(2017, 7, 1)), slab("28", date(2017, 7, 1), date(2025, 9, 21)), slab("40", date(2025, 9, 22)),
         slab("0.25", date(2017, 7, 1), special=True)]


def test_G11_slab_must_be_in_force_on_the_date():
    assert slab_in_force(SLABS, Decimal(12), date(2025, 9, 21))
    assert not slab_in_force(SLABS, Decimal(12), date(2025, 9, 22))
    assert slab_in_force(SLABS, Decimal(40), date(2025, 9, 22))
    assert not slab_in_force(SLABS, Decimal(40), date(2025, 9, 21))
    assert not slab_in_force(SLABS, Decimal(7), date(2025, 1, 1))
    assert slab_in_force(SLABS, Decimal("5.0000"), date(2025, 1, 1))


def test_G11_special_rate_is_not_a_general_slab():
    assert not slab_in_force(SLABS, Decimal("0.25"), date(2025, 1, 1))
    assert slab_in_force(SLABS, Decimal("0.25"), date(2025, 1, 1), allow_special=True)


def test_G03_states_in_force_by_date():
    codes = [StateCode("28", "AP old", "state", date(2017, 7, 1), date(2020, 3, 31), "t", "pending"),
             StateCode("27", "MH", "state", date(2017, 7, 1), None, "t", "secondary_verified")]
    assert [c.code for c in states_in_force(codes, date(2020, 3, 31))] == ["27", "28"]
    assert [c.code for c in states_in_force(codes, date(2020, 4, 1))] == ["27"]
    assert states_in_force(codes, date(2017, 6, 30)) == []


def test_G10_pick_by_date_for_keyed_rcm_rules():
    gta = "GTA"
    rcm = [RcmRule("gta", "CGST 9(3)", "services", gta, "any", "9965", date(2017, 7, 1), date(2020, 12, 31), "t",
                   "pending"),
           RcmRule("gta", "CGST 9(3)", "services", gta, "any", "9965", date(2021, 1, 1), None, "t", "pending"),
           RcmRule("adv", "CGST 9(3)", "services", "Advocate", "any", "9982", date(2017, 7, 1), None, "t", "pending")]
    assert pick_rcm(rcm, "gta", date(2020, 12, 31)) is rcm[0]
    assert pick_rcm(rcm, "gta", date(2021, 1, 1)) is rcm[1]
    assert pick_rcm(rcm, "adv", date(2026, 1, 1)) is rcm[2]
    assert pick_rcm(rcm, "none", date(2026, 1, 1)) is None
    assert pick_rcm(rcm, "adv", date(2017, 6, 30)) is None


def test_pick_blocked_condition_threshold_composition():
    b = [BlockedRule("motor", "17(5)(a)", "Motor vehicles", True, "exception", date(2019, 2, 1), None, "t", "pending")]
    c = [ItcCondition("payment_within_days", "16(2)", "180 days", None, 180, None, None, date(2017, 7, 1), None, "t",
                      "pending")]
    t = [Threshold("b2cl", "inr", Decimal("250000.00"), date(2017, 7, 1), None, "t", "pending")]
    k = [CompositionRule("trader", Decimal("1.0000"), Decimal("15000000.00"), "10(1)", "turnover_in_state",
                         date(2019, 4, 1), None, "t", "pending")]
    assert pick_blocked(b, "motor", date(2026, 1, 1)) is b[0]
    assert pick_blocked(b, "motor", date(2019, 1, 31)) is None
    assert pick_condition(c, "payment_within_days", date(2026, 1, 1)).parameter_days == 180
    assert pick_threshold(t, "b2cl", date(2026, 1, 1)).numeric_value == Decimal("250000.00")
    assert pick_composition(k, "trader", date(2026, 1, 1)).rate == Decimal("1.0000")
    assert pick_composition(k, "restaurant", date(2026, 1, 1)) is None


def test_pick_by_date_overlap_is_ambiguous():
    rows = [Threshold("x", "inr", Decimal(1), date(2020, 1, 1), None, "t", "pending"),
            Threshold("x", "inr", Decimal(2), date(2021, 1, 1), None, "t", "pending")]
    with pytest.raises(AmbiguousRuleError):
        pick_by_date(rows, "threshold_key", "x", date(2022, 1, 1))


def test_status_summary_rolls_up_to_the_weakest_status():
    rows = [slab("5", date(2017, 7, 1)), slab("18", date(2017, 7, 1))]
    assert status_summary(rows) == {"overall": "secondary_verified", "counts": {"secondary_verified": 2}}
    mixed = rows + [RateSlab(Decimal(3), True, date(2017, 7, 1), None, "t", "pending")]
    assert status_summary(mixed) == {"overall": "pending", "counts": {"secondary_verified": 2, "pending": 1}}
    assert status_summary([]) == {"overall": "pending", "counts": {}}
    ver = [RateSlab(Decimal(3), True, date(2017, 7, 1), None, "t", "verified")]
    assert status_summary(ver)["overall"] == "verified"
