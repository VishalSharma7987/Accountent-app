"""Pure pickers of rules/tds_rules.py: the rule in force on the date wins (law is data), the Act follows from the row,
overlaps are errors, the status roll-up (T-50) names the pending sources. Expected values typed literally."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.tds_types import FormRule, Nature, RateRule, SectionRef
from app.rules.tds_rules import (
    AmbiguousRuleError,
    deductee_group,
    pick_form,
    pick_rate,
    rule_status,
    section_map,
    status_summary,
)

Z = Decimal(0)


def rr(rid, nature, group, rate, frm, to=None, *, act="it_act_1961", status="pending", src="src-" ):
    return RateRule(rid, nature, act, group, Decimal(rate), Decimal(20), None, None, None, "whole_amount", frm, to,
                    src + rid, status)


# contractor: 1961 rows to 31-03-2026, 2025 rows from 01-04-2026 (example data, not law)
RATES = [
    rr("c_ind_old", "contractor", "individual_huf", "1", date(2025, 4, 1), date(2026, 3, 31)),
    rr("c_oth_old", "contractor", "others", "2", date(2025, 4, 1), date(2026, 3, 31)),
    rr("c_ind_new", "contractor", "individual_huf", "1", date(2026, 4, 1), act="it_act_2025", status="secondary_verified"),
    rr("c_oth_new", "contractor", "others", "2", date(2026, 4, 1), act="it_act_2025", status="secondary_verified"),
    rr("eco_old", "ecommerce_participant", "any", "0.1", date(2025, 4, 1), date(2026, 3, 31)),
]


def test_T02_T04_group_of_deductee_type():
    assert deductee_group("individual") == "individual_huf"
    assert deductee_group("huf") == "individual_huf"
    for other in ("company", "firm", "llp", "aop_boi", "co_operative_society", "local_authority", "trust", "other"):
        assert deductee_group(other) == "others"


def test_T02_rate_picked_by_date_and_act_follows_the_row():
    on_old = pick_rate(RATES, "contractor", "others", date(2026, 3, 31))
    on_new = pick_rate(RATES, "contractor", "others", date(2026, 4, 1))
    assert (on_old.id, on_old.act, on_old.rate) == ("c_oth_old", "it_act_1961", Decimal(2))
    assert (on_new.id, on_new.act, on_new.verification_status) == ("c_oth_new", "it_act_2025", "secondary_verified")


def test_T02_no_rule_in_force_returns_none_never_a_default():
    assert pick_rate(RATES, "contractor", "others", date(2025, 3, 31)) is None   # before the data starts
    assert pick_rate(RATES, "no_such_nature", "others", date(2026, 4, 1)) is None


def test_T04_group_any_applies_to_everybody_and_exact_group_is_chosen():
    assert pick_rate(RATES, "ecommerce_participant", "individual_huf", date(2025, 6, 1)).id == "eco_old"
    assert pick_rate(RATES, "ecommerce_participant", "others", date(2025, 6, 1)).id == "eco_old"
    assert pick_rate(RATES, "contractor", "individual_huf", date(2025, 6, 1)).id == "c_ind_old"


def test_T02_two_rules_in_force_for_one_key_is_an_error_not_a_guess():
    rows = RATES + [rr("dup", "contractor", "others", "3", date(2025, 10, 1), act="it_act_1961")]
    with pytest.raises(AmbiguousRuleError):
        pick_rate(rows, "contractor", "others", date(2026, 1, 1))
    # a specific row and a group-'any' row in force together is also ambiguous
    rows = RATES + [rr("any", "contractor", "any", "5", date(2025, 4, 1), date(2026, 3, 31))]
    with pytest.raises(AmbiguousRuleError):
        pick_rate(rows, "contractor", "others", date(2025, 6, 1))


def test_T50_status_summary_weakest_wins_and_empty_is_pending():
    assert status_summary(RATES[2:4]) == {"overall": "secondary_verified", "counts": {"secondary_verified": 2}}
    assert status_summary(RATES[:3])["overall"] == "pending"
    assert status_summary([]) == {"overall": "pending", "counts": {}}


def test_T50_rule_status_lists_tables_and_pending_sources():
    status = rule_status({"rate": RATES[2:4], "due_date": RATES[:1]})
    assert status["worst"] == "pending"
    assert status["tables"] == {"rate": "secondary_verified", "due_date": "pending"}
    assert status["pending_sources"] == ["src-c_ind_old"]


def test_T50_rule_status_all_verified_has_no_pending_sources():
    rows = [rr("v", "contractor", "others", "2", date(2026, 4, 1), status="verified")]
    assert rule_status({"rate": rows}) == {"worst": "verified", "tables": {"rate": "verified"}, "pending_sources": []}


def sref(nature, act, section, frm, to, table=None, code=None, status="pending"):
    return SectionRef(nature, act, section, table, code, frm, to, "s", status)


NATURES = [Nature("contractor", "tds", "Contractor", "flat", "pending"),
           Nature("salary", "tds", "Salary", "slab_manual", "pending")]
REFS = [
    sref("contractor", "it_act_1961", "194C", date(2025, 4, 1), date(2026, 3, 31)),
    sref("contractor", "it_act_2025", "393(1)", date(2026, 4, 1), None, table="Sl. 6(i)", status="secondary_verified"),
    sref("salary", "it_act_1961", "192", date(2025, 4, 1), date(2026, 3, 31)),
    sref("salary", "it_act_2025", "392", date(2026, 4, 1), None),
]


def test_section_map_pairs_old_and_new_sections_and_marks_the_act_in_force():
    rows = section_map(NATURES, REFS, date(2026, 5, 1))
    assert [r["nature_key"] for r in rows] == ["contractor", "salary"]
    c = rows[0]
    assert (c["sec_1961"], c["sec_2025"], c["table_ref_2025"], c["payment_code_2025"]) == ("194C", "393(1)", "Sl. 6(i)", None)
    assert c["status"] == "pending"          # weakest of the two rows
    assert c["act_in_force"] == "it_act_2025"
    assert section_map(NATURES, REFS, date(2026, 3, 31))[0]["act_in_force"] == "it_act_1961"
    assert section_map(NATURES, REFS, date(2025, 3, 31))[0]["act_in_force"] is None


def test_section_map_nature_without_a_row_for_an_act_shows_none():
    rows = section_map(NATURES[:1], REFS[:1], date(2026, 1, 1))
    assert (rows[0]["sec_1961"], rows[0]["sec_2025"], rows[0]["status"]) == ("194C", None, "pending")


def test_form_picker_by_date():
    forms = [FormRule("return_non_salary", "it_act_1961", "26Q", "d", None, date(2025, 4, 1), date(2026, 3, 31), "pending"),
             FormRule("return_non_salary", "it_act_2025", "140", "d", None, date(2026, 4, 1), None, "pending")]
    assert pick_form(forms, "return_non_salary", date(2026, 3, 31)).form_no == "26Q"
    assert pick_form(forms, "return_non_salary", date(2026, 4, 1)).form_no == "140"
    assert pick_form(forms, "return_non_salary", date(2025, 1, 1)) is None
