"""G-30 .. G-37: ITC eligibility, claim deadline, 180-day share, reversal arithmetic. Expected values are hand-calculated."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.gst_itc import (
    Amounts,
    ItcFacts,
    claim_deadline,
    classify,
    days_since,
    deadline_passed,
    payment_due_date,
    reclaim_amounts,
    reversal_amounts,
    transition_error,
    unpaid_share,
)
from app.engine.gst_types import BlockedRule, ItcCondition

D = Decimal


def blocked(key="food_beverages_catering_17_5_b", exception=True, frm=date(2017, 7, 1), to=None):
    return BlockedRule(key, "CGST 17(5)(b)", "Food", exception, "exception text" if exception else None, frm, to, "src", "pending")


def cond(frm=date(2022, 10, 1), to=None):
    return ItcCondition("claim_time_limit", "16(4)", "limit", "claim_deadline", None, 11, 30, frm, to, "src", "pending")


def facts(**kw):
    base = {
        "source": "regular", "doc_type": "invoice", "invoice_date": date(2026, 5, 10), "itc_category_key": None,
        "itc_exception_claimed": False, "itc_exception_note": None, "tax_document_held": True, "goods_services_received": True,
        "received_date": date(2026, 5, 12), "supplier_tax_paid": "in_2b", "ims_status": None,
    }
    base.update(kw)
    return ItcFacts(**base)


RULES = [blocked(), blocked("club_fitness_membership_17_5_b", exception=False)]


def test_G31_all_evidence_and_in_2b_is_eligible():
    r = classify(facts(), RULES)
    assert (r.status, r.pending_reason, r.blocked_category_key) == ("eligible", None, None)


def test_G31_missing_tax_document_stays_pending_evidence_missing():
    r = classify(facts(tax_document_held=False), RULES)
    assert (r.status, r.pending_reason) == ("pending", "evidence_missing")


def test_G31_goods_not_received_stays_pending_evidence_missing():
    r = classify(facts(goods_services_received=False, received_date=None), RULES)
    assert (r.status, r.pending_reason) == ("pending", "evidence_missing")


def test_G31_received_without_date_is_missing_evidence():
    r = classify(facts(received_date=None), RULES)
    assert (r.status, r.pending_reason) == ("pending", "evidence_missing")


def test_G32_unknown_supplier_payment_is_not_in_2b_pending():
    r = classify(facts(supplier_tax_paid="unknown"), RULES)
    assert (r.status, r.pending_reason) == ("pending", "not_in_2b")


def test_G32_not_in_2b_is_pending():
    r = classify(facts(supplier_tax_paid="not_in_2b"), RULES)
    assert (r.status, r.pending_reason) == ("pending", "not_in_2b")


def test_G32_manual_confirmation_makes_eligible():
    assert classify(facts(supplier_tax_paid="manual_confirmed"), RULES).status == "eligible"


def test_G32_ims_rejected_keeps_pending_even_when_in_2b():
    r = classify(facts(ims_status="rejected"), RULES)
    assert (r.status, r.pending_reason) == ("pending", "ims_rejected")


def test_G32_ims_pending_keeps_pending():
    r = classify(facts(ims_status="pending"), RULES)
    assert (r.status, r.pending_reason) == ("pending", "ims_pending")


def test_G32_rcm_needs_no_supplier_payment_evidence():
    assert classify(facts(source="rcm", supplier_tax_paid="unknown"), RULES).status == "eligible"


def test_G30_tagged_17_5_category_is_blocked_whatever_the_evidence():
    r = classify(facts(itc_category_key="club_fitness_membership_17_5_b", tax_document_held=False), RULES)
    assert (r.status, r.pending_reason, r.blocked_category_key) == ("blocked", None, "club_fitness_membership_17_5_b")


def test_G30_exception_with_note_lifts_the_block():
    r = classify(
        facts(itc_category_key="food_beverages_catering_17_5_b", itc_exception_claimed=True, itc_exception_note="outward catering"),
        RULES,
    )
    assert r.status == "eligible"


def test_G30_exception_without_note_stays_blocked():
    r = classify(facts(itc_category_key="food_beverages_catering_17_5_b", itc_exception_claimed=True, itc_exception_note="  "), RULES)
    assert r.status == "blocked"


def test_G30_exception_claimed_where_rule_has_none_stays_blocked():
    r = classify(facts(itc_category_key="club_fitness_membership_17_5_b", itc_exception_claimed=True, itc_exception_note="x"), RULES)
    assert r.status == "blocked"


def test_G30_category_not_in_force_on_invoice_date_is_not_guessed():
    rules = [blocked("vessels_aircraft_17_5_aa", frm=date(2019, 2, 1))]
    r = classify(facts(itc_category_key="vessels_aircraft_17_5_aa", invoice_date=date(2018, 1, 1)), rules)
    assert (r.status, r.pending_reason) == ("pending", "evidence_missing")
    assert "17(5)" in r.reason


def test_G30_unknown_category_is_not_guessed():
    r = classify(facts(itc_category_key="no_such_key"), RULES)
    assert (r.status, r.pending_reason) == ("pending", "evidence_missing")


def test_G33_deadline_for_invoice_in_fy_2026_27_is_30_nov_2027():
    # invoice 10-05-2026 belongs to FY 2026-27 which ends 31-03-2027; deadline 30-11-2027
    assert claim_deadline(date(2026, 5, 10), cond()) == date(2027, 11, 30)


def test_G33_deadline_for_invoice_in_march_belongs_to_the_year_ending_that_march():
    # 31-03-2026 is in FY 2025-26: deadline 30-11-2026
    assert claim_deadline(date(2026, 3, 31), cond()) == date(2026, 11, 30)


def test_G33_no_rule_in_force_means_no_deadline_not_a_guess():
    assert claim_deadline(date(2022, 9, 30), cond()) is None
    assert claim_deadline(date(2026, 5, 10), None) is None


def test_G33_deadline_passed_only_after_the_day():
    assert deadline_passed(date(2027, 11, 30), date(2027, 11, 30)) is False
    assert deadline_passed(date(2027, 11, 30), date(2027, 12, 1)) is True
    assert deadline_passed(None, date(2030, 1, 1)) is False


def test_G34_days_and_due_date():
    assert days_since(date(2026, 5, 10), date(2026, 5, 10)) == 0
    assert days_since(date(2026, 5, 10), date(2026, 11, 6)) == 180
    assert payment_due_date(date(2026, 5, 10), 180) == date(2026, 11, 6)


def test_G34_unpaid_share_proportionate_half_up():
    # bill 11,800.00 of which 4,700.00 is unpaid; tax CGST 450.00, SGST 450.00, IGST 0, cess 25.00
    # fraction 4700/11800 = 0.398305...; CGST 450 x 0.398305... = 179.2372... -> 179.24; cess = 9.9576... -> 9.96
    s = unpaid_share(Amounts(D("0"), D("450.00"), D("450.00"), D("25.00")), D("11800.00"), D("4700.00"))
    assert s.fraction == D("0.3983")
    assert s.amounts == Amounts(D("0.00"), D("179.24"), D("179.24"), D("9.96"))


def test_G34_fully_unpaid_is_the_full_tax_and_fully_paid_is_zero():
    t = Amounts(D("180.00"), D("0"), D("0"), D("0"))
    assert unpaid_share(t, D("1180.00"), D("1180.00")).amounts.igst == D("180.00")
    assert unpaid_share(t, D("1180.00"), D("0.00")).amounts.igst == D("0.00")


def test_G34_outstanding_above_original_is_capped_at_the_whole_tax():
    t = Amounts(D("180.00"), D("0"), D("0"), D("0"))
    assert unpaid_share(t, D("1180.00"), D("2000.00")).amounts.igst == D("180.00")


def test_G34_zero_original_is_refused():
    with pytest.raises(ValueError):
        unpaid_share(Amounts(D("1"), D("0"), D("0"), D("0")), D("0.00"), D("0.00"))


def test_G36_reversal_is_only_the_part_not_yet_reversed():
    share = Amounts(D("0"), D("179.24"), D("179.24"), D("9.96"))
    done = Amounts(D("0"), D("100.00"), D("100.00"), D("9.96"))
    assert reversal_amounts(share, done) == Amounts(D("0.00"), D("79.24"), D("79.24"), D("0.00"))


def test_G36_nothing_to_reverse_when_already_reversed_for_the_same_amount():
    share = Amounts(D("0"), D("179.24"), D("179.24"), D("0"))
    assert reversal_amounts(share, share).is_zero()


def test_G35_reclaim_is_what_was_paid_since_and_never_more_than_reversed():
    # reversed CGST 179.24 (nothing reclaimed yet); unpaid share today is 100.00 -> reclaim 79.24
    rev = Amounts(D("0"), D("179.24"), D("179.24"), D("9.96"))
    now = Amounts(D("0"), D("100.00"), D("100.00"), D("0.00"))
    assert reclaim_amounts(rev, Amounts.zero(), now) == Amounts(D("0.00"), D("79.24"), D("79.24"), D("9.96"))


def test_G35_reclaim_once_only_per_payment():
    rev = Amounts(D("0"), D("179.24"), D("179.24"), D("0"))
    already = Amounts(D("0"), D("79.24"), D("79.24"), D("0"))
    now = Amounts(D("0"), D("100.00"), D("100.00"), D("0"))
    assert reclaim_amounts(rev, already, now).is_zero()


def test_G35_reclaim_never_exceeds_the_amount_reversed():
    rev = Amounts(D("0"), D("50.00"), D("50.00"), D("0"))
    assert reclaim_amounts(rev, Amounts.zero(), Amounts.zero()) == Amounts(D("0.00"), D("50.00"), D("50.00"), D("0.00"))


def test_G36_a_reversed_entry_cannot_be_confirmed_or_re_evidenced():
    assert transition_error("reversed", "eligible", via="confirm") is not None
    assert transition_error("reversed", "pending", via="evidence") is not None


def test_G37_allowed_transitions():
    assert transition_error("pending", "eligible", via="confirm") is None
    assert transition_error("eligible", "pending", via="evidence") is None
    assert transition_error("eligible", "blocked", via="tag") is None
    assert transition_error("eligible", "reversed", via="reversal") is None
    assert transition_error("reversed", "eligible", via="reclaim") is None
    assert transition_error("blocked", "eligible", via="confirm") is not None
