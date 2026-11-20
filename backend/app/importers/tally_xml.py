"""Strict reader of a Tally XML file (Phase 7 package B, rules D-30, D-35, D-36). Pure parse: no database, no accounting.

The structure is the documented Tally import / export shape and nothing else:

    ENVELOPE / BODY / IMPORTDATA / REQUESTDATA / TALLYMESSAGE / GROUP | LEDGER | STOCKITEM | VOUCHER
    VOUCHER / ALLLEDGERENTRIES.LIST or LEDGERENTRIES.LIST  (LEDGERNAME, ISDEEMEDPOSITIVE, AMOUNT, BILLALLOCATIONS.LIST)
    VOUCHER / ALLINVENTORYENTRIES.LIST or INVENTORYENTRIES.LIST / ACCOUNTINGALLOCATIONS.LIST  (same entry shape)

NOT VERIFIED against a real export: the schema is not officially available to the developers. Anything that does not fit is
rejected with a message that names the place, never guessed. A real sample from the accountant's Tally must be run through
`parse_tally_xml` before this is relied on (docs/decisions_parts/B7.md).

Safety: defusedxml with DTDs and entities forbidden (D-30). The file may be UTF-8 or UTF-16; character references to characters XML
cannot hold (Tally writes some, e.g. &#4;) are removed before parsing.
"""

import codecs
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET


class TallyParseError(ValueError):
    """The file is not a Tally file this reader understands. `rule_id` is D-30 (file level) or D-35 (voucher entry shape)."""

    def __init__(self, message: str, rule_id: str = "D-30"):
        super().__init__(message)
        self.rule_id = rule_id
        self.message = message


@dataclass(frozen=True)
class TallyGroup:
    name: str
    parent: str | None


@dataclass(frozen=True)
class TallyLedger:
    name: str
    parent: str | None
    opening_balance: str | None  # the text exactly as in the file; its sign convention is NOT interpreted (D-33)
    gstin: str | None = None


@dataclass(frozen=True)
class TallyStockItem:
    name: str
    parent: str | None
    unit: str | None
    hsn: str | None


@dataclass(frozen=True)
class TallyEntry:
    ledger_name: str
    amount: Decimal          # exactly as in the file (Tally: debit negative, credit positive)
    deemed_positive: bool    # ISDEEMEDPOSITIVE: Yes = the entry is on the debit side
    bill_allocations: int = 0
    from_inventory: bool = False


@dataclass(frozen=True)
class TallyVoucher:
    guid: str | None
    voucher_type: str
    voucher_date: date
    number: str | None
    narration: str | None
    reference: str | None
    party_ledger: str | None
    is_cancelled: bool
    is_optional: bool
    is_postdated: bool
    entries: tuple[TallyEntry, ...]
    inventory_lines: int = 0


@dataclass(frozen=True)
class TallyFile:
    company_name: str | None
    groups: tuple[TallyGroup, ...]
    ledgers: tuple[TallyLedger, ...]
    stock_items: tuple[TallyStockItem, ...]
    vouchers: tuple[TallyVoucher, ...]
    ignored: dict[str, int] = field(default_factory=dict)  # known master kinds this reader does not use (UNIT, GODOWN, ...)


# master kinds that exist in Tally exports and are deliberately not imported (counted in the report, never an error)
IGNORED_KINDS = frozenset({
    "UNIT", "CURRENCY", "GODOWN", "VOUCHERTYPE", "COSTCENTRE", "COSTCATEGORY", "STOCKGROUP", "STOCKCATEGORY", "COMPANY",
    "TDSCATEGORY", "ATTENDANCETYPE", "EMPLOYEE", "REPORTINGUNIT",
})
ENTRY_TAGS = ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST")
INVENTORY_TAGS = ("ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST")
_AMOUNT = re.compile(r"^-?\d+(\.\d{1,2})?$")
_CHAR_REF = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")
_RAW_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")


def _xml_char_ok(code: int) -> bool:
    return code in (0x9, 0xA, 0xD) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


def _decode(data: bytes) -> str:
    if not data.strip():
        raise TallyParseError("The file is empty.")
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TallyParseError("The file is neither UTF-8 nor UTF-16 text, so it cannot be a Tally XML export.") from None


def _clean(text: str) -> str:
    text = _DECLARATION.sub("", text)
    text = _RAW_CONTROL.sub("", text)

    def drop_illegal(m: re.Match) -> str:
        ref = m.group(1)
        code = int(ref[1:], 16) if ref[0] == "x" else int(ref)
        return m.group(0) if _xml_char_ok(code) else ""

    return _CHAR_REF.sub(drop_illegal, text)


def _text(el: Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or child.text is None or not child.text.strip():
        return None
    return child.text.strip()


def _name(el: Element, what: str) -> str:
    name = (el.get("NAME") or "").strip()
    if not name:
        listed = el.find("NAME.LIST/NAME")
        name = (listed.text or "").strip() if listed is not None and listed.text else ""
    if not name:
        raise TallyParseError(f"A {what} in the file has no name (neither a NAME attribute nor NAME.LIST/NAME).")
    return name


def _yes_no(el: Element, tag: str, where: str, *, required: bool = False) -> bool:
    raw = _text(el, tag)
    if raw is None:
        if required:
            raise TallyParseError(f"{where}: {tag} is missing.", "D-35")
        return False
    if raw.lower() not in ("yes", "no"):
        raise TallyParseError(f"{where}: {tag} must be Yes or No, found '{raw}'.", "D-35" if required else "D-30")
    return raw.lower() == "yes"


def _entry(el: Element, where: str, *, from_inventory: bool) -> TallyEntry:
    ledger = _text(el, "LEDGERNAME")
    if ledger is None:
        raise TallyParseError(f"{where}: an entry has no LEDGERNAME.", "D-35")
    raw_amount = _text(el, "AMOUNT")
    if raw_amount is None or not _AMOUNT.match(raw_amount):
        raise TallyParseError(
            f"{where}: the amount of '{ledger}' is '{raw_amount}'; a plain number with at most 2 decimals is required "
            "(it is rejected, never rounded).", "D-35")
    return TallyEntry(
        ledger, Decimal(raw_amount), _yes_no(el, "ISDEEMEDPOSITIVE", f"{where}, ledger '{ledger}'", required=True),
        len(el.findall("BILLALLOCATIONS.LIST")), from_inventory,
    )


def _voucher(el: Element) -> TallyVoucher:
    vtype = (el.get("VCHTYPE") or _text(el, "VOUCHERTYPENAME") or "").strip()
    number = _text(el, "VOUCHERNUMBER")
    where = f"Voucher {number or '(no number)'}"
    if not vtype:
        raise TallyParseError(f"{where}: the voucher type is missing (VCHTYPE or VOUCHERTYPENAME).")
    action = el.get("ACTION")
    if action not in (None, "Create", "Alter"):
        raise TallyParseError(f"{where}: ACTION '{action}' is not understood (only Create or Alter).")
    raw_date = _text(el, "DATE")
    if raw_date is None or not re.fullmatch(r"\d{8}", raw_date):
        raise TallyParseError(f"{where}: DATE '{raw_date}' is not in the form YYYYMMDD.")
    try:
        on = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:]))
    except ValueError:
        raise TallyParseError(f"{where}: DATE '{raw_date}' is not a real date.") from None
    entries = [_entry(e, where, from_inventory=False) for tag in ENTRY_TAGS for e in el.findall(tag)]
    inventory = [i for tag in INVENTORY_TAGS for i in el.findall(tag)]
    for inv in inventory:
        entries += [_entry(e, where, from_inventory=True) for e in inv.findall("ACCOUNTINGALLOCATIONS.LIST")]
    return TallyVoucher(
        _text(el, "GUID"), vtype, on, number, _text(el, "NARRATION"), _text(el, "REFERENCE"), _text(el, "PARTYLEDGERNAME"),
        _yes_no(el, "ISCANCELLED", where), _yes_no(el, "ISOPTIONAL", where), _yes_no(el, "ISPOSTDATED", where),
        tuple(entries), len(inventory),
    )


def parse_tally_xml(data: bytes) -> TallyFile:
    text = _clean(_decode(data))
    try:
        root = SafeET.fromstring(text, forbid_dtd=True)
    except DefusedXmlException:
        raise TallyParseError(
            "The file contains a DTD or entity declaration. Tally exports never do; the file is refused for safety (D-30).") from None
    except ParseError as exc:
        raise TallyParseError(f"The file is not well-formed XML: {exc}.") from None
    if root.tag != "ENVELOPE":
        raise TallyParseError(f"Not a Tally file: the top element is <{root.tag}>, expected <ENVELOPE>.")
    request = root.find("BODY/IMPORTDATA/REQUESTDATA")
    if request is None:
        raise TallyParseError("Not a Tally import / export file: ENVELOPE/BODY/IMPORTDATA/REQUESTDATA was not found.")
    company = root.find("BODY/IMPORTDATA/REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY")
    groups, ledgers, items, vouchers = [], [], [], []
    ignored: dict[str, int] = {}
    messages = request.findall("TALLYMESSAGE")
    if not messages:
        raise TallyParseError("REQUESTDATA holds no TALLYMESSAGE.")
    for message in messages:
        for el in message:
            if el.tag == "GROUP":
                groups.append(TallyGroup(_name(el, "group"), _text(el, "PARENT")))
            elif el.tag == "LEDGER":
                ledgers.append(TallyLedger(_name(el, "ledger"), _text(el, "PARENT"), _text(el, "OPENINGBALANCE"),
                                           _text(el, "PARTYGSTIN")))
            elif el.tag == "STOCKITEM":
                hsn = _text(el, "GSTDETAILS.LIST/HSNCODE") or _text(el, "HSNCODE")
                items.append(TallyStockItem(_name(el, "stock item"), _text(el, "PARENT"), _text(el, "BASEUNITS"), hsn))
            elif el.tag == "VOUCHER":
                vouchers.append(_voucher(el))
            elif el.tag in IGNORED_KINDS:
                ignored[el.tag] = ignored.get(el.tag, 0) + 1
            else:
                raise TallyParseError(f"Unknown element <{el.tag}> inside TALLYMESSAGE; this reader accepts only GROUP, LEDGER, "
                                      "STOCKITEM and VOUCHER (and ignores " + ", ".join(sorted(IGNORED_KINDS)) + ").")
    if not (groups or ledgers or items or vouchers):
        raise TallyParseError("The file holds no group, ledger, stock item or voucher.")
    return TallyFile(
        company.text.strip() if company is not None and company.text else None,
        tuple(groups), tuple(ledgers), tuple(items), tuple(vouchers), ignored,
    )
