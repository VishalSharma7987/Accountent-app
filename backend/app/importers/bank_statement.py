"""Read a bank statement (.xlsx or .csv) with a saved column Mapping. Pure parsing: no database, no accounting.

Bank wording is kept: `debit` = money going OUT of the bank (withdrawal), `credit` = money coming IN (deposit).
Every problem carries the row number of the file (row 0 = the file as a whole). Nothing is skipped silently:
only rows without a date (blank lines, totals, footers) are skipped; a row with a date must give a clean amount.
Rule R-01: opening + credits - debits = closing, and every printed running balance must agree.
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

from app.engine.money import MoneyError, format_inr, parse_amount

ZERO = Decimal("0.00")
MAPPING_KEYS = {
    "header_row", "date_col", "date_format", "description_col", "reference_col", "debit_col", "credit_col",
    "amount_col", "drcr_col", "balance_col", "opening_balance_cell", "opening_balance",
}
_COMMA_NUMBER = re.compile(r"^-?[\d,]+(\.\d+)?$")
_CELL_REF = re.compile(r"^([A-Za-z]{1,3})([1-9]\d*)$")
_FOOTER_WORDS = re.compile(r"total|closing|opening|balance|b/f|c/f|brought|carried|summary", re.IGNORECASE)
_DEBIT_WORDS = {"DR", "D", "DEBIT", "-"}
_CREDIT_WORDS = {"CR", "C", "CREDIT", "+"}


class MappingError(ValueError):
    """A saved mapping that is not well formed."""


@dataclass(frozen=True)
class RowProblem:
    row: int  # row of the file; 0 = the file as a whole
    message: str


@dataclass(frozen=True)
class StatementLine:
    row: int
    txn_date: date
    description: str
    reference: str | None
    debit: Decimal  # withdrawal
    credit: Decimal  # deposit
    balance: Decimal | None


@dataclass
class ParsedStatement:
    lines: list[StatementLine] = field(default_factory=list)
    period_from: date | None = None
    period_to: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    problems: list[RowProblem] = field(default_factory=list)


# ================================================================================================== amounts


def parse_balance_text(value: object) -> Decimal:
    """A balance as entered: like parse_amount but a leading minus is allowed (overdrawn account). Raises MoneyError."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            return -parse_amount(text[1:].strip().replace(",", ""))
    return parse_amount(value)


def _cell_to_amount_input(value: object) -> object:
    """Cell value -> something parse_amount takes: floats become their exact shortest text (1234.5 -> '1234.5')."""
    if isinstance(value, bool):
        raise MoneyError("invalid", f"{value!r} is not a valid amount")
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        return text.replace(",", "") if _COMMA_NUMBER.match(text) else text
    return value


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _amount_cell(value: object) -> Decimal:
    if _blank(value):
        return ZERO
    return parse_amount(_cell_to_amount_input(value))


def _balance_cell(value: object) -> Decimal:
    return parse_balance_text(_cell_to_amount_input(value))


# ================================================================================================== mapping


def validate_mapping(mapping: object) -> dict:
    """The mapping as a clean dict, or MappingError saying what is wrong."""
    if not isinstance(mapping, dict):
        raise MappingError("The mapping must be an object.")
    unknown = sorted(set(mapping) - MAPPING_KEYS)
    if unknown:
        raise MappingError(f"Unknown mapping field(s): {', '.join(unknown)}.")
    clean: dict = {}
    header_row = mapping.get("header_row")
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        raise MappingError("header_row must be a whole number, 1 or more (the row holding the column names).")
    clean["header_row"] = header_row
    for key in ("date_col", "description_col", "date_format"):
        if not isinstance(mapping.get(key), str) or not mapping[key].strip():
            raise MappingError(f"{key} is required.")
        clean[key] = mapping[key].strip() if key != "date_format" else mapping[key]
    probe = date(2026, 4, 5)
    try:
        ok = datetime.strptime(probe.strftime(clean["date_format"]), clean["date_format"]).date() == probe
    except ValueError:
        ok = False
    if not ok or "%" not in clean["date_format"]:
        raise MappingError(f"date_format '{clean['date_format']}' is not a usable date format such as %d/%m/%Y.")
    for key in ("reference_col", "debit_col", "credit_col", "amount_col", "drcr_col", "balance_col"):
        value = mapping.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not value.strip():
            raise MappingError(f"{key} must be a column name.")
        clean[key] = value.strip()
    split = "debit_col" in clean or "credit_col" in clean
    single = "amount_col" in clean or "drcr_col" in clean
    if split and single:
        raise MappingError("Use either debit_col + credit_col or amount_col + drcr_col, not both.")
    if split and not ("debit_col" in clean and "credit_col" in clean):
        raise MappingError("Both debit_col and credit_col are required.")
    if single and not ("amount_col" in clean and "drcr_col" in clean):
        raise MappingError("Both amount_col and drcr_col are required.")
    if not split and not single:
        raise MappingError("Give debit_col + credit_col, or amount_col + drcr_col.")
    cell, fixed = mapping.get("opening_balance_cell"), mapping.get("opening_balance")
    if cell not in (None, "") and fixed not in (None, ""):
        raise MappingError("Give opening_balance_cell or opening_balance, not both.")
    if cell not in (None, ""):
        if not isinstance(cell, str) or not _CELL_REF.match(cell.strip()):
            raise MappingError(f"opening_balance_cell '{cell}' must be a cell such as B3.")
        clean["opening_balance_cell"] = cell.strip().upper()
    if fixed not in (None, ""):
        try:
            clean["opening_balance"] = str(parse_balance_text(str(fixed) if not isinstance(fixed, str) else fixed))
        except MoneyError as problem:
            raise MappingError(f"opening_balance: {problem}") from None
    return clean


# ================================================================================================== reading


def _column_letters_to_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read_grid(content: bytes) -> list[list[object]]:
    """All rows of the file as lists of cell values (xlsx: first sheet, saved values; csv: text)."""
    if content[:2] == b"PK":
        try:
            wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
            ws = wb[wb.sheetnames[0]]
            return [list(row) for row in ws.iter_rows(values_only=True)]
        except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError, IndexError) as problem:
            raise ValueError("The upload is not a valid Excel (.xlsx) file.") from problem
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The file is neither an .xlsx nor a UTF-8 text (.csv) file.") from None
    sample = "\n".join(text.splitlines()[:10])
    delimiter = max(",;\t", key=sample.count) if any(d in sample for d in ",;\t") else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _cell(grid: list[list[object]], row: int, col: int) -> object:
    if row < 1 or row > len(grid):
        return None
    cells = grid[row - 1]
    return cells[col] if col < len(cells) else None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm(name: object) -> str:
    return " ".join(_text(name).split()).casefold()


def _parse_date(value: object, fmt: str) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(_text(value), fmt).date()
    except ValueError:
        return None


# ================================================================================================== parsing


def parse_statement(
    content: bytes, mapping: dict, opening_balance: object = None, closing_balance: object = None
) -> ParsedStatement:
    """Parse the file with a (validated) mapping. `opening_balance` / `closing_balance` arguments, when given, win
    over the mapping's opening value. Problems (including R-01 failures) are returned in `problems`."""
    result = ParsedStatement()
    problems = result.problems
    mapping = validate_mapping(mapping)
    try:
        grid = _read_grid(content)
    except ValueError as problem:
        problems.append(RowProblem(0, str(problem)))
        return result

    header_row = mapping["header_row"]
    names = {_norm(v): i for i, v in enumerate(grid[header_row - 1])} if header_row <= len(grid) else {}
    columns: dict[str, int] = {}
    for key in ("date_col", "description_col", "reference_col", "debit_col", "credit_col", "amount_col",
                "drcr_col", "balance_col"):
        if key not in mapping:
            continue
        index = names.get(_norm(mapping[key]))
        if index is None:
            problems.append(RowProblem(header_row, f"Row {header_row}: column '{mapping[key]}' was not found in the header row"))
        else:
            columns[key] = index
    if problems:
        return result

    opening = _opening(grid, mapping, opening_balance, problems)
    closing_arg = _balance_argument(closing_balance, "closing balance", problems)

    fmt = mapping["date_format"]
    has_balance = "balance_col" in columns
    for row_no in range(header_row + 1, len(grid) + 1):
        cells = grid[row_no - 1]
        get = lambda key, cells=cells: cells[columns[key]] if key in columns and columns[key] < len(cells) else None
        if all(_blank(c) for c in cells) or _blank(get("date_col")):
            continue
        raw_date = get("date_col")
        txn_date = _parse_date(raw_date, fmt)
        if txn_date is None:
            if _is_footer(raw_date, columns, get):
                continue
            problems.append(RowProblem(row_no, f"Row {row_no}: date '{_text(raw_date)}' does not match the format {fmt}"))
            continue
        row_problem_count = len(problems)
        debit, credit = _sides(row_no, columns, get, problems)
        balance = None
        if has_balance:
            try:
                if _blank(get("balance_col")):
                    problems.append(RowProblem(row_no, f"Row {row_no}: the running balance is blank"))
                else:
                    balance = _balance_cell(get("balance_col"))
            except MoneyError as problem:
                problems.append(RowProblem(row_no, f"Row {row_no}: balance: {problem}"))
        if len(problems) > row_problem_count:
            continue
        reference = _text(get("reference_col")) or None
        result.lines.append(StatementLine(row_no, txn_date, _text(get("description_col")), reference, debit, credit, balance))

    if problems:
        return result
    if not result.lines:
        problems.append(RowProblem(0, "The file has no transactions below the header row"))
        return result
    result.period_from = min(x.txn_date for x in result.lines)
    result.period_to = max(x.txn_date for x in result.lines)
    result.opening_balance = opening
    _integrity(result, opening, closing_arg, has_balance)
    return result


def _is_footer(raw_date: object, columns: dict[str, int], get) -> bool:
    """A non-date text in the date column: a totals/footer row (skipped), unless it carries amounts."""
    text = _text(raw_date)
    if _FOOTER_WORDS.search(text):
        return True
    amount_keys = [k for k in ("debit_col", "credit_col", "amount_col", "balance_col") if k in columns]
    return all(_blank(get(k)) for k in amount_keys)


def _sides(row_no: int, columns: dict[str, int], get, problems: list[RowProblem]) -> tuple[Decimal, Decimal]:
    try:
        if "debit_col" in columns:
            debit, credit = _amount_cell(get("debit_col")), _amount_cell(get("credit_col"))
        else:
            amount = _amount_cell(get("amount_col"))
            word = _text(get("drcr_col")).upper()
            if _blank(get("amount_col")) or amount == 0:
                debit = credit = ZERO
            elif word in _DEBIT_WORDS:
                debit, credit = amount, ZERO
            elif word in _CREDIT_WORDS:
                debit, credit = ZERO, amount
            else:
                problems.append(RowProblem(
                    row_no, f"Row {row_no}: the Dr/Cr column says '{_text(get('drcr_col'))}'; expected Dr, Cr, D, C, + or -"
                ))
                return ZERO, ZERO
    except MoneyError as problem:
        problems.append(RowProblem(row_no, f"Row {row_no}: {problem}"))
        return ZERO, ZERO
    if debit > 0 and credit > 0:
        problems.append(RowProblem(
            row_no,
            f"Row {row_no}: both a debit ({format_inr(debit)}) and a credit ({format_inr(credit)}) are filled; "
            "a row has only one side",
        ))
    elif debit == 0 and credit == 0:
        problems.append(RowProblem(row_no, f"Row {row_no}: the row has a date but no debit or credit amount"))
    return debit, credit


def _balance_argument(value: object, what: str, problems: list[RowProblem]) -> Decimal | None:
    if _blank(value):
        return None
    try:
        return parse_balance_text(value)
    except MoneyError as problem:
        problems.append(RowProblem(0, f"The {what} given is not valid: {problem}"))
        return None


def _opening(grid, mapping: dict, argument: object, problems: list[RowProblem]) -> Decimal | None:
    given = _balance_argument(argument, "opening balance", problems)
    if given is not None:
        return given
    if "opening_balance" in mapping:
        return Decimal(mapping["opening_balance"])
    ref = mapping.get("opening_balance_cell")
    if ref:
        match = _CELL_REF.match(ref)
        value = _cell(grid, int(match.group(2)), _column_letters_to_index(match.group(1)))
        if _blank(value):
            problems.append(RowProblem(0, f"The opening balance cell {ref} is empty"))
            return None
        try:
            return _balance_cell(value)
        except MoneyError as problem:
            problems.append(RowProblem(0, f"The opening balance cell {ref}: {problem}"))
            return None
    return None


def _integrity(result: ParsedStatement, opening: Decimal | None, closing_arg: Decimal | None, has_balance: bool) -> None:
    problems = result.problems
    if opening is None:
        problems.append(RowProblem(
            0, "The opening balance is not in the file or the saved format: enter the opening balance as per the statement"
        ))
        return
    running = opening
    for line in result.lines:
        expected = running + line.credit - line.debit
        if has_balance:
            if line.balance != expected:
                problems.append(RowProblem(
                    line.row,
                    f"Row {line.row}: running balance {format_inr(line.balance)} does not agree with the previous "
                    f"balance {format_inr(running)} + credit {format_inr(line.credit)} - debit {format_inr(line.debit)}"
                    f" = {format_inr(expected)}",
                ))
                return
            running = line.balance
        else:
            running = expected
    if has_balance:
        closing = result.lines[-1].balance
        if closing_arg is not None and closing_arg != closing:
            problems.append(RowProblem(
                0, f"The closing balance given ({format_inr(closing_arg)}) differs from the last running balance "
                   f"in the file ({format_inr(closing)})"
            ))
            return
    else:
        if closing_arg is None:
            problems.append(RowProblem(
                0, "The file has no running-balance column: enter the closing balance as per the statement"
            ))
            return
        if closing_arg != running:
            credits = sum((x.credit for x in result.lines), ZERO)
            debits = sum((x.debit for x in result.lines), ZERO)
            problems.append(RowProblem(
                0, f"Opening {format_inr(opening)} + credits {format_inr(credits)} - debits {format_inr(debits)} = "
                   f"{format_inr(running)}, but the closing balance is {format_inr(closing_arg)}"
            ))
            return
        closing = closing_arg
    result.closing_balance = closing
