"""Excel and PDF export of the Phase 6 statements and workings (docs/PHASE6_API_CONTRACT.md, package E; rules F-70, F-71).

Consumes the statement dicts of `services/final_statements.py`, `final_sch3.py` and `final_cashflow.py`, the fixed asset register,
depreciation preview and income-tax working of `final_assets.py` and the adjustments list of `final_adjustments.py`. No amount is
computed or changed here. F-71: nothing is exported while a statement or working has an error finding. Every export carries the
client, the financial year, the basis, the engine version and the status of the law rules used (all `pending` until verified).
"""

from collections import Counter
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_final_statements as frepo
from app.engine.final_types import ENGINE_VERSION, EntityType
from app.services import (
    final_adjustments,
    final_assets,
    final_cashflow,
    final_sch3,
    final_statements,
)
from app.services.errors import ServiceError
from app.services.final_export_render import file_stem, render

ORDER = ("trading", "profit_loss", "appropriation", "balance_sheet", "cash_flow")
SHEET_NAMES = {"trading": "Trading", "profit_loss": "Profit and Loss", "appropriation": "Appropriation", "balance_sheet": "Balance Sheet",
               "cash_flow": "Cash Flow"}
FORMATS = ("xlsx", "pdf")
COMPANY_ONLY_OUT = ("trading", "appropriation")


def check_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise ServiceError("invalid_format", "The export format must be xlsx or pdf.")
    return fmt


def _rule_text(rows: list[dict]) -> str:
    if not rows:
        return "No law-table rule is used by this statement."
    counts = Counter(r.get("verification_status") or "unknown" for r in rows)
    parts = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    text = f"{len(rows)} rule row(s): {parts}"
    if counts.get("pending") or counts.get("unknown"):
        text += ". PENDING: the rule rows are not yet verified against an official source."
    return text


def _warnings(findings: list[dict]) -> list[str]:
    return [f"Warning {f['rule_id']}: {f['message']}" for f in findings if f["severity"] == "warning"]


def _errors(title: str, findings: list[dict]) -> list[dict]:
    return [{"statement": title, **f} for f in findings if f["severity"] == "error"]


def _block(errors: list[dict]) -> None:
    if errors:
        raise ServiceError(
            "export_blocked",
            "Nothing is exported while a statement has an error (F-71). " + " ".join(f"{e['statement']}: {e['message']}" for e in errors),
            {"findings": errors})


def _context(conn: Connection, client_id: Any, fy_id: Any):
    return final_statements._year(conn, client_id, fy_id), frepo.client_profile(conn, client_id)


def _document(conn: Connection, client_id: Any, fy_id: Any, title: str, header: list[tuple[str, str]], sections: list[dict],
              rules: list[dict]) -> dict:
    fy, profile = _context(conn, client_id, fy_id)
    pending = any(r.get("verification_status") != "verified" for r in rules)
    return {
        "title": title, "client": profile.name, "fy_label": f"{fy.start_date:%d-%m-%Y} to {fy.end_date:%d-%m-%Y}",
        "engine_version": ENGINE_VERSION, "header": [*header, ("Law rule status", _rule_text(rules))], "sections": sections,
        "ledgers": final_statements.ledger_positions_out(conn, client_id, fy_id),
        "status_line": "rules: " + (("pending" if pending else "verified") if rules else "none used"),
    }


# ============================================================================================ statements


def _fetch(conn: Connection, client_id: Any, fy_id: Any, key: str, company: bool, layout: str | None) -> dict:
    try:
        if company:
            if key in COMPANY_ONLY_OUT:
                raise ServiceError("invalid_statement", f"The {SHEET_NAMES[key]} is not a Schedule III statement: a company exports "
                                                        "the Balance Sheet, the Statement of Profit and Loss, the notes and the Cash Flow.")
            if key == "balance_sheet":
                return final_sch3.balance_sheet(conn, client_id, fy_id)
            if key == "profit_loss":
                return final_sch3.profit_loss(conn, client_id, fy_id)
            return final_cashflow.cash_flow(conn, client_id, fy_id)
        if key == "trading":
            return final_statements.trading(conn, client_id, fy_id)
        if key == "profit_loss":
            return final_statements.profit_loss(conn, client_id, fy_id, None, layout)
        if key == "balance_sheet":
            return final_statements.balance_sheet(conn, client_id, fy_id, None, layout)
        if key == "appropriation":
            return final_statements.appropriation(conn, client_id, fy_id)
        return final_cashflow.cash_flow(conn, client_id, fy_id)
    except final_sch3.UnclassifiedError as exc:
        return exc.statement
    except ServiceError as exc:
        if exc.code == "statement_blocked":
            return exc.details["statement"]
        raise


def parse_statements(value: str | None, company: bool, firm: bool) -> list[str]:
    if not value:
        return ["balance_sheet", "profit_loss", "cash_flow"] if company else (
            ["trading", "profit_loss", *(["appropriation"] if firm else []), "balance_sheet"])
    keys = [k.strip() for k in value.split(",") if k.strip()]
    unknown = [k for k in keys if k not in ORDER]
    if unknown or not keys:
        raise ServiceError("invalid_statement", f"Unknown statement(s): {', '.join(unknown) or '(none)'}. Choose from: {', '.join(ORDER)}.")
    return [k for k in ORDER if k in keys]


def statements_document(conn: Connection, client_id: Any, fy_id: Any, statements: str | None = None, layout: str | None = None) -> dict:
    _, profile = _context(conn, client_id, fy_id)
    company = profile.entity_type == EntityType.COMPANY.value
    firm = profile.entity_type in (EntityType.PARTNERSHIP.value, EntityType.LLP.value)
    keys = parse_statements(statements, company, firm)
    bodies = {k: _fetch(conn, client_id, fy_id, k, company, layout) for k in keys}
    _block([e for k in keys for e in _errors(bodies[k]["title"], bodies[k]["findings"])])
    sections, rules = [], []
    for k in keys:
        body = bodies[k]
        rules += body.get("rule_status", [])
        basis = body.get("basis", {})
        sections.append({
            "name": SHEET_NAMES[k], "title": body["title"], "statement": body, "warnings": _warnings(body["findings"]),
            "header": [("Basis", f"format {body['format']}; entity {basis.get('entity_type', profile.entity_type)}; closing stock "
                                 + f"{basis.get('closing_stock_method') or 'not applicable'}"),
                       ("Period", f"{body['from_date']} to {body['to_date']}"), ("Law rule status", _rule_text(body.get("rule_status", [])))]})
    return _document(conn, client_id, fy_id, "Final statements", [("Entity", profile.entity_type), ("Business", profile.business_type)],
                     sections, rules)


# ============================================================================================ workings (packages A, B)


def _table(name: str, title: str, columns: list[tuple[str, str, str]], rows: list[dict], *, totals: dict | None = None,
           header: list[tuple[str, str]] | None = None, warnings: list[str] | None = None, footnotes: list[str] | None = None) -> dict:
    return {"name": name, "title": title, "statement": None, "columns": columns, "rows": rows, "totals": totals,
            "header": header or [], "warnings": warnings or [], "footnotes": footnotes or []}


def register_document(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    data = final_assets.register(conn, client_id, fy_id)
    cols = [("asset_no", "Asset no", "text"), ("name", "Asset", "text"), ("ledger", "Ledger", "ledger"),
            ("opening_cost", "Opening cost", "amount"), ("additions", "Additions", "amount"), ("disposals", "Disposals", "amount"),
            ("closing_cost", "Closing cost", "amount"), ("opening_accumulated", "Opening accumulated depreciation", "amount"),
            ("depreciation_for_year", "Depreciation for the year", "amount"), ("disposal_accumulated", "Accumulated on disposals", "amount"),
            ("closing_accumulated", "Closing accumulated depreciation", "amount"), ("net_block", "Net block", "amount")]
    section = _table("Fixed Asset Register", "Fixed asset register", cols, data["rows"], totals=data["totals"],
                     header=[("Basis", "Book view computed from the asset events (opening, additions, disposals, depreciation of the year)")])
    return _document(conn, client_id, fy_id, "Fixed asset register", [], [section], [])


def depreciation_document(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    data = final_assets.preview_book(conn, client_id, fy_id)
    _block(_errors("Book depreciation run", data["findings"]))
    rules = [{"verification_status": r.get("verification_status")} for r in data["rule_status"]]
    for line in data["lines"]:
        line["rule_status_text"] = (line["rule_status"] or {}).get("verification_status")
    header = [("Basis", "Companies Act (Schedule II) book depreciation; the Journal is created as a draft through the voucher service")]
    cols = [("asset_no", "Asset no", "text"), ("name", "Asset", "text"), ("method", "Method", "text"), ("cost", "Cost", "amount"),
            ("opening_accumulated", "Opening accumulated", "amount"), ("wdv_rate_percent", "WDV rate %", "rate"),
            ("days_used", "Days used", "text"), ("days_in_year", "Days in year", "text"),
            ("depreciation", "Depreciation", "amount"), ("closing_accumulated", "Closing accumulated", "amount"),
            ("rule_status_text", "Class rule status", "text")]
    sections = [_table("Book Depreciation", "Book depreciation run", cols, data["lines"], totals={"depreciation": data["total"]},
                       header=header, warnings=_warnings(data["findings"]))]
    if data["journal_lines"]:
        sections.append(_table("Depreciation Journal", "Depreciation journal (draft)",
                               [("ledger_name", "Ledger", "ledger"), ("debit", "Debit", "amount"), ("credit", "Credit", "amount")],
                               data["journal_lines"], header=header))
    if data["disposal_workings"]:
        sections.append(_table("Disposals", "Disposal workings",
                               [("asset_no", "Asset no", "text"), ("disposal_date", "Date", "text"), ("proceeds", "Proceeds", "amount"),
                                ("book_value", "Book value", "amount"), ("profit_or_loss", "Profit / (loss)", "amount")],
                               data["disposal_workings"], header=header))
    return _document(conn, client_id, fy_id, "Book depreciation run", [], sections, rules)


def it_document(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    data = final_assets.it_working(conn, client_id, fy_id)
    _block(_errors("Income-tax depreciation working", data["findings"]))
    for block in data["blocks"]:
        block["flags_text"] = ", ".join(block["flags"])
    cols = [("block_key", "Block", "text"), ("description", "Description", "text"), ("rate", "Rate %", "rate"),
            ("opening_wdv", "Opening WDV", "amount"), ("additions_full", "Additions (full rate)", "amount"),
            ("additions_half", "Additions (half rate)", "amount"), ("disposals", "Disposals", "amount"),
            ("depreciation", "Depreciation", "amount"), ("closing_wdv", "Closing WDV", "amount"), ("flags_text", "Flags (for the CA)", "text")]
    header = [("Basis", f"Income-tax block working, status {data['status']}; a working only: no voucher, no ledger effect (F-34)")]
    section = _table("IT Depreciation", "Income-tax depreciation working", cols, data["blocks"],
                     totals={"depreciation": data["total_depreciation"]}, header=header, warnings=_warnings(data["findings"]),
                     footnotes=["Flagged blocks (negative block, terminal depreciation) are not computed; they are for the CA to decide."])
    return _document(conn, client_id, fy_id, "Income-tax depreciation working", [], [section], data["rule_status"])


def adjustments_document(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    rows = final_adjustments.list_adjustments(conn, client_id, fy_id)
    for r in rows:
        r["type_text"] = r["adj_type"].replace("_", " ")
    cols = [("as_on_date", "As on", "text"), ("type_text", "Adjustment", "text"), ("amount", "Amount", "amount"),
            ("voucher_number", "Voucher no", "text"), ("voucher_status", "Voucher status", "text"), ("basis_note", "Basis", "text")]
    section = _table("Adjustments", "Period-end adjustments", cols, rows, totals={"amount": sum((r["amount"] for r in rows), 0)},
                     header=[("Basis", "Every adjustment is a Journal voucher created through the voucher service")])
    return _document(conn, client_id, fy_id, "Period-end adjustments", [], [section], [])


# ============================================================================================ entry points

WORKINGS = {"register": register_document, "depreciation": depreciation_document, "it-working": it_document,
            "adjustments": adjustments_document}


def export_statements(conn: Connection, client_id: Any, fy_id: Any, fmt: str, statements: str | None = None, layout: str | None = None
                      ) -> tuple[bytes, str, str]:
    """(bytes, media type, file name)."""
    check_format(fmt)
    if layout not in (None, "vertical", "horizontal"):
        raise ServiceError("invalid_layout", "The layout must be vertical or horizontal.")
    doc = statements_document(conn, client_id, fy_id, statements, layout)
    content, media = render(doc, fmt)
    return content, media, f"{file_stem(doc, 'statements')}.{fmt}"


def export_working(conn: Connection, client_id: Any, fy_id: Any, kind: str, fmt: str) -> tuple[bytes, str, str]:
    check_format(fmt)
    if kind not in WORKINGS:
        raise ServiceError("invalid_export", f"Unknown export '{kind}'. Choose from: {', '.join(WORKINGS)}.")
    doc = WORKINGS[kind](conn, client_id, fy_id)
    content, media = render(doc, fmt)
    return content, media, f"{file_stem(doc, kind)}.{fmt}"
