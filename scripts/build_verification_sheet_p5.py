"""Builds the printable verification sheet (Excel) for the Phase 5 (Inventory) test pack.

    python scripts/build_verification_sheet_p5.py [docs/test-packs/phase5-fresh-pharma-apr-2026]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the inputs and the
hand-typed expected answers); no figure is computed here. The accountants re-work each section, tick it and sign.
Same look as the Phase 1-4 sheets (scripts/build_verification_sheet.py).
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase5-fresh-pharma-apr-2026"
NUMERIC = {  # columns shown as Indian-format numbers
    "value", "unit_rate", "opening_value", "inward_value", "outward_value", "closing_value", "cost_value", "nrv_per_unit",
    "nrv_value", "write_down", "carrying_value",
}
NOTE = ("Goods are HSN 3004, IGST 5% (example row of the rule table). GST is not part of stock cost. "
        "Quantities have 3 decimals. FIFO, weighted average periodic and weighted average moving are run as three clients.")


def read(pack: Path, name: str) -> list[dict]:
    with open(pack / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cell(column: str, text: str):
    if column in NUMERIC and text not in ("", None):
        try:
            return Decimal(text)
        except ArithmeticError:
            return text
    return text


def table_sheet(wb: Workbook, name: str, heading: str, pack_name: str, rows: list[dict], columns: list[str],
                widths: list[float], note: str = "") -> None:
    ws = wb.create_sheet(name)
    ncols = len(columns) + 1
    title(ws, heading, pack_name, ncols)
    header(ws, 2, columns + ["Your check"])
    money = tuple(i for i, c in enumerate(columns, start=1) if c in NUMERIC)
    row = 3
    for r in rows:
        put(ws, row, [cell(c, r.get(c, "")) for c in columns] + ["[   ]"], money)
        row += 1
    if note:
        put(ws, row + 1, [note] + [""] * (ncols - 1))
    page(ws, 2, widths + [10])


def build(pack: Path) -> Path:
    name = f"Fresh Pharma Traders - Phase 5 Inventory pack ({pack.name})"
    wb = Workbook()

    ws = wb.active
    ws.title = "1 Setup"
    title(ws, "Godowns, items and opening stock 01-04-2026 (inputs)", name, 6)
    header(ws, 2, ["Item", "Detail 1", "Detail 2", "Detail 3", "Detail 4", "Your check"])
    row = 3
    for r in read(pack, "godowns.csv"):
        put(ws, row, ["Godown " + r["godown_name"], "", "", "", "", "[   ]"])
        row += 1
    for r in read(pack, "items.csv"):
        put(ws, row, ["Item " + r["item_name"], "SKU " + r["sku"], f"HSN {r['hsn_sac']}", r["uqc"], "default godown " + r["default_godown"], "[   ]"])
        row += 1
    for r in read(pack, "opening.csv"):
        put(ws, row, ["Opening " + r["item_name"], r["godown_name"], f"qty {r['quantity']}", f"value {r['value']}", "", "[   ]"])
        row += 1
    put(ws, row + 1, ["Method of the three clients: FIFO, weighted average periodic, weighted average moving; negative stock: block   [   ]", "", "", "", "", ""])
    page(ws, 2, [44, 24, 20, 20, 30, 10])

    table_sheet(wb, "2 Vouchers", "Invoices and notes (item lines) posted in date order", name, read(pack, "vouchers.csv"),
                ["ref_id", "date", "voucher_type", "narration", "reference_no", "original_ref", "item_name", "quantity", "unit_rate"],
                [8, 11, 12, 44, 12, 10, 24, 10, 10], NOTE)
    table_sheet(wb, "3 Stock journals", "Write-off (with reason) and transfer between godowns", name, read(pack, "journals.csv"),
                ["ref_id", "journal_type", "date", "item_name", "from_godown_name", "to_godown_name", "quantity", "reason_code", "reason_note"],
                [8, 12, 11, 24, 10, 10, 10, 10, 50])
    table_sheet(wb, "4 Numbers", "Document numbers assigned at posting", name, read(pack, "expected_vouchers.csv"),
                ["ref_id", "voucher_number"], [8, 22])
    table_sheet(wb, "5 Register", "Stock register 01-04-2026 to 30-04-2026 by method (hand-worked, WORKING.md)", name,
                read(pack, "expected_register.csv"),
                ["method", "item_name", "opening_qty", "opening_value", "inward_qty", "inward_value", "outward_qty", "outward_value",
                 "closing_qty", "closing_value"], [12, 24, 11, 12, 11, 12, 11, 12, 11, 12],
                "Weighted average periodic: a sales return is shown as less outward quantity (A outward 320), the purchase return as outward at its own cost.")
    table_sheet(wb, "5b Register totals", "Totals of the register", name, read(pack, "expected_register_totals.csv"),
                ["method", "opening_value", "inward_value", "outward_value", "closing_value"], [12, 14, 14, 14, 14])
    table_sheet(wb, "6 Movement cost", "Cost of every movement as the tool must show it (item ledger)", name,
                read(pack, "expected_movement_cost.csv"), ["method", "ref_id", "item_name", "kind", "quantity", "value"],
                [12, 8, 24, 16, 10, 12], "Transfers carry quantity only (value 0.00). Returns are valued at the cost of the movement they refer to.")
    table_sheet(wb, "7 By godown", "Closing quantity by godown (same in all methods)", name, read(pack, "expected_by_godown.csv"),
                ["item_name", "godown_name", "closing_qty"], [26, 12, 12])
    table_sheet(wb, "8 NRV entered", "Net realisable value entered per item as on 30-04-2026", name, read(pack, "nrv.csv"),
                ["item_name", "as_on_date", "nrv_per_unit", "basis_note"], [26, 12, 12, 70])
    table_sheet(wb, "9 Closing stock", "Closing stock at lower of cost and NRV, item by item (AS 2)", name,
                read(pack, "expected_closing_stock.csv"),
                ["method", "item_name", "closing_qty", "cost_value", "nrv_per_unit", "nrv_value", "write_down", "carrying_value"],
                [12, 24, 11, 12, 11, 12, 12, 14], "Vitamin C has no NRV entered: shown at cost with a warning (S-15), no write-down guessed.")
    table_sheet(wb, "9b Closing totals", "Closing stock totals", name, read(pack, "expected_closing_totals.csv"),
                ["method", "cost_value", "write_down", "carrying_value", "items_without_nrv"], [12, 14, 14, 14, 26])
    table_sheet(wb, "10 Wrong cases", "Deliberately wrong entries: the tool must refuse each with the rule named", name,
                read(pack, "wrong_cases.csv"), ["case_id", "kind", "date", "item_name", "quantity", "expected_rule", "description"],
                [8, 12, 11, 24, 10, 10, 70])

    ws = wb.create_sheet("11 Sign-off")
    title(ws, "Sign-off", name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""),
        ("Method (stock cards on paper / Tally / Excel)", ""), ("", ""),
        ("[   ] FIFO, weighted average periodic and moving closing stock of items A and B (sheet 5, WORKING.md)", ""),
        ("[   ] Cost of every sale, write-off and return per method (sheet 6)", ""),
        ("[   ] Sales return at the cost of the original sale; purchase return at the cost of the original purchase", ""),
        ("[   ] Transfer: quantity by godown changes, value does not (sheets 6, 7)", ""),
        ("[   ] Write-off has a reason and is valued at the method's cost", ""),
        ("[   ] AS 2: lower of cost and NRV per item, write-down shown, no netting (sheet 9)", ""),
        ("[   ] No negative stock, also per godown (sheet 10, W1 to W3, W7)", ""),
        ("[   ] Questions in SIGNOFF.md answered (returns at original cost, periodic windows, per item not per godown, freight, purchase return presentation)", ""),
        ("[   ] Data is dummy / synthetic", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b], fill=TOTAL_FILL if a.startswith("Result") else None)
        ws.row_dimensions[i].height = 22
    page(ws, 1, [110, 40])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
