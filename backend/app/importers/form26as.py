"""Read a 26AS / AIS / TIS statement saved as CSV or Excel (T-40). Pure parsing: no database, no accounting.

NOT VALIDATED AGAINST A REAL TRACES / AIS FILE. The official layout was not available, so this parser reads ONE flat table
(first sheet of an .xlsx, or a UTF-8 CSV with a comma delimiter) whose header names are the ones below, and it is strict on
purpose: an unknown header, a missing required column, a malformed amount (more than 2 decimals), a bad date, TAN or PAN
rejects the WHOLE file with the row and the reason; nothing is guessed or skipped. When the owner supplies real files, the
tables _HEADERS / _REQUIRED below are the only places to adjust (the header text is compared without spaces, case or
punctuation).

Columns (canonical name: accepted header texts)
  deductor_tan      Deductor TAN | TAN of Deductor | TAN
  deductor_name     Name of Deductor | Deductor Name
  deductee_pan      Deductee PAN | PAN of Deductee | PAN
  section_ref       Section | Section Ref           (kept as printed, e.g. 194C or 393(1); mapped later, never guessed)
  transaction_date  Transaction Date | Date of Payment/Credit
  booking_date      Date of Booking | Booking Date  (optional)
  booking_status    Status of Booking | Booking Status (optional, as printed: F / U / P ...)
  amount_paid       Amount Paid/Credited | Amount Paid
  tax_deducted      Tax Deducted | Tax Deducted/Collected
  tax_deposited     Tax Deposited | Total Tax Deposited
Required: section_ref, transaction_date, amount_paid, tax_deducted, tax_deposited and at least one of deductor_tan /
deductee_pan (which one is needed depends on the side and is checked by the service). Amounts: plain or comma-grouped
(1,00,000.00); at most 2 decimals; negative rejected. Dates: dd-mm-yyyy, dd/mm/yyyy, yyyy-mm-dd, dd-Mon-yyyy.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.engine.money import MoneyError, parse_amount

TAN_FORMAT = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
PAN_FORMAT = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_GROUPED = re.compile(r"^\d{1,3}(,\d{2,3})+(\.\d+)?$")

_HEADERS = {
    "deductor_tan": ("deductortan", "tanofdeductor", "tan"),
    "deductor_name": ("nameofdeductor", "deductorname"),
    "deductee_pan": ("deducteepan", "panofdeductee", "pan"),
    "section_ref": ("section", "sectionref"),
    "transaction_date": ("transactiondate", "dateofpaymentcredit"),
    "booking_date": ("dateofbooking", "bookingdate"),
    "booking_status": ("statusofbooking", "bookingstatus"),
    "amount_paid": ("amountpaidcredited", "amountpaid"),
    "tax_deducted": ("taxdeducted", "taxdeductedcollected"),
    "tax_deposited": ("taxdeposited", "totaltaxdeposited"),
}
_REQUIRED = ("section_ref", "transaction_date", "amount_paid", "tax_deducted", "tax_deposited")
_LOOKUP = {text: key for key, texts in _HEADERS.items() for text in texts}


@dataclass(frozen=True)
class Problem:
    row: int  # row of the file counting the header as row 1; 0 = the file as a whole
    message: str


class Form26asFileError(ValueError):
    """The file is rejected as a whole (T-40). `problems` lists every reason found, each with its row."""

    def __init__(self, problems: list[Problem]):
        super().__init__("; ".join(f"row {p.row}: {p.message}" if p.row else p.message for p in problems))
        self.problems = problems


@dataclass(frozen=True)
class ParsedRow:
    row_no: int  # 1-based position among the data rows
    deductor_tan: str | None
    deductor_name: str | None
    deductee_pan: str | None
    section_ref: str
    transaction_date: date
    booking_date: date | None
    booking_status: str | None
    amount_paid: Decimal
    tax_deducted: Decimal
    tax_deposited: Decimal


@dataclass
class ParsedFile:
    source_format: str  # csv | excel
    rows: list[ParsedRow] = field(default_factory=list)


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower()) if value is not None else ""


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date(value: object, what: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip() if value is not None else ""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{what} {text!r} is not a date (expected dd-mm-yyyy)")


def _amount(value: object, what: str) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{what} is missing")
    if isinstance(value, float):  # Excel cells: shortest text, so 90.0 is 90 and never a binary float
        value = repr(value)
    if isinstance(value, str) and _GROUPED.match(value.strip()):
        value = value.strip().replace(",", "")
    try:
        return parse_amount(value)
    except MoneyError as e:
        raise ValueError(f"{what}: {e}") from None


def _row(row_no: int, cells: dict[str, object]) -> ParsedRow:
    tan, pan = _text(cells.get("deductor_tan")), _text(cells.get("deductee_pan"))
    tan, pan = (tan.upper() if tan else None), (pan.upper() if pan else None)
    if tan and not TAN_FORMAT.match(tan):
        raise ValueError(f"deductor TAN {tan!r} is not in the format AAAA99999A")
    if pan and not PAN_FORMAT.match(pan):
        raise ValueError(f"deductee PAN {pan!r} is not in the format AAAAA9999A")
    section = _text(cells.get("section_ref"))
    if section is None:
        raise ValueError("section is missing")
    booked = cells.get("booking_date")
    return ParsedRow(
        row_no=row_no, deductor_tan=tan, deductor_name=_text(cells.get("deductor_name")), deductee_pan=pan, section_ref=section,
        transaction_date=_date(cells.get("transaction_date"), "transaction date"),
        booking_date=None if booked in (None, "") else _date(booked, "booking date"),
        booking_status=_text(cells.get("booking_status")),
        amount_paid=_amount(cells.get("amount_paid"), "amount paid"), tax_deducted=_amount(cells.get("tax_deducted"), "tax deducted"),
        tax_deposited=_amount(cells.get("tax_deposited"), "tax deposited"),
    )


def _read_table(source_format: str, table: list[list[object]]) -> ParsedFile:
    table = [r for r in table if any(c not in (None, "") for c in r)]
    if not table:
        raise Form26asFileError([Problem(0, "The file is empty")])
    header = table[0]
    columns: dict[str, int] = {}
    problems: list[Problem] = []
    for col, cell in enumerate(header):
        if cell in (None, ""):
            continue
        key = _LOOKUP.get(_norm(cell))
        if key is None:
            problems.append(Problem(1, f"Unknown column {str(cell).strip()!r}: the file layout is not recognised"))
        elif key in columns:
            problems.append(Problem(1, f"Column {str(cell).strip()!r} appears twice"))
        else:
            columns[key] = col
    missing = [k for k in _REQUIRED if k not in columns]
    if missing:
        problems.append(Problem(1, f"Required column(s) not found: {', '.join(missing)}"))
    if "deductor_tan" not in columns and "deductee_pan" not in columns:
        problems.append(Problem(1, "Neither a deductor TAN nor a deductee PAN column was found"))
    if problems:
        raise Form26asFileError(problems)
    parsed = ParsedFile(source_format)
    known = len(header)
    for offset, row in enumerate(table[1:], start=2):
        if any(c not in (None, "") for c in row[known:]):
            problems.append(Problem(offset, "The row has more cells than the header has columns"))
            continue
        cells = {key: (row[col] if col < len(row) else None) for key, col in columns.items()}
        try:
            parsed.rows.append(_row(len(parsed.rows) + 1, cells))
        except ValueError as e:
            problems.append(Problem(offset, str(e)))
    if not problems and not parsed.rows:
        problems.append(Problem(0, "The file has a header but no data rows"))
    if problems:
        raise Form26asFileError(problems)
    return parsed


def parse_csv(content: bytes) -> ParsedFile:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Form26asFileError([Problem(0, "The CSV file is not UTF-8 text")]) from None
    return _read_table("csv", [list(r) for r in csv.reader(io.StringIO(text))])


def parse_excel(content: bytes) -> ParsedFile:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError):
        raise Form26asFileError([Problem(0, "The file is not a readable .xlsx workbook")]) from None
    if not workbook.sheetnames:
        raise Form26asFileError([Problem(0, "The workbook has no sheets")])
    return _read_table("excel", [list(r) for r in workbook[workbook.sheetnames[0]].iter_rows(values_only=True)])


def parse_26as(content: bytes) -> ParsedFile:
    """Excel (a zip, first sheet) or CSV; a PDF, text statement or anything else is rejected with a clear reason."""
    if content[:2] == b"PK":
        return parse_excel(content)
    if content[:4] == b"%PDF":
        raise Form26asFileError([Problem(0, "PDF statements cannot be read: save the statement as Excel or CSV")])
    return parse_csv(content)
