"""Plain data -> Tally-importable XML text (Phase 7 package B, D-38, D-39). Pure Python: strings only, no XML library, no DB.

The output has the same documented structure the reader (importers/tally_xml.py) accepts, so a file made here is read back by it.
NOT VERIFIED by importing into a real Tally: the structure is the documented one; a real Tally must be asked to import a sample
before the accountant relies on it (docs/decisions_parts/B7.md).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.tally_map import TALLY_TYPE_NAMES

TALLY_EXPORT_VERSION = "tally-export-1"
# Longest ledger / group name written without a warning. An assumption about Tally's own limit, NOT verified: reported, never cut.
TALLY_NAME_MAX = 99


@dataclass(frozen=True)
class ExportGroup:
    name: str
    parent: str


@dataclass(frozen=True)
class ExportLedger:
    name: str
    parent: str  # group name


@dataclass(frozen=True)
class ExportLine:
    ledger_name: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class ExportVoucher:
    voucher_type: str  # our code: sales, credit_note, ...
    voucher_date: date
    number: str
    narration: str | None
    reference_no: str | None
    party_ledger: str | None
    lines: tuple[ExportLine, ...]


@dataclass(frozen=True)
class ExportHeader:
    client_name: str
    financial_year: str   # e.g. 2026-27
    from_date: date | None
    to_date: date | None
    kind: str             # masters | vouchers | both
    generated_at: str = ""  # written into the header comment; makes two exports of the same range two different files


@dataclass(frozen=True)
class ExportResult:
    xml: str
    master_count: int
    voucher_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _xml_char_ok(ch: str) -> bool:
    code = ord(ch)
    return code in (0x9, 0xA, 0xD) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


class _Escaper:
    """Escapes text for XML and remembers every name that held a character XML cannot carry (D-39)."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def __call__(self, value: str, what: str = "") -> str:
        kept = "".join(ch for ch in value if _xml_char_ok(ch))
        if kept != value:
            self.warnings.append(f"{what or 'A value'} '{kept}' contained a character that XML cannot hold; the character was left out.")
        return kept.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _check_name(name: str, kind: str, warnings: list[str], seen: set[str]) -> None:
    if len(name) > TALLY_NAME_MAX:
        warnings.append(f"The {kind} name '{name[:30]}...' is {len(name)} characters; Tally may refuse names longer than {TALLY_NAME_MAX}.")
    key = (kind, name.lower())
    if key in seen:
        warnings.append(f"The {kind} name '{name}' appears twice (names are not case sensitive in Tally).")
    seen.add(key)  # type: ignore[arg-type]


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def build_export(header: ExportHeader, groups: list[ExportGroup], ledgers: list[ExportLedger], vouchers: list[ExportVoucher]) -> ExportResult:
    """D-38: masters first (groups before the ledgers that use them), then the vouchers. Debit = ISDEEMEDPOSITIVE Yes with a negative
    amount; credit = No with a positive amount. Names are escaped; problems are returned as warnings and nothing is shortened."""
    esc = _Escaper()
    warnings: list[str] = []
    seen: set = set()
    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    note = (f"LedgerMind AI export (engine {TALLY_EXPORT_VERSION}); client: {header.client_name}; financial year: {header.financial_year}; "
            f"range: {header.from_date or 'start'} to {header.to_date or 'end'}; kind: {header.kind}; generated: {header.generated_at or 'n/a'}")
    out.append("<!-- " + esc(note).replace("--", "- -") + " -->")
    out.append("<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>")
    out.append("<REPORTNAME>" + ("Vouchers" if header.kind == "vouchers" else "All Masters") + "</REPORTNAME>")
    out.append(f"<STATICVARIABLES><SVCURRENTCOMPANY>{esc(header.client_name, 'The client name')}</SVCURRENTCOMPANY></STATICVARIABLES>")
    out.append("</REQUESTDESC><REQUESTDATA>")
    if groups or ledgers:
        out.append("<TALLYMESSAGE>")
        for g in groups:
            _check_name(g.name, "group", warnings, seen)
            out.append(f'<GROUP NAME="{esc(g.name, "A group name")}" ACTION="Create"><PARENT>{esc(g.parent)}</PARENT></GROUP>')
        for led in ledgers:
            _check_name(led.name, "ledger", warnings, seen)
            out.append(f'<LEDGER NAME="{esc(led.name, "A ledger name")}" ACTION="Create"><PARENT>{esc(led.parent)}</PARENT></LEDGER>')
        out.append("</TALLYMESSAGE>")
    if vouchers:
        out.append("<TALLYMESSAGE>")
        for v in vouchers:
            tally_type = TALLY_TYPE_NAMES[v.voucher_type]
            out.append(f'<VOUCHER VCHTYPE="{tally_type}" ACTION="Create"><DATE>{v.voucher_date:%Y%m%d}</DATE>'
                       f"<VOUCHERTYPENAME>{tally_type}</VOUCHERTYPENAME><VOUCHERNUMBER>{esc(v.number)}</VOUCHERNUMBER>")
            if v.reference_no:
                out.append(f"<REFERENCE>{esc(v.reference_no)}</REFERENCE>")
            if v.party_ledger:
                out.append(f"<PARTYLEDGERNAME>{esc(v.party_ledger)}</PARTYLEDGERNAME>")
            if v.narration:
                out.append(f"<NARRATION>{esc(v.narration)}</NARRATION>")
            for line in v.lines:
                debit = line.debit > 0
                amount = -line.debit if debit else line.credit
                out.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{esc(line.ledger_name)}</LEDGERNAME>"
                           f"<ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE><AMOUNT>{_amount(amount)}</AMOUNT></ALLLEDGERENTRIES.LIST>")
            out.append("</VOUCHER>")
        out.append("</TALLYMESSAGE>")
    out.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return ExportResult("\n".join(out) + "\n", len(groups) + len(ledgers), len(vouchers), tuple(warnings + esc.warnings))
