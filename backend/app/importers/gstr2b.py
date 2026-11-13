"""Read a GSTR-2B file (portal JSON or portal Excel). Pure parsing: no database, no accounting.

NOT VALIDATED AGAINST A REAL PORTAL FILE. The official schema / a sample was not available, so this parser is written
against the documented shape in docs/PHASE3_PLAN.md (`data.docdata.b2b / cdnr`, field names as the portal uses them) and is
strict on purpose: an unknown section, an unknown key or a missing required field rejects the whole file with the row and
the reason (G-40); nothing is guessed or skipped. When the owner supplies real JSON / Excel files the tables below
(_INVOICE_KEYS, _NOTE_KEYS, _SUPPLIER_KEYS, _DATA_KEYS, EXCEL_*) are the only places to adjust.

Sections other than b2b and cdnr (b2ba, cdnra, isd, impg, impgsez) are rejected when they hold documents, because their
shapes are not documented yet. IMS files are not read here for the same reason.

Amounts are Decimal (JSON is read with parse_float=Decimal, never float) and must have at most 2 decimal places.
An absent tax head (e.g. igst on an intra-state document) is 0.00, as the portal omits heads that do not apply.
"""

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.engine.money import MoneyError, parse_amount

ZERO = Decimal("0.00")
GSTIN_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DATA_KEYS = {"gstin", "rtnprd", "gendt", "version", "docdata", "itcsumm"}
_SUPPLIER_KEYS = {"ctin", "trdnm", "supprd", "supfildt", "inv", "nt"}
_COMMON_DOC_KEYS = {"dt", "val", "pos", "rev", "itcavl", "rsn", "diffprcnt", "txval", "igst", "cgst", "sgst", "cess", "srctyp",
                    "irn", "irngendate"}
_INVOICE_KEYS = _COMMON_DOC_KEYS | {"inum", "typ"}
_NOTE_KEYS = _COMMON_DOC_KEYS | {"ntnum", "typ", "ntty", "suptyp"}
_UNSUPPORTED_SECTIONS = {"b2ba", "cdnra", "isd", "impg", "impgsez"}
_ITC = {"Y": "yes", "N": "no", "T": "temporary"}

EXCEL_SHEETS = {"b2b": "B2B", "cdnr": "B2B-CDNR"}
_EXCEL_COMMON = {  # canonical field -> header text (compared without spaces, case or punctuation; a prefix is enough)
    "supplier_gstin": "gstinofsupplier", "supplier_name": "tradelegalname", "doc_date": "date", "doc_value": "value",
    "place_of_supply": "placeofsupply", "reverse_charge": "supplyattractreversecharge", "taxable_value": "taxablevalue",
    "igst": "integratedtax", "cgst": "centraltax", "sgst": "stateuttax", "cess": "cess", "itc_available": "itcavailability",
    "itc_reason": "reason", "supplier_return_period": "period", "supplier_filing_date": "filingdate",
}
_EXCEL_REQUIRED = ("supplier_gstin", "doc_no", "doc_date", "taxable_value", "igst", "cgst", "sgst", "cess", "itc_available")
_EXCEL_NUMBER_HEADER = {"b2b": "invoicenumber", "cdnr": "notenumber"}
_EXCEL_DATE_HEADER = {"b2b": "invoicedate", "cdnr": "notedate"}
_EXCEL_VALUE_HEADER = {"b2b": "invoicevalue", "cdnr": "notevalue"}


@dataclass(frozen=True)
class Problem:
    row: int  # document / sheet row of the file; 0 = the file as a whole
    message: str


class Gstr2bFileError(ValueError):
    """The file is rejected as a whole (G-40). `problems` lists every reason found, each with its row."""

    def __init__(self, problems: list[Problem]):
        super().__init__("; ".join(f"row {p.row}: {p.message}" if p.row else p.message for p in problems))
        self.problems = problems


@dataclass(frozen=True)
class ParsedDocument:
    row_no: int
    section: str
    supplier_gstin: str
    supplier_name: str | None
    doc_type: str  # invoice | credit_note | debit_note
    doc_no: str
    doc_date: date
    place_of_supply: str | None
    reverse_charge: bool
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    doc_value: Decimal | None
    itc_available: str  # yes | no | temporary
    itc_reason: str | None
    supplier_return_period: date | None
    supplier_filing_date: date | None


@dataclass
class ParsedFile:
    source_format: str  # json | excel
    recipient_gstin: str
    period: date | None  # first day of the month the file says it is for (None when the file does not say)
    generated_on: date | None
    documents: list[ParsedDocument] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------ shared pieces


def _parse_date(value: object, what: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip() if value is not None else ""
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{what} {text!r} is not a date (expected dd-mm-yyyy)")


def _month_period(value: object, what: str) -> date:
    """MMYYYY (portal) or Mon-YY / Mon-YYYY -> first day of that month."""
    text = str(value).strip() if value is not None else ""
    if re.fullmatch(r"(0[1-9]|1[0-2])\d{4}", text):
        return date(int(text[2:]), int(text[:2]), 1)
    match = re.fullmatch(r"([A-Za-z]{3})[- ]?(\d{2}|\d{4})", text)
    if match and match.group(1).lower() in _MONTHS:
        year = int(match.group(2))
        return date(year + 2000 if year < 100 else year, _MONTHS[match.group(1).lower()], 1)
    raise ValueError(f"{what} {text!r} is not a month (expected MMYYYY)")


def _amount(value: object, what: str, *, required: bool) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{what} is missing")
        return None
    if isinstance(value, float):  # Excel cells: go through the shortest text so 90.0 is 90, never a binary float
        value = repr(value)
    try:
        return parse_amount(value)
    except MoneyError as e:
        raise ValueError(f"{what}: {e}") from None


def _yes_no(value: object, what: str) -> bool:
    text = str(value).strip().upper() if value is not None else ""
    if text in ("Y", "YES"):
        return True
    if text in ("N", "NO"):
        return False
    raise ValueError(f"{what} {value!r} must be Y or N")


def _itc(value: object) -> str:
    text = str(value).strip().upper() if value is not None else ""
    if text in _ITC:
        return _ITC[text]
    words = {"YES": "yes", "NO": "no", "TEMPORARY": "temporary"}
    if text in words:
        return words[text]
    raise ValueError(f"ITC availability {value!r} must be Y, N or T")


def _check_gstin(value: object, what: str) -> str:
    text = str(value).strip().upper() if value is not None else ""
    if not GSTIN_FORMAT.match(text):
        raise ValueError(f"{what} {value!r} is not a valid GSTIN format")
    return text


def _blank_to_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _build(row_no: int, section: str, supplier: dict, raw: dict, doc_type: str, doc_no: object) -> ParsedDocument:
    """One document from already-extracted raw fields (JSON keys or Excel columns share these names)."""
    number = str(doc_no).strip() if doc_no is not None else ""
    if not number:
        raise ValueError("document number is missing")
    heads = {h: _amount(raw.get(h), h, required=(h == "taxable_value")) or ZERO for h in ("taxable_value", "igst", "cgst", "sgst", "cess")}
    prd, filed = supplier.get("supplier_return_period"), supplier.get("supplier_filing_date")
    return ParsedDocument(
        row_no=row_no, section=section, supplier_gstin=_check_gstin(supplier.get("supplier_gstin"), "supplier GSTIN"),
        supplier_name=_blank_to_none(supplier.get("supplier_name")), doc_type=doc_type, doc_no=number,
        doc_date=_parse_date(raw.get("doc_date"), "document date"),
        place_of_supply=_blank_to_none(raw.get("place_of_supply")),
        reverse_charge=_yes_no(raw.get("reverse_charge", "N"), "reverse charge"),
        doc_value=_amount(raw.get("doc_value"), "document value", required=False),
        itc_available=_itc(raw.get("itc_available")), itc_reason=_blank_to_none(raw.get("itc_reason")),
        supplier_return_period=None if prd in (None, "") else _month_period(prd, "supplier return period"),
        supplier_filing_date=None if filed in (None, "") else _parse_date(filed, "supplier filing date"), **heads,
    )


# ------------------------------------------------------------------------------------------------------- JSON


def _expect(obj: object, kind: type, where: str, problems: list[Problem]) -> bool:
    if not isinstance(obj, kind):
        problems.append(Problem(0, f"{where} must be a {'list' if kind is list else 'JSON object'}"))
        return False
    return True


def parse_json(content: bytes) -> ParsedFile:
    problems: list[Problem] = []
    try:
        root = json.loads(content.decode("utf-8-sig"), parse_float=Decimal, parse_int=Decimal)
    except (UnicodeDecodeError, ValueError):
        raise Gstr2bFileError([Problem(0, "The file is not valid JSON")]) from None
    if not isinstance(root, dict) or not isinstance(root.get("data"), dict):
        raise Gstr2bFileError([Problem(0, "This is not a GSTR-2B JSON file: the top level must hold a 'data' object")])
    data = root["data"]
    unknown = sorted(set(data) - _DATA_KEYS)
    if unknown:
        raise Gstr2bFileError([Problem(0, f"Unknown key(s) in 'data': {', '.join(unknown)}; the file layout is not recognised")])
    try:
        recipient = _check_gstin(data.get("gstin"), "recipient GSTIN (data.gstin)")
        period = _month_period(data.get("rtnprd"), "return period (data.rtnprd)")
        generated = None if data.get("gendt") in (None, "") else _parse_date(data["gendt"], "generation date (data.gendt)")
    except ValueError as e:
        raise Gstr2bFileError([Problem(0, str(e))]) from None
    docdata = data.get("docdata")
    if not isinstance(docdata, dict):
        raise Gstr2bFileError([Problem(0, "'data.docdata' is missing: the file layout is not recognised")])
    sections = set(docdata)
    unknown_sections = sorted(sections - {"b2b", "cdnr"} - _UNSUPPORTED_SECTIONS)
    if unknown_sections:
        raise Gstr2bFileError([Problem(0, f"Unknown section(s) in 'docdata': {', '.join(unknown_sections)}")])
    for name in sorted(sections & _UNSUPPORTED_SECTIONS):
        if docdata[name]:
            problems.append(Problem(0, f"Section '{name}' holds documents but this version cannot read it yet; "
                                       "a real portal file of that section is needed"))
    parsed = ParsedFile("json", recipient, period, generated)
    for section, list_key, kinds in (("b2b", "inv", _INVOICE_KEYS), ("cdnr", "nt", _NOTE_KEYS)):
        suppliers = docdata.get(section, [])
        if not _expect(suppliers, list, f"docdata.{section}", problems):
            continue
        for supplier in suppliers:
            _json_supplier(parsed, section, list_key, kinds, supplier, problems)
    if problems:
        raise Gstr2bFileError(problems)
    return parsed


def _json_supplier(parsed: ParsedFile, section: str, list_key: str, allowed: set, supplier: object, problems: list[Problem]) -> None:
    row = len(parsed.documents) + 1
    if not isinstance(supplier, dict):
        problems.append(Problem(row, f"{section}: a supplier entry must be a JSON object"))
        return
    extra = sorted(set(supplier) - _SUPPLIER_KEYS)
    if extra or list_key not in supplier:
        problems.append(Problem(row, f"{section}: supplier entry {supplier.get('ctin')!r} has "
                                     + (f"unknown key(s) {', '.join(extra)}" if extra else f"no '{list_key}' list")))
        return
    other = "nt" if list_key == "inv" else "inv"
    if other in supplier:
        problems.append(Problem(row, f"{section}: supplier entry {supplier.get('ctin')!r} holds '{other}', expected '{list_key}'"))
        return
    header = {"supplier_gstin": supplier.get("ctin"), "supplier_name": supplier.get("trdnm"),
              "supplier_return_period": supplier.get("supprd"), "supplier_filing_date": supplier.get("supfildt")}
    if not isinstance(supplier[list_key], list):
        problems.append(Problem(row, f"{section}: '{list_key}' of {supplier.get('ctin')!r} must be a list"))
        return
    for item in supplier[list_key]:
        row = len(parsed.documents) + 1
        label = f"{section} {supplier.get('ctin')!r}"
        if not isinstance(item, dict):
            problems.append(Problem(row, f"{label}: a document must be a JSON object"))
            parsed.documents.append(None)  # keeps row numbers aligned; removed below when there are no problems
            continue
        extra = sorted(set(item) - allowed)
        if extra:
            problems.append(Problem(row, f"{label}: unknown key(s) {', '.join(extra)}"))
            parsed.documents.append(None)
            continue
        number = item.get("inum" if section == "b2b" else "ntnum")
        raw = {"doc_date": item.get("dt"), "doc_value": item.get("val"), "place_of_supply": item.get("pos"),
               "reverse_charge": item.get("rev"), "itc_available": item.get("itcavl"), "itc_reason": item.get("rsn"),
               "taxable_value": item.get("txval"), "igst": item.get("igst"), "cgst": item.get("cgst"),
               "sgst": item.get("sgst"), "cess": item.get("cess")}
        try:
            if section == "b2b":
                doc_type = "invoice"
            else:
                note_kind = item.get("typ", item.get("ntty"))
                if str(note_kind).strip().upper() not in ("C", "D"):
                    raise ValueError(f"note type {note_kind!r} must be C (credit note) or D (debit note)")
                doc_type = "credit_note" if str(note_kind).strip().upper() == "C" else "debit_note"
            parsed.documents.append(_build(row, section, header, raw, doc_type, number))
        except ValueError as e:
            problems.append(Problem(row, f"{label} number {number!r}: {e}"))
            parsed.documents.append(None)


# ------------------------------------------------------------------------------------------------------ Excel


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower()) if value is not None else ""


def _find_header(rows: list[tuple], section: str) -> tuple[int, dict[str, int]] | None:
    wanted = dict(_EXCEL_COMMON, doc_no=_EXCEL_NUMBER_HEADER[section])
    wanted["doc_date"] = _EXCEL_DATE_HEADER[section]
    wanted["doc_value"] = _EXCEL_VALUE_HEADER[section]
    if section == "cdnr":
        wanted["note_type"] = "notetype"
    for index, row in enumerate(rows[:12]):
        cells = [_norm(c) for c in row]
        if "gstinofsupplier" not in cells:
            continue
        columns: dict[str, int] = {}
        for key, text in wanted.items():
            for col, cell in enumerate(cells):
                if cell.startswith(text) or (key in ("supplier_return_period", "supplier_filing_date") and text in cell):
                    columns.setdefault(key, col)
                    break
        return index, columns
    return None


def _excel_recipient(workbook) -> str:
    for name in workbook.sheetnames:
        if _norm(name) in ("readme",):
            rows = list(workbook[name].iter_rows(values_only=True))
            for row in rows:
                for col, cell in enumerate(row):
                    if _norm(cell) == "gstin" and col + 1 < len(row) and row[col + 1]:
                        return _check_gstin(row[col + 1], "recipient GSTIN (Read me sheet)")
    raise ValueError("The recipient GSTIN was not found: a 'Read me' sheet with a GSTIN cell is expected")


def parse_excel(content: bytes) -> ParsedFile:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError):
        raise Gstr2bFileError([Problem(0, "The file is not a readable .xlsx workbook")]) from None
    try:
        recipient = _excel_recipient(workbook)
    except ValueError as e:
        raise Gstr2bFileError([Problem(0, str(e))]) from None
    parsed = ParsedFile("excel", recipient, None, None)
    problems: list[Problem] = []
    found_any = False
    for section, sheet in EXCEL_SHEETS.items():
        if sheet not in workbook.sheetnames:
            continue
        found_any = True
        rows = list(workbook[sheet].iter_rows(values_only=True))
        header = _find_header(rows, section)
        if header is None:
            problems.append(Problem(0, f"Sheet '{sheet}': the header row (with 'GSTIN of supplier') was not found"))
            continue
        index, columns = header
        missing = [k for k in _EXCEL_REQUIRED if k not in columns]
        if missing:
            problems.append(Problem(0, f"Sheet '{sheet}': column(s) not found: {', '.join(missing)}"))
            continue
        for offset, row in enumerate(rows[index + 1:], start=index + 2):
            cells = {key: (row[col] if col < len(row) else None) for key, col in columns.items()}
            if all(v in (None, "") for v in cells.values()) or not cells.get("supplier_gstin"):
                if any(v not in (None, "") for v in cells.values()):
                    problems.append(Problem(offset, f"Sheet '{sheet}': supplier GSTIN is missing"))
                continue
            supplier = {k: cells.get(k) for k in ("supplier_gstin", "supplier_name", "supplier_return_period",
                                                  "supplier_filing_date")}
            try:
                if section == "b2b":
                    doc_type = "invoice"
                else:
                    kind = _norm(cells.get("note_type"))
                    doc_type = {"c": "credit_note", "creditnote": "credit_note", "d": "debit_note", "debitnote": "debit_note"}.get(kind)
                    if doc_type is None:
                        raise ValueError(f"note type {cells.get('note_type')!r} must be Credit Note or Debit Note")
                parsed.documents.append(_build(len(parsed.documents) + 1, section, supplier, cells, doc_type, cells.get("doc_no")))
            except ValueError as e:
                problems.append(Problem(offset, f"Sheet '{sheet}': {e}"))
    if not found_any:
        problems.append(Problem(0, f"None of the expected sheets ({', '.join(EXCEL_SHEETS.values())}) was found"))
    if problems:
        raise Gstr2bFileError(problems)
    return parsed


def parse_gstr2b(content: bytes) -> ParsedFile:
    """JSON (starts with '{') or Excel (a zip); anything else is rejected."""
    head = content.lstrip()[:1]
    if head == b"{":
        parsed = parse_json(content)
    elif content[:2] == b"PK":
        parsed = parse_excel(content)
    else:
        raise Gstr2bFileError([Problem(0, "The file is neither a GSTR-2B JSON nor an Excel (.xlsx) file")])
    return parsed
