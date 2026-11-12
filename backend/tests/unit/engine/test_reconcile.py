"""Step 2.7: automatic matching and match validation (R-03, R-04). Pure engine, hand-calculated expectations."""

from datetime import date
from decimal import Decimal

from app.engine.reconcile import BankLine, BookItem, auto_match, validate_match


def D(x: str) -> Decimal:
    return Decimal(x)


def bank(i, day, amount, direction="payment", ref=None, desc=""):
    return BankLine(i, date(2026, 4, day), D(amount), direction, ref, desc)


def book(i, day, amount, direction="payment", ref=None, narration="", kind="voucher_line"):
    return BookItem(i, date(2026, 4, day), D(amount), direction, ref, narration, kind)


def groups(result):
    return sorted((tuple(sorted(g.bank_ids)), tuple(sorted(g.book_ids)), g.rule) for g in result.groups)


# ------------------------------------------------------------------------------------------------ rule 1


def test_R03_reference_in_voucher_reference_beats_amount_only():
    # two payments of 5,000.00 on the same day; the bank line carries cheque 000456, only K2 mentions 456
    result = auto_match(
        [bank("B1", 12, "5000.00", ref="000456")],
        [book("K1", 12, "5000.00", ref="CHQ 123"), book("K2", 11, "5000.00", ref="Cheque no 456")],
    )
    assert groups(result) == [(("B1",), ("K2",), 1)]
    assert result.suggestions == []


def test_R03_reference_found_in_narration_case_insensitive():
    result = auto_match(
        [bank("B1", 12, "700.00", "deposit", ref="neft-ab12cd34")],
        [book("K1", 10, "700.00", "deposit", narration="Received via NEFT-AB12CD34 from Rahul"),
         book("K2", 10, "700.00", "deposit", narration="Other receipt")],
    )
    assert groups(result) == [(("B1",), ("K1",), 1)]


def test_R03_digits_must_match_the_whole_number_not_a_part_of_it():
    # cheque 456 is not contained in 4567; two candidates remain -> ambiguous
    result = auto_match(
        [bank("B1", 12, "900.00", ref="456")],
        [book("K1", 12, "900.00", ref="4567"), book("K2", 12, "900.00", ref="9999")],
    )
    assert result.groups == []
    assert len(result.suggestions) == 1


def test_R03_two_bank_lines_same_amount_each_matched_by_its_own_reference():
    result = auto_match(
        [bank("B1", 12, "1000.00", ref="111111"), bank("B2", 12, "1000.00", ref="222222")],
        [book("K1", 12, "1000.00", ref="222222"), book("K2", 12, "1000.00", ref="111111")],
    )
    assert groups(result) == [(("B1",), ("K2",), 1), (("B2",), ("K1",), 1)]


# ------------------------------------------------------------------------------------------------ rule 2


def test_R03_unique_amount_and_date_window_matches():
    result = auto_match([bank("B1", 12, "2500.00")], [book("K1", 10, "2500.00")])
    assert groups(result) == [(("B1",), ("K1",), 2)]


def test_R03_window_edge_seven_days_matches_eight_days_does_not():
    inside = auto_match([bank("B1", 17, "100.00")], [book("K1", 10, "100.00")])
    assert groups(inside) == [(("B1",), ("K1",), 2)]
    outside = auto_match([bank("B1", 18, "100.00")], [book("K1", 10, "100.00")])
    assert outside.groups == []
    assert outside.suggestions == []  # nothing is a candidate at all


def test_R03_window_is_configurable():
    assert auto_match([bank("B1", 14, "100.00")], [book("K1", 10, "100.00")], date_window_days=3).groups == []
    assert len(auto_match([bank("B1", 13, "100.00")], [book("K1", 10, "100.00")], date_window_days=3).groups) == 1


def test_R03_opposite_direction_is_never_matched():
    result = auto_match([bank("B1", 10, "100.00", "deposit")], [book("K1", 10, "100.00", "payment")])
    assert result.groups == []
    assert result.suggestions == []


def test_R03_opposite_direction_with_same_reference_is_never_matched():
    result = auto_match([bank("B1", 10, "100.00", "deposit", ref="777777")],
                        [book("K1", 10, "100.00", "payment", ref="777777")])
    assert result.groups == []


def test_R03_amount_must_be_exact_to_the_paisa():
    assert auto_match([bank("B1", 10, "100.00")], [book("K1", 10, "100.01")]).groups == []


def test_R03_ambiguity_two_candidates_is_never_matched_but_suggested():
    result = auto_match(
        [bank("B1", 12, "3000.00")],
        [book("K1", 11, "3000.00"), book("K2", 13, "3000.00")],
    )
    assert result.groups == []
    assert len(result.suggestions) == 1
    s = result.suggestions[0]
    assert sorted(s.bank_line_ids) == ["B1"] and sorted(s.book_item_ids) == ["K1", "K2"]
    assert s.reason != ""


def test_R03_two_bank_lines_competing_for_one_voucher_are_left_unmatched():
    result = auto_match(
        [bank("B1", 12, "3000.00"), bank("B2", 13, "3000.00")],
        [book("K1", 12, "3000.00")],
    )
    assert result.groups == []
    assert len(result.suggestions) == 1
    assert sorted(result.suggestions[0].bank_line_ids) == ["B1", "B2"]


def test_R03_unambiguous_pairs_are_still_matched_next_to_an_ambiguous_one():
    result = auto_match(
        [bank("B1", 12, "3000.00"), bank("B2", 12, "40.00")],
        [book("K1", 11, "3000.00"), book("K2", 13, "3000.00"), book("K3", 12, "40.00")],
    )
    assert groups(result) == [(("B2",), ("K3",), 2)]
    assert len(result.suggestions) == 1


# ------------------------------------------------------------------------------------------------ rule 3


def test_R03_three_cheques_banked_as_one_deposit():
    result = auto_match(
        [bank("B1", 15, "60000.00", "deposit")],
        [book("K1", 12, "10000.00", "deposit"), book("K2", 13, "20000.00", "deposit"),
         book("K3", 14, "30000.00", "deposit")],
    )
    assert groups(result) == [(("B1",), ("K1", "K2", "K3"), 3)]
    assert result.suggestions == []


def test_R03_one_cheque_cleared_in_two_bank_lines_many_to_one():
    result = auto_match(
        [bank("B1", 15, "4000.00"), bank("B2", 16, "6000.00")],
        [book("K1", 14, "10000.00")],
    )
    assert groups(result) == [(("B1", "B2"), ("K1",), 3)]


def test_R03_subset_must_be_unique_otherwise_suggestion_only():
    # 10,000 = 4,000 + 6,000 = 3,000 + 7,000: two different subsets -> not matched
    result = auto_match(
        [bank("B1", 15, "10000.00", "deposit")],
        [book("K1", 14, "4000.00", "deposit"), book("K2", 14, "6000.00", "deposit"),
         book("K3", 14, "3000.00", "deposit"), book("K4", 14, "7000.00", "deposit")],
    )
    assert result.groups == []
    assert len(result.suggestions) == 1
    assert sorted(result.suggestions[0].book_item_ids) == ["K1", "K2", "K3", "K4"]


def test_R03_subset_never_mixes_directions():
    result = auto_match(
        [bank("B1", 15, "6000.00", "deposit")],
        [book("K1", 14, "2000.00", "deposit"), book("K2", 14, "4000.00", "payment")],
    )
    assert result.groups == []


def test_R03_subset_respects_the_date_window():
    result = auto_match(
        [bank("B1", 20, "6000.00", "deposit")],
        [book("K1", 2, "2000.00", "deposit"), book("K2", 19, "4000.00", "deposit")],
    )
    assert result.groups == []


def test_R03_subset_of_seven_items_is_not_attempted():
    items = [book(f"K{n}", 10, "100.00", "deposit") for n in range(1, 8)]
    result = auto_match([bank("B1", 12, "700.00", "deposit")], items)
    assert result.groups == []


def test_R03_subset_of_six_items_is_matched():
    items = [book(f"K{n}", 10, "100.00", "deposit") for n in range(1, 7)]
    result = auto_match([bank("B1", 12, "600.00", "deposit")], items)
    assert len(result.groups) == 1 and len(result.groups[0].book_ids) == 6


def test_R03_two_deposits_competing_for_the_same_cheques_are_left_unmatched():
    result = auto_match(
        [bank("B1", 15, "3000.00", "deposit"), bank("B2", 15, "3000.00", "deposit")],
        [book("K1", 14, "1000.00", "deposit"), book("K2", 14, "2000.00", "deposit")],
    )
    assert result.groups == []


def test_R03_rules_run_in_order_exact_pair_is_taken_before_a_subset():
    # K3 (3,000) is the single exact candidate for B1; K1 + K2 (1,000 + 2,000) is not used
    result = auto_match(
        [bank("B1", 15, "3000.00", "deposit")],
        [book("K1", 14, "1000.00", "deposit"), book("K2", 14, "2000.00", "deposit"),
         book("K3", 14, "3000.00", "deposit")],
    )
    assert groups(result) == [(("B1",), ("K3",), 2)]


def test_R03_matched_items_are_never_reused():
    result = auto_match(
        [bank("B1", 12, "500.00", ref="123456"), bank("B2", 12, "500.00")],
        [book("K1", 12, "500.00", ref="123456")],
    )
    assert groups(result) == [(("B1",), ("K1",), 1)]
    assert result.suggestions == []


def test_R03_empty_inputs():
    result = auto_match([], [])
    assert result.groups == [] and result.suggestions == []


# ------------------------------------------------------------------------------------------------ validate_match


def test_R04_match_that_ties_is_accepted():
    assert validate_match([bank("B1", 12, "600.00", "deposit")],
                          [book("K1", 12, "250.00", "deposit"), book("K2", 12, "350.00", "deposit")]) == []


def test_R04_difference_is_refused_with_indian_format_and_difference():
    errors = validate_match([bank("B1", 12, "100000.00", "deposit")], [book("K1", 12, "99000.00", "deposit")])
    assert [e.rule_id for e in errors] == ["R-04"]
    assert errors[0].message == (
        "The match does not tie: books 99,000.00 deposit and bank 1,00,000.00 deposit are not equal "
        "(difference 1,000.00)."
    )


def test_R04_opposite_directions_do_not_tie_even_with_equal_amounts():
    errors = validate_match([bank("B1", 12, "500.00", "deposit")], [book("K1", 12, "500.00", "payment")])
    assert [e.rule_id for e in errors] == ["R-04"]
    assert "(difference 1,000.00)" in errors[0].message


def test_R04_payments_and_deposits_net_off_on_one_side():
    # books: deposit 1,000 and payment 400 = net deposit 600; bank: one credit of 600
    assert validate_match([bank("B1", 12, "600.00", "deposit")],
                          [book("K1", 12, "1000.00", "deposit"), book("K2", 12, "400.00", "payment")]) == []


def test_R04_reversal_pair_with_no_bank_line_ties_at_nil():
    assert validate_match([], [book("K1", 12, "400.00", "payment"), book("K2", 13, "400.00", "deposit")]) == []


def test_R03_empty_match_is_refused():
    errors = validate_match([], [])
    assert [e.rule_id for e in errors] == ["R-03"]


def test_R03_same_item_twice_is_refused():
    k = book("K1", 12, "100.00", "deposit")
    errors = validate_match([bank("B1", 12, "200.00", "deposit")], [k, k])
    assert "R-03" in [e.rule_id for e in errors]
