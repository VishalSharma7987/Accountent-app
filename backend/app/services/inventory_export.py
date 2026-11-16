"""Excel output of the inventory reports (Phase 5, package E). Input is the report as the service returns it (amounts as
2-decimal strings, quantities as 3-decimal strings); here they become numbers with number formats. No accounting is done."""

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font

_METHOD = {"fifo": "FIFO", "wa_periodic": "Weighted average (periodic)", "wa_moving": "Weighted average (moving)"}


def _num(text: str | None, places: int):
    if text is None:
        return None, None
    return Decimal(text), "0." + "0" * places


def _header(ws, title: str, report: dict, period_label: str) -> None:
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Valuation method", _METHOD.get(report["policy"]["valuation_method"], report["policy"]["valuation_method"])])
    ws.append(["Negative stock", report["policy"]["negative_stock_mode"]])
    ws.append([period_label, report.get("as_on") or f"{report.get('from')} to {report.get('to')}"])
    ws.append([])


def _table(ws, columns: list[tuple[str, str, int | None]], rows: list[dict]) -> None:
    """columns = (header, key, decimals or None for text)."""
    ws.append([c[0] for c in columns])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for row in rows:
        cells, formats = [], []
        for _, key, places in columns:
            if places is None:
                cells.append(row.get(key))
                formats.append(None)
            else:
                value, fmt = _num(row.get(key), places)
                cells.append(value)
                formats.append(fmt)
        ws.append(cells)
        for cell, fmt in zip(ws[ws.max_row], formats, strict=True):
            if fmt:
                cell.number_format = fmt


def _messages(wb: Workbook, report: dict) -> None:
    ws = wb.create_sheet("Findings")
    ws.append(["Severity", "Rule", "Date", "Message"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for e in report["errors"] + report["warnings"]:
        ws.append([e["severity"], e["rule_id"], e["date"], e["message"]])


def register_to_xlsx(report: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock register"
    _header(ws, "Stock register", report, "Period")
    if report.get("godown_name"):
        ws.append(["Godown", report["godown_name"]])
    _table(ws, [("SKU", "sku", None), ("Item", "name", None), ("Unit", "uqc", None),
                ("Opening qty", "opening_qty", 3), ("Opening value", "opening_value", 2),
                ("Inward qty", "inward_qty", 3), ("Inward value", "inward_value", 2),
                ("Outward qty", "outward_qty", 3), ("Outward value", "outward_value", 2),
                ("Closing qty", "closing_qty", 3), ("Closing value", "closing_value", 2)], report["rows"])
    if report.get("totals"):
        t = report["totals"]
        ws.append(["", "Total", "", None, *(_num(t["opening_value"], 2)[0], None, _num(t["inward_value"], 2)[0], None,
                                              _num(t["outward_value"], 2)[0], None, _num(t["closing_value"], 2)[0])])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
            if isinstance(cell.value, Decimal):
                cell.number_format = "0.00"
    _messages(wb, report)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def closing_stock_to_xlsx(report: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Closing stock"
    _header(ws, "Closing stock at lower of cost and net realisable value (AS 2)", report, "As on")
    _table(ws, [("SKU", "sku", None), ("Item", "name", None), ("Unit", "uqc", None), ("Closing qty", "closing_qty", 3),
                ("Cost value", "cost_value", 2), ("NRV per unit", "nrv_per_unit", 2), ("NRV value", "nrv_value", 2),
                ("Write-down", "write_down", 2), ("Carrying value", "carrying_value", 2)], report["rows"])
    t = report["totals"]
    ws.append(["", "Total", "", None, _num(t["cost_value"], 2)[0], None, None, _num(t["write_down"], 2)[0],
               _num(t["carrying_value"], 2)[0]])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
        if isinstance(cell.value, Decimal):
            cell.number_format = "0.00"
    _messages(wb, report)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
