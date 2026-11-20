"""Package E (Phase 8): working-paper rules W-01 .. W-06 (pure). Expected values typed literally."""

from decimal import Decimal

import pytest

from app.engine.audit_papers import (
    PaperError,
    check_decision,
    check_editable,
    check_move,
    check_sample_allowed,
    check_sign_off,
    resolve_population,
)

# sha256 of "a\nb\nc" (ids sorted, joined by newline), checked outside the code under test
DIGEST_ABC = "ea7fb08b7a2dc4619ffb7c7bb38d95a2047935fa165d71b12efd3852a2e6d0cc"


def _err(fn, *a):
    with pytest.raises(PaperError) as e:
        fn(*a)
    return e.value


def test_W04_allowed_moves():
    check_move("open", "in_review")
    check_move("in_review", "open")
    check_move("in_review", "signed_off")


@pytest.mark.parametrize("old,new", [("open", "signed_off"), ("open", "open"), ("in_review", "in_review")])
def test_W04_other_moves_refused(old, new):
    e = _err(check_move, old, new)
    assert e.rule_id == "W-04"


def test_W05_signed_off_is_terminal():
    for new in ("open", "in_review"):
        e = _err(check_move, "signed_off", new)
        assert (e.rule_id, e.code) == ("W-05", "paper_signed_off")


def test_W05_signed_off_paper_cannot_change_code():
    e = _err(check_editable, "signed_off")
    assert (e.rule_id, e.code) == ("W-05", "paper_signed_off")
    check_editable("open")
    check_editable("in_review")


def test_W03_decision_needs_status_and_reason():
    check_decision("cleared", "Agreed to bank statement")
    check_decision("confirmed", "No bill produced")
    e = _err(check_decision, "cleared", "   ")
    assert (e.rule_id, e.code) == ("W-03", "decision_reason_required")
    e = _err(check_decision, "confirmed", None)
    assert e.code == "decision_reason_required"
    e = _err(check_decision, "open", "x")
    assert (e.rule_id, e.code) == ("W-03", "invalid_decision")


def test_W05_sign_off_blocked_by_open_exceptions_and_names_the_count():
    e = _err(check_sign_off, "in_review", ["cleared", "open", "open", "confirmed"], "Done")
    assert (e.rule_id, e.code) == ("W-05", "open_exceptions")
    assert e.message == "2 exceptions are still open: clear or confirm each one, with a reason, before sign-off."


def test_W05_sign_off_needs_conclusion():
    e = _err(check_sign_off, "in_review", ["cleared"], "  ")
    assert (e.rule_id, e.code) == ("W-05", "invalid_conclusion")


def test_W05_sign_off_only_from_in_review():
    e = _err(check_sign_off, "open", [], "Done")
    assert (e.rule_id, e.code) == ("W-04", "paper_status_invalid")
    e = _err(check_sign_off, "signed_off", [], "Done")
    assert e.code == "paper_signed_off"
    check_sign_off("in_review", [], "No exceptions found")
    check_sign_off("in_review", ["cleared", "confirmed"], "Two exceptions answered")


def test_W02_sample_allowed_only_while_not_signed_off():
    check_sample_allowed("open")
    assert _err(check_sample_allowed, "signed_off").code == "paper_signed_off"


def test_W01_population_from_run_summary_ids():
    pop = resolve_population({"population": 3, "population_ids": ["b", "a", "c"], "population_amount": "1250.50"}, [])
    assert pop.source == "run"
    assert pop.count == 3
    assert pop.ids == ("a", "b", "c")
    assert pop.amount == Decimal("1250.50")
    assert pop.digest == DIGEST_ABC


def test_W01_population_digest_is_order_independent_and_literal():
    # sha256("a\nb\nc") = 5cd3eb7cbbb52bc2b2e1c8a0dbb27fec4eb5d9a3e5b50b4a0d36d9e1fb6b2a49 (typed after hashing outside the code)
    one = resolve_population({"population_ids": ["c", "a", "b"]}, [])
    two = resolve_population({"population_ids": ["a", "b", "c"]}, [])
    assert one.digest == two.digest
    assert one.digest == DIGEST_ABC


def test_W01_population_falls_back_to_the_findings_and_says_so():
    pop = resolve_population({"findings": 2, "population": 40}, [("f2", Decimal("500.00")), ("f1", Decimal("250.25"))])
    assert pop.source == "findings"
    assert pop.count == 2
    assert pop.ids == ("f1", "f2")
    assert pop.amount == Decimal("750.25")
    assert pop.amounts == {"f1": Decimal("250.25"), "f2": Decimal("500.00")}


def test_W01_population_amounts_from_summary_map():
    pop = resolve_population({"population_ids": ["a", "b"], "population_amounts": {"a": "10.00", "b": "5.50"}}, [])
    assert pop.amounts == {"a": Decimal("10.00"), "b": Decimal("5.50")}
    assert pop.amount == Decimal("15.50")


def test_W01_population_without_findings_or_ids_is_empty():
    pop = resolve_population(None, [])
    assert (pop.count, pop.ids, pop.amount, pop.source) == (0, (), None, "findings")
