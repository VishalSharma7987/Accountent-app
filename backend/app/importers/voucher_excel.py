"""Read vouchers from an Excel file (pure parsing: no database, no accounting rules).

Columns are those of the test packs' vouchers.csv plus the bill allocation columns (bill_type, bill_ref,
bill_amount, due_date). Rows with the same ref_id form one voucher. A line of a bill-wise party may be split into
several allocations: the first allocation goes on the line's own row, each further one on a CONTINUATION row (same
ref_id, ledger_name/debit/credit empty, only the bill columns filled). Every
problem carries the Excel row number. Amounts are NOT judged here beyond what Excel cells can hide (formulas
without a saved result, TRUE/FALSE): text and numbers are handed on as entered (numbers as their exact Decimal)
and the rule engine rejects bad amounts under V-03 with the line's row number.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

COLUMNS = (
    "ref_id", "date", "voucher_type", "ledger_name", "debit", "credit", "narration", "reference_no", "party_ledger",
    "bill_type", "bill_ref", "bill_amount", "due_date",
)
LEGACY_COLUMNS = COLUMNS[:9]  # files made before bill allocations existed are still accepted
# Phase 3 invoice mode: optional extra columns after the 13 above (any order, any subset). Rows of one ref_id are the
# item lines of one invoice; the ledger / tax lines are built by the GST engine, so the debit / credit cells stay empty.
GST_COLUMNS = (
    "gst_registration", "document_kind", "supply_category", "place_of_supply", "counterparty_gstin",
    "original_invoice_no", "original_invoice_date", "note_reason",
    "item_description", "hsn_sac", "uqc", "quantity", "unit_rate", "discount", "item_ledger", "itc_category", "rcm_category",
)
TAX_COLUMNS = ("cgst", "sgst", "igst", "cess", "gst_rate", "tax_amount", "taxable_value")  # refused when filled (G-14)
ITEM_COLUMNS = ("item_description", "hsn_sac", "quantity", "unit_rate", "item_ledger")
INVOICE_HEAD = (
    "gst_registration", "document_kind", "supply_category", "place_of_supply", "counterparty_gstin",
    "original_invoice_no", "original_invoice_date", "note_reason",
)
BILL_KINDS = {"newref": "new_ref", "againstref": "against_ref", "advance": "advance", "onaccount": "on_account"}
BILL_TYPE_PROBLEM = "bill_type must be one of New Ref, Against Ref, Advance, On Account"
VOUCHER_TYPES = (
    "contra", "payment", "receipt", "sales", "purchase", "credit_note", "debit_note", "journal",
)
SHEET_NAME = "Vouchers"
DATE_PROBLEM = "date must be a real date, as an Excel date or text like 2026-04-05 or 05-04-2026"
_HEAD_FIELDS = ("date", "voucher_type", "narration", "reference_no", "party_ledger")
_TEXT_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$|^(\d{1,2})-(\d{1,2})-(\d{4})$")
_COMMA_NUMBER = re.compile(r"^-?[\d,]+(\.\d+)?$")


class ImportFileError(ValueError):
    """The file as a whole cannot be read (not an .xlsx, wrong header, no rows)."""


@dataclass(frozen=True)
class RowError:
    row: int  # Excel row number
    message: str


@dataclass(frozen=True)
class ParsedAllocation:
    row: int
    kind: str  # new_ref | against_ref | advance | on_account
    bill_ref: str | None
    amount: str | Decimal | None  # as entered, like debit/credit
    due_date: date | None


@dataclass
class ParsedLine:
    row: int
    ledger_name: str
    debit: str | Decimal | None  # as entered: text (commas stripped) or the cell's exact number
    credit: str | Decimal | None
    allocations: list[ParsedAllocation] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedItem:
    """One item line of an invoice-mode voucher. Numbers as entered (text with commas stripped, or the exact number)."""

    row: int
    description: str
    hsn_sac: str
    uqc: str | None
    quantity: str | Decimal | None
    unit_rate: str | Decimal | None
    discount: str | Decimal | None
    item_ledger: str
    itc_category: str | None
    rcm_category: str | None


@dataclass(frozen=True)
class ParsedGst:
    """The invoice header of an invoice-mode voucher (from the first item row; later rows may repeat it)."""

    registration: str
    document_kind: str
    supply_category: str
    place_of_supply: str
    counterparty_gstin: str | None
    original_invoice_no: str | None
    original_invoice_date: date | None
    note_reason: str | None


@dataclass
class ParsedVoucher:
    ref_id: str
    first_row: int
    voucher_type: str = ""
    voucher_date: date | None = None
    narration: str = ""
    reference_no: str = ""
    party_ledger: str = ""
    lines: list[ParsedLine] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    gst: ParsedGst | None = None  # Phase 3: set when the rows are item lines
    items: list[ParsedItem] = field(default_factory=list)


@dataclass(frozen=True)
class ParseResult:
    vouchers: list[ParsedVoucher]


# ================================================================================================== cells


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        match = _TEXT_DATE.match(value.strip())
        if match:
            groups = match.groups()
            year, month, day = (groups[0], groups[1], groups[2]) if groups[0] else (groups[5], groups[4], groups[3])
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                return None
    return None


def _normalise_type(value: object) -> str:
    return _text(value).lower().replace(" ", "_")


def _amount(value: object, formula: bool, column: str, row: int, errors: list[RowError]) -> str | Decimal | None:
    """One amount cell as entered. Returns None for an empty cell or a problem (the problem is recorded)."""
    if formula and value is None:
        errors.append(RowError(
            row, f"{column} holds a formula with no saved result; open the file in Excel, save it, and upload it again"
        ))
        return None
    if value is None:
        return None
    if isinstance(value, bool):
        errors.append(RowError(row, f"{column} is a TRUE/FALSE value, not an amount"))
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))  # the exact number Excel saved, e.g. 0.30000000000000004
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    return text.replace(",", "") if _COMMA_NUMBER.match(text) else text


def _bill_kind(value: object) -> str | None:
    return BILL_KINDS.get(re.sub(r"[\s_]+", "", _text(value).lower()))


def _allocation(cells: list, formulas: list[bool], row: int, errors: list[RowError]) -> ParsedAllocation | None:
    """The allocation of one row (cells = bill_type, bill_ref, bill_amount, due_date), None when all four are empty."""
    if all(_text(v) == "" for v in cells):
        return None
    kind = _bill_kind(cells[0])
    if kind is None:
        found = _text(cells[0])
        errors.append(RowError(row, BILL_TYPE_PROBLEM + (f" (found: {found!r})" if found else " (bill_type is empty)")))
    before = len(errors)
    amount = _amount(cells[2], formulas[2], "bill_amount", row, errors)
    if amount is None and len(errors) == before:
        errors.append(RowError(row, "bill_amount is empty"))
    due = None
    if _text(cells[3]):
        due = _parse_date(cells[3])
        if due is None:
            errors.append(RowError(row, "due_date must be a real date, as an Excel date or text like 2026-04-05 or 05-04-2026"))
    if kind is None:
        return None
    return ParsedAllocation(row, kind, _text(cells[1]) or None, amount, due)


# ================================================================================================= invoice rows


def _item_row(voucher: ParsedVoucher, row: int, cells: list, extra: dict, extra_index: dict, is_formula: list[bool]) -> None:
    """An item line of an invoice-mode voucher: the header fields come from the first item row (later rows may repeat
    them but not change them); debit / credit / ledger_name must be empty; tax columns are refused (G-14)."""
    errors = voucher.errors
    if voucher.lines:
        errors.append(RowError(row, "an invoice (item rows) cannot mix with ledger rows in one voucher"))
    if any(_text(cells[i]) for i in (3, 4, 5)):
        errors.append(RowError(row, "an item row carries no ledger_name, debit or credit: the system builds the ledger lines (G-14)"))
    for name in TAX_COLUMNS:
        if _text(extra.get(name)):
            errors.append(RowError(row, f"{name}: tax amounts are not accepted (G-14); the system calculates the tax"))

    def number(name: str):
        return _amount(extra.get(name), is_formula[extra_index[name]], name, row, errors) if name in extra else None

    head = {name: _text(extra.get(name)) for name in INVOICE_HEAD if name != "original_invoice_date"}
    original_date = None
    if _text(extra.get("original_invoice_date")):
        original_date = _parse_date(extra["original_invoice_date"])
        if original_date is None:
            errors.append(RowError(row, "original_invoice_date must be a real date"))
    if voucher.gst is None:
        for name in ("gst_registration", "document_kind", "supply_category", "place_of_supply"):
            if not head[name]:
                errors.append(RowError(row, f"{name} is required on the first item row of an invoice"))
        voucher.gst = ParsedGst(
            head["gst_registration"].upper(), head["document_kind"].lower(), head["supply_category"].lower(),
            head["place_of_supply"], head["counterparty_gstin"].upper() or None, head["original_invoice_no"] or None,
            original_date, head["note_reason"].lower() or None,
        )
    else:
        first = voucher.gst
        known = {
            "gst_registration": first.registration, "document_kind": first.document_kind,
            "supply_category": first.supply_category, "place_of_supply": first.place_of_supply,
            "counterparty_gstin": first.counterparty_gstin or "", "original_invoice_no": first.original_invoice_no or "",
            "note_reason": first.note_reason or "",
        }
        for name, value in known.items():
            if head[name] and head[name].lower() != value.lower():
                errors.append(RowError(row, f"{name} differs from the invoice's first item row (row {voucher.first_row})"))
    voucher.items.append(ParsedItem(
        row, _text(extra.get("item_description")), _text(extra.get("hsn_sac")), _text(extra.get("uqc")).upper() or None,
        number("quantity"), number("unit_rate"), number("discount"), _text(extra.get("item_ledger")),
        _text(extra.get("itc_category")) or None, _text(extra.get("rcm_category")) or None,
    ))


# ================================================================================================= workbook


def _open(data: bytes):
    try:
        values = load_workbook(io.BytesIO(data), data_only=True)
        formulas = load_workbook(io.BytesIO(data), data_only=False)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as problem:
        raise ImportFileError("The upload is not a valid Excel (.xlsx) file.") from problem
    name = SHEET_NAME if SHEET_NAME in values.sheetnames else values.sheetnames[0]
    return values[name], formulas[name]


def _check_header(sheet) -> dict[str, int]:
    """The header must be the 13 columns (or the 9 legacy ones), optionally followed by invoice-mode columns.
    Returns name -> 0-based column of the extra columns."""
    found = [_text(c.value).lower() for c in sheet[1]]
    while found and not found[-1]:
        found.pop()
    extra = found[len(COLUMNS):]
    extras_ok = len(set(extra)) == len(extra) and all(name in GST_COLUMNS + TAX_COLUMNS for name in extra)
    if found not in (list(COLUMNS), list(LEGACY_COLUMNS)) and not (found[:len(COLUMNS)] == list(COLUMNS) and extras_ok):
        raise ImportFileError(
            f"The first row of the sheet must be exactly: {', '.join(COLUMNS)} (found: {', '.join(found)})."
        )
    return {name: len(COLUMNS) + i for i, name in enumerate(extra)}


def parse_workbook(data: bytes) -> ParseResult:
    """Parse the file into vouchers in order of first appearance. Raises ImportFileError for file-level problems."""
    values, formulas = _open(data)
    extra_index = _check_header(values)
    width = len(COLUMNS) + len(extra_index)

    vouchers: dict[str, ParsedVoucher] = {}
    for row_cells in values.iter_rows(min_row=2, max_col=width):
        row = row_cells[0].row
        cells = [c.value for c in row_cells]
        cells += [None] * (width - len(cells))
        if all(_text(v) == "" for v in cells):
            continue
        is_formula = [formulas.cell(row=row, column=i + 1).data_type == "f" for i in range(width)]
        extra = {name: cells[i] for name, i in extra_index.items()}
        ref = _text(cells[0])
        bill_cells = cells[9:13]
        continuation = (
            ref in vouchers and vouchers[ref].lines and _text(cells[3]) == "" and _text(cells[4]) == ""
            and _text(cells[5]) == "" and any(_text(v) for v in bill_cells)
        )
        if continuation:  # a further allocation of the previous line of this voucher
            voucher = vouchers[ref]
            allocation = _allocation(bill_cells, is_formula[9:13], row, voucher.errors)
            if allocation is not None:
                voucher.lines[-1].allocations.append(allocation)
            continue
        errors: list[RowError] = []
        if not ref:
            ref = f"(row {row})"
            errors.append(RowError(row, "ref_id is empty: rows of one voucher share a ref_id"))
        voucher = vouchers.setdefault(ref, ParsedVoucher(ref_id=ref, first_row=row))
        voucher.errors.extend(errors)

        row_date = _parse_date(cells[1])
        row_type = _normalise_type(cells[2])
        if row_date is None:
            voucher.errors.append(RowError(row, DATE_PROBLEM))
        if row_type not in VOUCHER_TYPES and (row == voucher.first_row or row_type != voucher.voucher_type):
            voucher.errors.append(RowError(
                row, f"voucher_type must be one of {', '.join(VOUCHER_TYPES)} (found: {_text(cells[2])!r})"
            ))
        head = {
            "date": row_date, "voucher_type": row_type, "narration": _text(cells[6]),
            "reference_no": _text(cells[7]), "party_ledger": _text(cells[8]),
        }
        if len(voucher.lines) == 0 and voucher.first_row == row:
            voucher.voucher_date, voucher.voucher_type = row_date, row_type
            voucher.narration, voucher.reference_no, voucher.party_ledger = (
                head["narration"], head["reference_no"], head["party_ledger"])
        else:
            first = {"date": voucher.voucher_date, "voucher_type": voucher.voucher_type, "narration": voucher.narration,
                     "reference_no": voucher.reference_no, "party_ledger": voucher.party_ledger}
            for name in _HEAD_FIELDS:
                comparable = not (name == "date" and (row_date is None or voucher.voucher_date is None))
                if comparable and head[name] != first[name]:
                    voucher.errors.append(RowError(row, f"{name} differs from the voucher's first row (row {voucher.first_row})"))

        if any(_text(extra.get(name)) for name in ITEM_COLUMNS):  # Phase 3: an item line of an invoice
            _item_row(voucher, row, cells, extra, extra_index, is_formula)
            continue
        if voucher.items:
            voucher.errors.append(RowError(row, "an invoice (item rows) cannot mix with ledger rows in one voucher"))
        for name in TAX_COLUMNS:
            if _text(extra.get(name)):
                voucher.errors.append(RowError(row, f"{name}: tax amounts are not accepted (G-14); the system calculates the tax"))
        ledger_name = _text(cells[3])
        if not ledger_name:
            voucher.errors.append(RowError(row, "ledger_name is empty"))
        debit = _amount(cells[4], is_formula[4], "debit", row, voucher.errors)
        credit = _amount(cells[5], is_formula[5], "credit", row, voucher.errors)
        line = ParsedLine(row, ledger_name, debit, credit)
        allocation = _allocation(bill_cells, is_formula[9:13], row, voucher.errors)
        if allocation is not None:
            line.allocations.append(allocation)
        voucher.lines.append(line)

    if not vouchers:
        raise ImportFileError("The sheet has a header but no voucher rows.")
    return ParseResult(list(vouchers.values()))
