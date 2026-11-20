"""Package B: Tally mapping rules (D-31, D-32, D-34, D-35, D-36, D-37). Hand-typed expectations."""

from datetime import date
from decimal import Decimal

from app.engine.tally_map import (
    resolve_group,
    skip_reason,
    source_refs,
    suggest_ledger,
    to_lines,
    voucher_type,
)

D = Decimal


def test_D31_predefined_group_maps_by_table():
    s = resolve_group("Sundry Debtors", {})
    assert (s.code, s.predefined) == ("sundry_debtors", True)
    assert resolve_group("  cash-in-HAND ", {}).code == "cash_in_hand"
    assert resolve_group("Duties & Taxes", {}).code == "duties_taxes"
    assert resolve_group("Bank OD A/c", {}).code == "loans_liability"


def test_D31_custom_group_maps_through_parent_chain():
    defined = {"retail debtors": "Sundry Debtors", "north zone": "Retail Debtors"}
    s = resolve_group("North Zone", defined)
    assert (s.code, s.predefined, s.chain) == ("sundry_debtors", False, ("North Zone", "Retail Debtors", "Sundry Debtors"))


def test_D31_unknown_parent_is_not_guessed():
    s = resolve_group("Orphan Group", {"orphan group": "Group That Is Nowhere"})
    assert s.code is None
    assert "Group That Is Nowhere" in s.reason


def test_D31_predefined_without_equivalent_needs_accountant():
    assert resolve_group("Misc. Expenses (ASSET)", {}).code is None


def test_D31_circle_is_reported_not_followed_forever():
    s = resolve_group("A", {"a": "B", "b": "A"})
    assert s.code is None and "circle" in s.reason


def test_D31_earlier_confirmed_custom_group_is_used():
    s = resolve_group("Staff Advances", {}, {"staff advances": "loans_advances_asset"})
    assert s.code == "loans_advances_asset"


def test_D31_ledger_without_parent_needs_decision():
    assert resolve_group(None, {}).code is None


def test_D32_existing_ledger_same_group_is_suggested_for_confirmation():
    g = resolve_group("Sundry Debtors", {})
    s = suggest_ledger("Rahul", g, "L1", "sundry_debtors")
    assert (s.existing_ledger_id, s.needs_decision, s.rule_id) == ("L1", False, "D-32")


def test_D32_existing_ledger_in_other_group_is_not_overwritten():
    g = resolve_group("Sundry Debtors", {})
    s = suggest_ledger("Rahul", g, "L1", "sundry_creditors", "Sundry Creditors")
    assert (s.existing_ledger_id, s.needs_decision, s.rule_id) == ("L1", True, "D-32")
    assert "Sundry Creditors" in s.reason


def test_D31_new_ledger_with_known_group_is_offered_for_creation_only():
    s = suggest_ledger("Rahul", resolve_group("Sundry Debtors", {}), None, None)
    assert (s.target_group_code, s.existing_ledger_id, s.needs_decision) == ("sundry_debtors", None, False)


def test_D34_voucher_type_table():
    assert [voucher_type(x) for x in ("Sales", "credit note", "DEBIT NOTE", "Journal", "Contra")] == [
        "sales", "credit_note", "debit_note", "journal", "contra"]
    assert voucher_type("Stock Journal") is None
    assert voucher_type("Delivery Note") is None


def test_D34_unsupported_type_is_skipped_with_reason():
    rule, reason = skip_reason("Stock Journal", False, False, False)
    assert rule == "D-34" and "Stock Journal" in reason


def test_D36_cancelled_optional_postdated_are_skipped():
    assert skip_reason("Sales", True, False, False)[0] == "D-36"
    assert skip_reason("Sales", False, True, False)[0] == "D-36"
    assert skip_reason("Sales", False, False, True)[0] == "D-36"
    assert skip_reason("Sales", False, False, False) is None


def test_D35_sign_convention_converts_to_debit_and_credit():
    lines, problems = to_lines([("Rahul", D("-11800.00"), True), ("Sales", D("10000.00"), False), ("IGST", D("1800.00"), False)])
    assert problems == []
    assert [(x.ledger_name, x.debit, x.credit) for x in lines] == [
        ("Rahul", D("11800.00"), D("0.00")), ("Sales", D("0.00"), D("10000.00")), ("IGST", D("0.00"), D("1800.00"))]


def test_D35_contradicting_entry_is_reported_not_guessed():
    lines, problems = to_lines([("Rahul", D("100.00"), True), ("Sales", D("100.00"), False)])
    assert [x.ledger_name for x in lines] == ["Sales"]
    assert len(problems) == 1 and "'Rahul'" in problems[0] and "cannot be decided" in problems[0]


def test_D35_zero_entry_is_dropped_and_reported():
    lines, problems = to_lines([("Rahul", D("0.00"), True), ("Sales", D("5.00"), False)])
    assert [x.ledger_name for x in lines] == ["Sales"]
    assert "zero amount" in problems[0]


def test_D37_reference_is_guid_when_present_else_fallback_hash():
    ref, fallback = source_refs("guid-1", "Sales", date(2026, 4, 15), "1", "Rahul", D("11800.00"))
    assert ref == "guid-1" and fallback.startswith("tvh:") and len(fallback) == 68
    ref2, fallback2 = source_refs(None, "Sales", date(2026, 4, 15), "1", "Rahul", D("11800.00"))
    assert ref2 == fallback2 == fallback


def test_D37_fallback_ignores_case_and_spacing_but_not_amount_or_number():
    base = source_refs(None, "Sales", date(2026, 4, 15), "1", "Rahul  Enterprises", D("100.00"))[1]
    assert source_refs(None, "sales", date(2026, 4, 15), "1", "rahul enterprises", D("100.00"))[1] == base
    assert source_refs(None, "Sales", date(2026, 4, 15), "1", "Rahul Enterprises", D("100.01"))[1] != base
    assert source_refs(None, "Sales", date(2026, 4, 15), "2", "Rahul Enterprises", D("100.00"))[1] != base
