"""Excel and JSON outputs of the TDS return working and certificate data (Phase 4, package D).

Input is the working as the service stores / returns it (amounts as 2-decimal strings). The structure is the tool's OWN:
the official statement file (FVU / TRACES upload format) is not produced, so every JSON file says
`unverified-own-structure` (the same way the GST exports say `unverified-against-portal-schema`). Form names come from the
rule tables (the working carries them). Excel: a Summary sheet with the rule statuses and warnings first, then one sheet per
table, amounts as numbers with 2 decimals. No accounting is done here.
"""

import io
import json
import re
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font

FORMAT_STATUS = "unverified-own-structure"
AMOUNT_KEYS = {
    "amount_paid", "taxable_base", "tax_deducted", "tax_deposited", "tax", "interest", "fee", "other", "total",
    "short_deposit", "challan_tax", "challan_interest", "challan_fee", "challan_other", "challan_total", "total_amount_paid",
    "total_deducted", "total_deposited",
}
RATE_KEYS = {"rate"}
_TWO = re.compile(r"^-?\d+\.\d{2}$")
_RATE = re.compile(r"^-?\d+(\.\d{1,4})?$")


def _cell(key: str, value):
    """(value, number_format): amount and rate strings become numbers; everything else stays text."""
    if isinstance(value, str):
        if key in AMOUNT_KEYS and _TWO.match(value):
            return Decimal(value), "0.00"
        if key in RATE_KEYS and _RATE.match(value):
            return Decimal(value), "0.00##"
    if isinstance(value, bool):
        return ("Yes" if value else "No"), None
    return value, None


def _table(wb: Workbook, name: str, rows: list[dict]) -> None:
    ws = wb.create_sheet(name[:31])
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    ws.append(columns)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        cells = [_cell(col, r.get(col)) for col in columns]
        ws.append([v for v, _ in cells])
        for cell, (_, fmt) in zip(ws[ws.max_row], cells, strict=True):
            if fmt:
                cell.number_format = fmt


def _rule_status_rows(ws, status: dict) -> None:
    ws.append(["Worst rule status", status.get("worst")])
    for table, st in status.get("tables", {}).items():
        ws.append([f"Rule status: {table}", st])
    for src in status.get("pending_sources", []):
        ws.append(["PENDING rule, to be verified", src])


def _messages(ws, label: str, items: list[dict]) -> None:
    for e in items:
        ws.append([label, f"{e['rule_id']}: {e['message']}"])


def _finish(wb: Workbook) -> bytes:
    ws = wb["Summary"]
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 100
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def working_to_xlsx(w: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"{w['form_no']} working (quarter {w['quarter']}, {w['financial_year']})"])
    ws["A1"].font = Font(bold=True, size=13)
    for label, key in (("Form (from rule table)", "form_no"), ("Form status", "form_status"), ("Return kind", "return_kind"),
                       ("Deductor TAN", "tan"), ("Period from", "period_start"), ("Period to", "period_end"),
                       ("Version", "version"), ("Status", "status")):
        ws.append([label, w.get(key)])
    ws.append(["File format", FORMAT_STATUS + " (not the official statement file)"])
    _rule_status_rows(ws, w["rule_status"])
    _messages(ws, "ERROR", w["errors"])
    _messages(ws, "Warning", w["warnings"])
    for k, v in w["totals"].items():
        value, fmt = _cell(k, v)
        ws.append([f"Total: {k}", value])
        if fmt:
            ws.cell(ws.max_row, 2).number_format = fmt
    _table(wb, "Deductee rows", w["deductee_rows"])
    _table(wb, "Challans", w["challan_rows"])
    return _finish(wb)


def working_json(w: dict) -> dict:
    """The working in the tool's own structure; amounts stay exact strings (no floats)."""
    return {
        "format_status": FORMAT_STATUS,
        "form_no": w["form_no"], "form_status": w["form_status"], "return_kind": w["return_kind"], "tan": w["tan"],
        "financial_year": w["financial_year"], "quarter": w["quarter"], "period_start": w["period_start"],
        "period_end": w["period_end"], "version": w.get("version"), "status": w.get("status"),
        "deductee_rows": w["deductee_rows"], "challan_rows": w["challan_rows"], "totals": w["totals"],
        "errors": w["errors"], "warnings": w["warnings"], "rule_status": w["rule_status"],
    }


def dumps(obj: dict) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=False).encode()


def certificate_to_xlsx(c: dict) -> bytes:
    """c: the stored certificate as get_certificate returns it (snapshot fields at top level + identity)."""
    d = c
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"{d['form_no']} certificate data"])
    ws["A1"].font = Font(bold=True, size=13)
    for label, value in (
        ("Form (from rule table)", d["form_no"]), ("Form status", d["form_status"]), ("Period", d["period"]),
        ("Version", c.get("version")), ("Certificate no", c.get("certificate_no")), ("Issued on", c.get("issued_on")),
        ("Deductor", d["deductor"]["name"]), ("Deductor TAN", d["deductor"]["tan"]), ("Deductor PAN", d["deductor"]["pan"]),
        ("Deductee", d["deductee"]["name"]), ("Deductee PAN", d["deductee"]["pan"]),
        ("File format", FORMAT_STATUS + " (not the official certificate)"),
    ):
        ws.append([label, value])
    _rule_status_rows(ws, c["rule_status"])
    for k in ("total_amount_paid", "total_deducted", "total_deposited"):
        value, fmt = _cell(k, d[k])
        ws.append([f"Total: {k}", value])
        ws.cell(ws.max_row, 2).number_format = fmt
    _table(wb, "Items", d["items"])
    _table(wb, "Challans", d["challans"])
    return _finish(wb)
