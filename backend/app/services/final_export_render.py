"""Renders an export document to Excel (openpyxl) and PDF (reportlab). Phase 6 package E, rules F-70 / F-71.

Input is a plain dict built by `services/final_export.py` (no database here, no accounting maths: every figure is already in the
statement dicts of packages A..D). Document shape:
  {"title", "client", "fy_label", "engine_version", "header": [(label, text)], "ledgers": [ledger position dicts],
   "sections": [{"name", "title", "header": [(label, text)], "warnings": [text], "statement": {...} | None,
                 "columns": [(key, label, kind)], "rows": [dict], "totals": dict | None, "footnotes": [text]}]}
Amounts in statement dicts are 2-decimal strings; in tables they may be Decimal. Excel holds amounts as numbers (2 decimals); the PDF
prints Indian grouping (1,00,000.00) and brackets for negative figures.
"""

import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.hyperlink import Hyperlink
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.engine.money import format_inr

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
AMOUNT_FORMAT = "#,##0.00;(#,##0.00)"
LEDGER_FIRST_ROW = 8                      # first data row of the Ledgers sheet (hyperlink target rows are computed from it)
MAX_SHEET = 31
BOLD = Font(bold=True)
GREY = PatternFill("solid", fgColor="E7E6E6")


# ============================================================================================ shared helpers


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _inr(value: Any, brackets: bool = True) -> str:
    d = _dec(value)
    if d is None:
        return ""
    return f"({format_inr(abs(d))})" if d < 0 and brackets else format_inr(d)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value)
    return str(value)


def _is_heading(line: dict) -> bool:
    return str(line.get("code", "")).startswith("heading:")


def _drill_text(line: dict) -> str:
    return "; ".join(f"{d['ledger_name']}: {_inr(d['amount'])}" for d in line.get("drill", []))


def _drill_is_obvious(line: dict) -> bool:
    drill = line.get("drill", [])
    return not drill or (len(drill) == 1 and drill[0]["ledger_name"] == line.get("label"))


def _side_balance(value: Any) -> str:
    d = _dec(value) or Decimal(0)
    return "" if d == 0 else (f"{format_inr(abs(d))} Dr" if d > 0 else f"{format_inr(abs(d))} Cr")


def _is_horizontal(statement: dict) -> bool:
    return bool(statement.get("right")) or statement.get("format") == "horizontal"


def _pair_rows(statement: dict) -> list[tuple[dict | None, dict | None]]:
    """Horizontal statements: debit side and credit side side by side, the grand totals on one row at the bottom."""
    left, right = list(statement["left"]), list(statement["right"])
    tail: tuple[dict | None, dict | None] | None = None
    if left and right and left[-1].get("code") == "total" and right[-1].get("code") == "total":
        tail = (left.pop(), right.pop())
    rows = [(left[i] if i < len(left) else None, right[i] if i < len(right) else None) for i in range(max(len(left), len(right)))]
    if tail:
        rows.append(tail)
    return rows


def _show_previous(statement: dict) -> bool:
    return any(x.get("previous_amount") is not None for x in statement["left"]) or statement.get("format") == "sch3"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "export"


# ============================================================================================ Excel


def _sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", " ", name)[:MAX_SHEET] or "Sheet"
    candidate, n = base, 2
    while candidate.lower() in used:
        candidate = f"{base[:MAX_SHEET - 3]} {n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _link(cell, row: int) -> None:
    cell.hyperlink = Hyperlink(ref=cell.coordinate, location=f"'Ledgers'!A{row}")
    cell.font = Font(color="0563C1", underline="single")


def _amount_cell(ws, row: int, col: int, value: Any, *, bold: bool = False):
    d = _dec(value)
    cell = ws.cell(row=row, column=col, value=d)
    if d is not None:
        cell.number_format = AMOUNT_FORMAT
    if bold:
        cell.font = BOLD
    return cell


def _header_block(ws, doc: dict, section: dict) -> int:
    ws.cell(row=1, column=1, value=section["title"]).font = Font(bold=True, size=14)
    row = 2
    for label, text in [("Client", doc["client"]), ("Financial year", doc["fy_label"]), *doc.get("header", []), *section.get("header", []),
                        ("Engine version", doc["engine_version"])]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=2, value=text)
        row += 1
    for warning in section.get("warnings", []):
        cell = ws.cell(row=row, column=1, value=warning)
        cell.font = Font(bold=True, color="9C5700")
        row += 1
    return row + 1


def _ledger_refs(line: dict, rows: dict[str, tuple[int, str]]) -> tuple[str, int | None]:
    refs, first = [], None
    for d in line.get("drill", []):
        hit = rows.get(str(d["ledger_id"])) if d.get("ledger_id") else None
        if hit is not None:
            refs.append(hit[1])
            first = hit[0] if first is None else first
    return ", ".join(refs), first


def _write_statement(ws, start: int, statement: dict, rows: dict[str, tuple[int, str]]) -> None:
    row = start
    index: list[tuple[str, dict]] = []
    if _is_horizontal(statement):
        heads = ["Particulars", "Amount", "Ledgers (drill-down)", "Ledger ref", "", "Particulars", "Amount", "Ledgers (drill-down)", "Ledger ref"]
        for i, h in enumerate(heads, 1):
            ws.cell(row=row, column=i, value=h).font = BOLD
            ws.cell(row=row, column=i).fill = GREY
        row += 1
        for left, right in _pair_rows(statement):
            for offset, line in ((1, left), (6, right)):
                if line is None:
                    continue
                bold = bool(line.get("is_total"))
                ws.cell(row=row, column=offset, value=line["label"]).font = Font(bold=bold)
                _amount_cell(ws, row, offset + 1, line["amount"], bold=bold)
                ws.cell(row=row, column=offset + 2, value=_drill_text(line) if not _drill_is_obvious(line) else "")
                refs, target = _ledger_refs(line, rows)
                cell = ws.cell(row=row, column=offset + 3, value=refs)
                if target is not None:
                    _link(cell, target)
                index += [(line["label"], d) for d in line.get("drill", [])]
            row += 1
        widths = [34, 16, 40, 12, 3, 34, 16, 40, 12]
    else:
        previous = _show_previous(statement)
        heads = ["Particulars", "Note", "Amount", *(["Previous year"] if previous else []), "Ledgers (drill-down)", "Ledger ref"]
        for i, h in enumerate(heads, 1):
            ws.cell(row=row, column=i, value=h).font = BOLD
            ws.cell(row=row, column=i).fill = GREY
        row += 1
        for line in statement["left"]:
            heading = _is_heading(line)
            bold = heading or bool(line.get("is_total"))
            cell = ws.cell(row=row, column=1, value=line["label"])
            cell.font = Font(bold=bold)
            cell.alignment = Alignment(indent=2 * int(line.get("level", 0)))
            ws.cell(row=row, column=2, value=line.get("note_no"))
            col = 3
            if not heading:
                _amount_cell(ws, row, col, line["amount"], bold=bold)
            col += 1
            if previous:
                if line.get("previous_amount") is None and not heading:
                    ws.cell(row=row, column=col, value="-")
                else:
                    _amount_cell(ws, row, col, line.get("previous_amount"), bold=bold)
                col += 1
            ws.cell(row=row, column=col, value=_drill_text(line) if not _drill_is_obvious(line) else "")
            refs, target = _ledger_refs(line, rows)
            cell = ws.cell(row=row, column=col + 1, value=refs)
            if target is not None:
                _link(cell, target)
            index += [(line["label"], d) for d in line.get("drill", [])]
            row += 1
        widths = [58, 7, 18, *([18] if previous else []), 50, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    row += 1
    row = _totals_block(ws, row, statement)
    _drill_index(ws, row + 1, index, rows)
    _notes(ws, ws.max_row + 2, statement)


def _totals_block(ws, row: int, statement: dict) -> int:
    if not statement.get("totals"):
        return row
    ws.cell(row=row, column=1, value="Totals").font = BOLD
    row += 1
    for key, value in statement["totals"].items():
        ws.cell(row=row, column=1, value=key.replace("_", " ").capitalize())
        _amount_cell(ws, row, 3, value)
        row += 1
    return row


def _drill_index(ws, row: int, index: list[tuple[str, dict]], rows: dict[str, tuple[int, str]]) -> None:
    if not index:
        return
    ws.cell(row=row, column=1, value="Ledger drill-down index (click the ledger to open the Ledgers sheet)").font = BOLD
    row += 1
    for label, d in index:
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=2, value=d["ledger_name"])
        hit = rows.get(str(d["ledger_id"])) if d.get("ledger_id") else None
        if hit is not None:
            _link(cell, hit[0])
        _amount_cell(ws, row, 3, d["amount"])
        row += 1


def _notes(ws, row: int, statement: dict) -> None:
    for note in statement.get("notes", []):
        ws.cell(row=row, column=1, value=f"Note {note['note_no']}: {note['title']}").font = BOLD
        row += 1
        for line in note["lines"]:
            ws.cell(row=row, column=1, value=line["label"]).alignment = Alignment(indent=2 * int(line.get("level", 0)))
            _amount_cell(ws, row, 3, line["amount"], bold=bool(line.get("is_total")))
            if line.get("previous_amount") is not None:
                _amount_cell(ws, row, 4, line["previous_amount"])
            row += 1
        row += 1


def _write_table(ws, start: int, section: dict, name_rows: dict[str, tuple[int, str]]) -> None:
    columns = section["columns"]
    for i, (_, label, _kind) in enumerate(columns, 1):
        cell = ws.cell(row=start, column=i, value=label)
        cell.font = BOLD
        cell.fill = GREY
        ws.column_dimensions[cell.column_letter].width = 36 if _kind in ("text", "ledger") else 16
    row = start + 1
    for record in section["rows"]:
        for i, (key, _, kind) in enumerate(columns, 1):
            value = record.get(key)
            if kind in ("amount", "rate"):
                cell = _amount_cell(ws, row, i, value)
                if kind == "rate" and cell.value is not None:
                    cell.number_format = "0.00##"
            else:
                cell = ws.cell(row=row, column=i, value=_text(value))
                if kind == "ledger" and value in name_rows:
                    _link(cell, name_rows[value][0])
        row += 1
    if section.get("totals"):
        ws.cell(row=row, column=1, value="Total").font = BOLD
        for i, (key, _, kind) in enumerate(columns, 1):
            if key in section["totals"] and kind == "amount":
                _amount_cell(ws, row, i, section["totals"][key], bold=True)
        row += 1
    for note in section.get("footnotes", []):
        row += 1
        ws.cell(row=row, column=1, value=note)


def _ledger_entries(doc: dict) -> list[dict]:
    keep = ("opening", "debit_total", "credit_total", "closing")
    return [p for p in doc.get("ledgers", []) if any((_dec(p[k]) or 0) != 0 for k in keep)]


def to_xlsx(doc: dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    entries = _ledger_entries(doc)
    rows = {str(p["ledger_id"]): (LEDGER_FIRST_ROW + i, f"L{i + 1:03d}") for i, p in enumerate(entries)}
    name_rows = {p["name"]: rows[str(p["ledger_id"])] for p in entries}
    used: set[str] = {"ledgers"}
    for section in doc["sections"]:
        ws = wb.create_sheet(_sheet_name(section["name"], used))
        start = _header_block(ws, doc, section)
        if section.get("statement") is not None:
            _write_statement(ws, start, section["statement"], rows)
        else:
            _write_table(ws, start, section, name_rows)
    ws = wb.create_sheet("Ledgers")
    ws.cell(row=1, column=1, value="Ledgers: totals behind the statement lines").font = Font(bold=True, size=14)
    ws.cell(row=2, column=1, value="Client").font = BOLD
    ws.cell(row=2, column=2, value=doc["client"])
    ws.cell(row=3, column=1, value="Financial year").font = BOLD
    ws.cell(row=3, column=2, value=doc["fy_label"])
    ws.cell(row=4, column=1, value="Closing vouchers of a closed year are not counted; Dr / Cr = debit / credit balance.")
    ws.cell(row=5, column=1, value="Engine version").font = BOLD
    ws.cell(row=5, column=2, value=doc["engine_version"])
    heads = ["Ref", "Ledger", "Group", "Opening", "Debit total", "Credit total", "Closing"]
    for i, h in enumerate(heads, 1):
        cell = ws.cell(row=LEDGER_FIRST_ROW - 1, column=i, value=h)
        cell.font = BOLD
        cell.fill = GREY
    for i, p in enumerate(entries):
        r = LEDGER_FIRST_ROW + i
        ws.cell(row=r, column=1, value=f"L{i + 1:03d}")
        ws.cell(row=r, column=2, value=p["name"])
        ws.cell(row=r, column=3, value=p["group_code"])
        ws.cell(row=r, column=4, value=_side_balance(p["opening"]))
        _amount_cell(ws, r, 5, p["debit_total"])
        _amount_cell(ws, r, 6, p["credit_total"])
        ws.cell(row=r, column=7, value=_side_balance(p["closing"]))
    for col, w in zip("ABCDEFG", (8, 40, 24, 22, 18, 18, 22), strict=True):
        ws.column_dimensions[col].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ============================================================================================ PDF


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=13, spaceAfter=4),
        "head": ParagraphStyle("h", parent=base, fontSize=8, leading=10),
        "warn": ParagraphStyle("w", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#9C5700")),
        "cell": ParagraphStyle("c", parent=base, fontSize=8, leading=10),
        "bold": ParagraphStyle("b", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10),
        "small": ParagraphStyle("s", parent=base, fontSize=6.5, leading=8, textColor=colors.HexColor("#555555")),
        "right": ParagraphStyle("r", parent=base, fontSize=8, leading=10, alignment=2),
        "rbold": ParagraphStyle("rb", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=2),
    }


def _esc(text: Any) -> str:
    return _text(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _label_para(line: dict, st: dict[str, ParagraphStyle], *, indent: bool = True) -> Paragraph:
    bold = bool(line.get("is_total")) or _is_heading(line)
    pad = "&nbsp;" * (4 * int(line.get("level", 0))) if indent else ""
    html = f"{pad}{_esc(line['label'])}"
    if not _drill_is_obvious(line):
        html += f"<br/>{pad}<font size='6.5' color='#555555'>({_esc(_drill_text(line))})</font>"
    return Paragraph(html, st["bold" if bold else "cell"])


def _amount_para(line: dict, st: dict[str, ParagraphStyle], key: str = "amount") -> Paragraph:
    if _is_heading(line):
        return Paragraph("", st["cell"])
    value = line.get(key)
    text = "-" if value is None else _inr(value)
    return Paragraph(text, st["rbold" if line.get("is_total") else "right"])


_GRID = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7E6E6")),
         ("VALIGN", (0, 0), (-1, -1), "TOP")]


def _statement_table(statement: dict, st: dict[str, ParagraphStyle]) -> list:
    head = lambda t: Paragraph(t, st["bold"])
    if _is_horizontal(statement):
        data = [[head("Particulars"), head("Amount"), head("Particulars"), head("Amount")]]
        for left, right in _pair_rows(statement):
            data.append([_label_para(left, st) if left else "", _amount_para(left, st) if left else "",
                         _label_para(right, st) if right else "", _amount_para(right, st) if right else ""])
        return [Table(data, colWidths=[250, 95, 250, 95], repeatRows=1, style=TableStyle(_GRID))]
    previous = _show_previous(statement)
    data = [[head("Particulars"), head("Note"), head("Amount"), *([head("Previous year")] if previous else [])]]
    for line in statement["left"]:
        row = [_label_para(line, st), Paragraph(_esc(line.get("note_no")), st["cell"]), _amount_para(line, st)]
        if previous:
            row.append(_amount_para(line, st, "previous_amount"))
        data.append(row)
    widths = [380, 40, 100, 100] if previous else [440, 40, 120]
    return [Table(data, colWidths=widths, repeatRows=1, style=TableStyle(_GRID))]


def _notes_flowables(statement: dict, st: dict[str, ParagraphStyle]) -> list:
    out: list = []
    for note in statement.get("notes", []):
        out.append(Spacer(1, 6))
        out.append(Paragraph(f"Note {note['note_no']}: {_esc(note['title'])}", st["bold"]))
        data = [[_label_para(x, st), _amount_para(x, st), _amount_para(x, st, "previous_amount")] for x in note["lines"]]
        if data:
            out.append(Table(data, colWidths=[400, 100, 100], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])))
    return out


def _table_flowables(section: dict, st: dict[str, ParagraphStyle]) -> list:
    columns = section["columns"]
    data = [[Paragraph(_esc(label), st["bold"]) for _, label, _ in columns]]
    for record in section["rows"]:
        data.append([Paragraph(_inr(record.get(k)) if kind == "amount" else _esc(record.get(k)), st["right" if kind == "amount" else "cell"])
                     for k, _, kind in columns])
    if section.get("totals"):
        data.append([Paragraph("Total" if i == 0 else (_inr(section["totals"][k]) if k in section["totals"] else ""), st["rbold"])
                     for i, (k, _, kind) in enumerate(columns)])
    width = 780 / max(len(columns), 1)
    out: list = [Table(data, colWidths=[width] * len(columns), repeatRows=1, style=TableStyle(_GRID))]
    out += [Paragraph(_esc(n), st["small"]) for n in section.get("footnotes", [])]
    return out


def to_pdf(doc: dict) -> bytes:
    st = _styles()
    story: list = []
    for i, section in enumerate(doc["sections"]):
        if i:
            story.append(PageBreak())
        story.append(Paragraph(_esc(section["title"]), st["title"]))
        for label, text in [("Client", doc["client"]), ("Financial year", doc["fy_label"]), *doc.get("header", []),
                            *section.get("header", []), ("Engine version", doc["engine_version"])]:
            story.append(Paragraph(f"<b>{_esc(label)}:</b> {_esc(text)}", st["head"]))
        for warning in section.get("warnings", []):
            story.append(Paragraph(_esc(warning), st["warn"]))
        story.append(Spacer(1, 6))
        if section.get("statement") is not None:
            story += _statement_table(section["statement"], st) + _notes_flowables(section["statement"], st)
        else:
            story += _table_flowables(section, st)
    out = io.BytesIO()
    footer = f"{doc['client']} | {doc['fy_label']} | engine {doc['engine_version']} | {doc.get('status_line', '')}"

    def _page(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 8 * mm, footer[:150])
        canvas.drawRightString(landscape(A4)[0] - 15 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                      title=doc["title"], author="LedgerMind AI").build(story, onFirstPage=_page, onLaterPages=_page)
    return out.getvalue()


def render(doc: dict, fmt: str) -> tuple[bytes, str]:
    return (to_xlsx(doc), XLSX) if fmt == "xlsx" else (to_pdf(doc), PDF)


def file_stem(doc: dict, what: str) -> str:
    return f"{_slug(doc['client'])}_{_slug(doc['fy_label'])}_{what}"
