"""Read vouchers from an Excel file (pure parsing: no database, no accounting rules).

Columns are exactly those of the test packs' vouchers.csv. Rows with the same ref_id form one voucher. Every
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
)
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
class ParsedLine:
    row: int
    ledger_name: str
    debit: str | Decimal | None  # as entered: text (commas stripped) or the cell's exact number
    credit: str | Decimal | None


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


# ================================================================================================= workbook


def _open(data: bytes):
    try:
        values = load_workbook(io.BytesIO(data), data_only=True)
        formulas = load_workbook(io.BytesIO(data), data_only=False)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as problem:
        raise ImportFileError("The upload is not a valid Excel (.xlsx) file.") from problem
    name = SHEET_NAME if SHEET_NAME in values.sheetnames else values.sheetnames[0]
    return values[name], formulas[name]


def _check_header(sheet) -> None:
    found = [_text(c.value).lower() for c in sheet[1]]
    while found and not found[-1]:
        found.pop()
    if found != list(COLUMNS):
        raise ImportFileError(
            f"The first row of the sheet must be exactly: {', '.join(COLUMNS)} (found: {', '.join(found)})."
        )


def parse_workbook(data: bytes) -> ParseResult:
    """Parse the file into vouchers in order of first appearance. Raises ImportFileError for file-level problems."""
    values, formulas = _open(data)
    _check_header(values)

    vouchers: dict[str, ParsedVoucher] = {}
    for row_cells in values.iter_rows(min_row=2, max_col=len(COLUMNS)):
        row = row_cells[0].row
        cells = [c.value for c in row_cells]
        if all(_text(v) == "" for v in cells):
            continue
        is_formula = [formulas.cell(row=row, column=i + 1).data_type == "f" for i in range(len(COLUMNS))]
        ref = _text(cells[0])
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

        ledger_name = _text(cells[3])
        if not ledger_name:
            voucher.errors.append(RowError(row, "ledger_name is empty"))
        debit = _amount(cells[4], is_formula[4], "debit", row, voucher.errors)
        credit = _amount(cells[5], is_formula[5], "credit", row, voucher.errors)
        voucher.lines.append(ParsedLine(row, ledger_name, debit, credit))

    if not vouchers:
        raise ImportFileError("The sheet has a header but no voucher rows.")
    return ParseResult(list(vouchers.values()))
