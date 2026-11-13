"""Stock journal rules S-10 / S-11 (+ S-01, S-02, S-03, S-07, S-17 as they apply to journals), pure engine. Expected values typed by hand."""

import uuid
from datetime import date
from decimal import Decimal

from app.engine.inventory_journals import (
    JournalFacts,
    JournalInput,
    JournalLineInput,
    check_stock_chain,
    check_transition,
    mirror_movements,
    planned_movements,
    validate_journal,
    validate_reversal,
)
from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    MovementKind,
    NegativeStockMode,
    OpeningStock,
    ValuationMethod,
)

ITEM, ITEM2 = uuid.uuid4(), uuid.uuid4()
MAIN, SHOP, OLD = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
FY = (date(2026, 4, 1), date(2027, 3, 31))
FACTS = JournalFacts(
    items={ITEM: True, ITEM2: False},
    godowns={MAIN: True, SHOP: True, OLD: False},
    fy_ranges=[FY],
    periods=[(date(2026, 4, 1), date(2026, 4, 30), "open"), (date(2026, 5, 1), date(2026, 5, 31), "locked")],
)


def transfer(lines, on=date(2026, 4, 10), narration="Move to shop"):
    return JournalInput("transfer", on, narration, None, None, lines)


def writeoff(lines, code="damage", note="Water damage", on=date(2026, 4, 10)):
    return JournalInput("write_off", on, "Write off", code, note, lines)


def ids(errors):
    return [e.rule_id for e in errors]


def test_S10_valid_transfer_has_no_errors_and_parses_quantity():
    errors, lines = validate_journal(transfer([JournalLineInput(ITEM, MAIN, SHOP, "5.5")]), FACTS)
    assert errors == []
    assert lines[0].quantity == Decimal("5.500") and lines[0].line_no == 1


def test_S10_journal_needs_a_line():
    errors, _ = validate_journal(transfer([]), FACTS)
    assert ids(errors) == ["S-10"]


def test_S10_transfer_godowns_must_differ_and_destination_is_required():
    errors, _ = validate_journal(transfer([JournalLineInput(ITEM, MAIN, MAIN, "1"), JournalLineInput(ITEM, MAIN, None, "1")]), FACTS)
    assert [(e.rule_id, e.line_no) for e in errors] == [("S-10", 1), ("S-10", 2)]


def test_S10_writeoff_has_no_destination_and_needs_reason_code_and_note():
    errors, _ = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, SHOP, "1")]), FACTS)
    assert [(e.rule_id, e.line_no) for e in errors] == [("S-10", 1)]
    errors, _ = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, None, "1")], code=None), FACTS)
    assert ids(errors) == ["S-10"]
    errors, _ = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, None, "1")], note="  "), FACTS)
    assert ids(errors) == ["S-10"]
    errors, _ = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, None, "1")], code="fire"), FACTS)
    assert ids(errors) == ["S-10"]
    errors, lines = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, None, "1")]), FACTS)
    assert errors == [] and lines[0].to_godown_id is None


def test_S10_transfer_carries_no_reason():
    j = JournalInput("transfer", date(2026, 4, 10), "x", "damage", None, [JournalLineInput(ITEM, MAIN, SHOP, "1")])
    errors, _ = validate_journal(j, FACTS)
    assert ids(errors) == ["S-10"]


def test_S10_unknown_type_and_blank_narration():
    errors, _ = validate_journal(JournalInput("sale", date(2026, 4, 10), "x", None, None, []), FACTS)
    assert "S-10" in ids(errors)
    errors, _ = validate_journal(transfer([JournalLineInput(ITEM, MAIN, SHOP, "1")], narration=" "), FACTS)
    assert ids(errors) == ["V-09"]


def test_S02_quantity_fourth_decimal_rejected_not_rounded_and_zero_rejected():
    errors, _ = validate_journal(transfer([JournalLineInput(ITEM, MAIN, SHOP, "1.0005"), JournalLineInput(ITEM, MAIN, SHOP, "0")]), FACTS)
    assert [(e.rule_id, e.line_no) for e in errors] == [("S-02", 1), ("S-02", 2)]


def test_S03_item_must_be_an_active_stock_item():
    errors, _ = validate_journal(transfer([JournalLineInput(ITEM2, MAIN, SHOP, "1"), JournalLineInput(uuid.uuid4(), MAIN, SHOP, "1")]), FACTS)
    assert [(e.rule_id, e.line_no) for e in errors] == [("S-03", 1), ("S-03", 2)]


def test_S07_godown_must_exist_and_be_active():
    errors, _ = validate_journal(transfer([JournalLineInput(ITEM, OLD, SHOP, "1"), JournalLineInput(ITEM, MAIN, uuid.uuid4(), "1")]), FACTS)
    assert [(e.rule_id, e.line_no) for e in errors] == [("S-07", 1), ("S-07", 2)]


def test_S20_date_inside_a_year_and_open_period():
    line = [JournalLineInput(ITEM, MAIN, SHOP, "1")]
    errors, _ = validate_journal(transfer(line, on=date(2025, 3, 31)), FACTS)
    assert ids(errors) == ["V-06"]
    errors, _ = validate_journal(transfer(line, on=date(2026, 5, 15)), FACTS)
    assert ids(errors) == ["V-07"] and "01-05-2026 to 31-05-2026" in errors[0].message
    errors, _ = validate_journal(transfer(line, on=date(2026, 6, 15)), FACTS)
    assert ids(errors) == ["V-07"] and "No period" in errors[0].message


def test_S11_status_path():
    assert check_transition("draft", "update") is None
    assert check_transition("draft", "delete") is None
    assert check_transition("draft", "approve") is None
    assert check_transition("approved", "post") is None
    assert check_transition("posted", "reverse") is None
    assert check_transition("posted", "update") == "A posted stock journal cannot be edited; reverse it instead."
    assert check_transition("posted", "delete") == "A posted stock journal cannot be deleted; reverse it instead."
    assert check_transition("draft", "post") == "Only an approved stock journal can be posted (this one is draft)."
    assert check_transition("draft", "reverse") == "Only a posted stock journal can be reversed (this one is draft)."
    assert check_transition("reversed", "reverse") == "This stock journal has already been reversed."
    assert check_transition("approved", "approve") == "Only a draft stock journal can be approved (this one is approved)."
    assert check_transition("reversed", "update") == "A reversed stock journal cannot be edited."


def test_S11_reversal_needs_reason_and_date_in_the_journal_year_and_open_period():
    ok = {"journal_fy": FY, "fy_ranges": [FY], "periods": FACTS.periods}
    assert validate_reversal("Wrong godown", date(2026, 4, 12), **ok) == []
    assert ids(validate_reversal("  ", date(2026, 4, 12), **ok)) == ["S-11"]
    two_years = [FY, (date(2027, 4, 1), date(2028, 3, 31))]
    assert ids(validate_reversal("x", date(2027, 4, 2), journal_fy=FY, fy_ranges=two_years, periods=FACTS.periods)) == ["S-20"]
    assert ids(validate_reversal("x", date(2026, 5, 2), **ok)) == ["V-07"]


def test_S10_planned_movements_transfer_out_then_in_writeoff_single():
    line = validate_journal(transfer([JournalLineInput(ITEM, MAIN, SHOP, "4")]), FACTS)[1][0]
    t = planned_movements("transfer", [line])
    assert [(p.line_no, p.kind, p.godown_id, p.quantity) for p in t] == [
        (1, MovementKind.TRANSFER_OUT, MAIN, Decimal("4.000")), (1, MovementKind.TRANSFER_IN, SHOP, Decimal("4.000"))]
    line = validate_journal(writeoff([JournalLineInput(ITEM, MAIN, None, "2")]), FACTS)[1][0]
    w = planned_movements("write_off", [line])
    assert [(p.kind, p.godown_id, p.quantity) for p in w] == [(MovementKind.WRITE_OFF, MAIN, Decimal("2.000"))]


def _mv(kind, godown, qty, seq, on=date(2026, 4, 10), ref=None):
    return Movement(uuid.uuid4(), seq, on, ITEM, godown, kind, Decimal(qty), None, ref)


def test_S17_mirror_of_each_kind():
    out, inn, wo = (_mv(MovementKind.TRANSFER_OUT, MAIN, "4", 1), _mv(MovementKind.TRANSFER_IN, SHOP, "4", 2),
                    _mv(MovementKind.WRITE_OFF, MAIN, "2", 3))
    mirrors = mirror_movements([out, inn, wo])
    assert [(m.kind, m.godown_id, m.quantity, m.ref_movement_id) for m in mirrors] == [
        (MovementKind.REVERSAL_IN, MAIN, Decimal(4), out.movement_id),
        (MovementKind.REVERSAL_OUT, SHOP, Decimal(4), inn.movement_id),
        (MovementKind.REVERSAL_IN, MAIN, Decimal(2), wo.movement_id)]


POLICY_BLOCK = InventoryPolicy(ValuationMethod.FIFO, NegativeStockMode.BLOCK)
POLICY_WARN = InventoryPolicy(ValuationMethod.FIFO, NegativeStockMode.WARN)
OPEN = [OpeningStock(ITEM, MAIN, Decimal(10), Decimal("100.00"))]


def _chain(policy, new):
    return check_stock_chain(policy, FY[0], FY[1], OPEN, [], new, {ITEM})


def test_S01_transfer_more_than_on_hand_is_blocked_in_block_mode():
    new = [_mv(MovementKind.TRANSFER_OUT, MAIN, "11", 100), _mv(MovementKind.TRANSFER_IN, SHOP, "11", 101)]
    errors = _chain(POLICY_BLOCK, new)
    assert [(e.rule_id, e.severity, e.godown_id) for e in errors] == [("S-01", "error", MAIN)]
    assert "-1.000" in errors[0].message and "10-04-2026" in errors[0].message


def test_S01_same_finding_is_a_warning_in_warn_mode():
    errors = _chain(POLICY_WARN, [_mv(MovementKind.WRITE_OFF, MAIN, "11", 100)])
    assert [(e.rule_id, e.severity) for e in errors] == [("S-01", "warning")]


def test_S01_exact_stock_is_fine_and_transfer_value_is_untouched():
    new = [_mv(MovementKind.TRANSFER_OUT, MAIN, "10", 100), _mv(MovementKind.TRANSFER_IN, SHOP, "10", 101)]
    assert _chain(POLICY_BLOCK, new) == []


def test_S19_backdated_journal_rechecks_later_sale():
    """A transfer of 6 dated 05-04 leaves 4 in Main; a later sale of 7 from Main (10-04) would then go negative."""
    sale = _mv(MovementKind.SALE, MAIN, "7", 5, on=date(2026, 4, 10))
    new = [_mv(MovementKind.TRANSFER_OUT, MAIN, "6", 100, on=date(2026, 4, 5)),
           _mv(MovementKind.TRANSFER_IN, SHOP, "6", 101, on=date(2026, 4, 5))]
    errors = check_stock_chain(POLICY_BLOCK, FY[0], FY[1], OPEN, [sale], new, {ITEM})
    assert [(e.rule_id, e.severity, e.on_date) for e in errors] == [("S-01", "error", date(2026, 4, 10))]


def test_S01_findings_of_other_items_are_not_attributed_to_this_journal():
    other = Movement(uuid.uuid4(), 1, date(2026, 4, 2), ITEM2, MAIN, MovementKind.SALE, Decimal(3))
    new = [_mv(MovementKind.TRANSFER_OUT, MAIN, "1", 100), _mv(MovementKind.TRANSFER_IN, SHOP, "1", 101)]
    assert check_stock_chain(POLICY_BLOCK, FY[0], FY[1], OPEN, [other], new, {ITEM}) == []
