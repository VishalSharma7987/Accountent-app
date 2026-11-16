"""Phase 5 package E engine: register assembly (item level and by godown), item ledger, NRV entry rule S-15.
Expected values typed by hand from the plan's worked example (FIFO): opening 100 @ 10 = 1,000; 05-04 buy 200 = 2,400;
10-04 sell 150 (cost 1,600); 15-04 buy 100 = 1,500; 20-04 sell 180 (cost 2,250); closing 70 = 1,050."""

from datetime import date
from decimal import Decimal

from app.engine.inventory_report import (
    ItemMeta,
    item_ledger,
    register_lines,
    register_totals,
    validate_nrv_row,
)
from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    OpeningStock,
)
from app.engine.inventory_types import MovementKind as K
from app.engine.inventory_types import ValuationMethod as VM
from app.engine.inventory_valuation import compute_valuation

D = Decimal
START, END = date(2026, 4, 1), date(2027, 3, 31)
POLICY = InventoryPolicy(VM.FIFO)
META = {"I1": ItemMeta("W-1", "Widget", "NOS")}
OPEN = [OpeningStock("I1", "G1", D("100"), D("1000.00"))]
MOVES = [
    Movement("p1", 1, date(2026, 4, 5), "I1", "G2", K.PURCHASE, D("200"), D("2400.00")),
    Movement("s1", 2, date(2026, 4, 10), "I1", "G2", K.SALE, D("150")),
    Movement("p2", 3, date(2026, 4, 15), "I1", "G1", K.PURCHASE, D("100"), D("1500.00")),
    Movement("s2", 4, date(2026, 4, 20), "I1", "G1", K.SALE, D("180")),
]
DOCS = {"p1": "PUR/2026-27/0001", "s1": "SAL/2026-27/0001", "p2": "PUR/2026-27/0002", "s2": "SAL/2026-27/0002"}


def result(from_date=START, to_date=END):
    return compute_valuation(POLICY, from_date, to_date, OPEN, MOVES)


def test_S16_register_item_level_fifo():
    (line,) = register_lines(result(), META, OPEN, MOVES, START, END)
    assert (line.sku, line.name, line.uqc) == ("W-1", "Widget", "NOS")
    assert (line.opening_qty, line.opening_value) == (D("100"), D("1000.00"))
    assert (line.inward_qty, line.inward_value) == (D("300"), D("3900.00"))
    assert (line.outward_qty, line.outward_value) == (D("330"), D("3850.00"))
    assert (line.closing_qty, line.closing_value) == (D("70"), D("1050.00"))
    assert line.by_godown == {"G1": D("20"), "G2": D("50")}


def test_S16_register_totals_sum_value_columns():
    rows = register_lines(result(), META, OPEN, MOVES, START, END)
    assert register_totals(rows) == {"opening_value": D("1000.00"), "inward_value": D("3900.00"),
                                     "outward_value": D("3850.00"), "closing_value": D("1050.00")}


def test_S01_register_by_godown_has_quantities_only():
    (g1,) = register_lines(result(), META, OPEN, MOVES, START, END, godown_id="G1")
    assert (g1.opening_qty, g1.inward_qty, g1.outward_qty, g1.closing_qty) == (D("100"), D("100"), D("180"), D("20"))
    assert g1.opening_value is None and g1.inward_value is None and g1.outward_value is None and g1.closing_value is None
    (g2,) = register_lines(result(), META, OPEN, MOVES, START, END, godown_id="G2")
    assert (g2.opening_qty, g2.inward_qty, g2.outward_qty, g2.closing_qty) == (D("0"), D("200"), D("150"), D("50"))


def test_S01_register_by_godown_window_opening_includes_earlier_movements():
    # window from 10-04: G2 opened the window with the 200 bought on 05-04
    (g2,) = register_lines(result(date(2026, 4, 10)), META, OPEN, MOVES, date(2026, 4, 10), END, godown_id="G2")
    assert (g2.opening_qty, g2.inward_qty, g2.outward_qty, g2.closing_qty) == (D("200"), D("0"), D("150"), D("50"))


def test_S16_register_godown_without_stock_or_activity_is_left_out():
    assert register_lines(result(), META, OPEN, MOVES, START, END, godown_id="G9") == []


def test_S13_item_ledger_running_balance_with_computed_cost():
    lines = item_ledger(result(), "I1", DOCS)
    got = [(x.doc_number, x.in_qty, x.in_value, x.out_qty, x.out_value, x.balance_qty, x.balance_value) for x in lines]
    assert got == [
        ("PUR/2026-27/0001", D("200"), D("2400.00"), D("0"), D("0.00"), D("300"), D("3400.00")),
        ("SAL/2026-27/0001", D("0"), D("0.00"), D("150"), D("1600.00"), D("150"), D("1800.00")),
        ("PUR/2026-27/0002", D("100"), D("1500.00"), D("0"), D("0.00"), D("250"), D("3300.00")),
        ("SAL/2026-27/0002", D("0"), D("0.00"), D("180"), D("2250.00"), D("70"), D("1050.00")),
    ]
    assert [x.kind for x in lines] == [K.PURCHASE, K.SALE, K.PURCHASE, K.SALE]


def test_S13_item_ledger_window_starts_from_window_opening():
    lines = item_ledger(result(date(2026, 4, 10)), "I1", DOCS)
    assert [x.doc_number for x in lines] == ["SAL/2026-27/0001", "PUR/2026-27/0002", "SAL/2026-27/0002"]
    assert (lines[0].balance_qty, lines[0].balance_value) == (D("150"), D("1800.00"))  # 300 / 3,400 less 150 / 1,600


def test_S15_nrv_row_valid():
    assert validate_nrv_row("I1", D("13.50"), "Market quote 12-05") == []
    assert validate_nrv_row("I1", D("0"), "Obsolete") == []


def test_S15_nrv_row_negative_rejected():
    (e,) = validate_nrv_row("I1", D("-1.00"), "x")
    assert e.rule_id == "S-15"


def test_S15_nrv_row_three_decimals_rejected_not_rounded():
    (e,) = validate_nrv_row("I1", D("13.505"), "x")
    assert e.rule_id == "S-15" and "2 decimal" in e.message


def test_S15_nrv_row_blank_basis_rejected():
    (e,) = validate_nrv_row("I1", D("13.50"), "   ")
    assert e.rule_id == "S-15" and "basis" in e.message
