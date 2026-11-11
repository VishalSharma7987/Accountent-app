"""Reads a test-pack folder (see docs/test-packs/README.md) and checks the pack's own format.

This is a format/consistency check of the files the accountants fill in. It does NOT compute
accounting results and never imports the accounting engine.

    from pack_loader import load_pack, PackError
    pack = load_pack(Path("docs/test-packs/abc-traders-apr-2026"))   # raises PackError listing every problem
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

ENTITY_TYPES = ("proprietorship", "partnership", "llp", "company")
BUSINESS_TYPES = ("trading", "service", "manufacturing")
GST_TYPES = ("regular", "composition", "unregistered")
VOUCHER_TYPES = (
    "contra", "payment", "receipt", "sales", "purchase", "credit_note", "debit_note", "journal",
)
# Account groups seeded in the database (CLAUDE.md section 5).
KNOWN_GROUPS = frozenset({
    "Capital Account", "Reserves & Surplus", "Loans (Liability)", "Current Liabilities",
    "Sundry Creditors", "Duties & Taxes", "Provisions", "Fixed Assets", "Investments",
    "Current Assets", "Sundry Debtors", "Bank Accounts", "Cash-in-hand", "Stock-in-hand",
    "Loans & Advances (Asset)", "Deposits (Asset)", "Sales Accounts", "Direct Incomes",
    "Indirect Incomes", "Purchase Accounts", "Direct Expenses", "Indirect Expenses", "Suspense A/c",
})

CLIENT_KEYS = ("name", "entity_type", "business_type", "gst_type", "fy_start", "pack_end_date")
LEDGER_COLS = ("ledger_name", "group_name", "opening_dr", "opening_cr")
VOUCHER_COLS = (
    "ref_id", "date", "voucher_type", "ledger_name", "debit", "credit", "narration", "reference_no",
)
INVALID_COLS = VOUCHER_COLS + ("expected_rule_id", "expected_message_contains")
BALANCE_COLS = ("ledger_name", "closing_dr", "closing_cr")
TB_COLS = ("group_name", "ledger_name", "dr", "cr")

_AMOUNT = re.compile(r"^\d+\.\d{2}$")
_RULE_ID = re.compile(r"^V-(0[1-9]|1[0-4])$")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class PackIssue:
    file: str
    row: int | None  # CSV row number as seen in Excel (header = row 1); None for whole-file problems
    message: str

    def __str__(self) -> str:
        where = self.file if self.row is None else f"{self.file} row {self.row}"
        return f"{where}: {self.message}"


class PackError(Exception):
    def __init__(self, issues: list[PackIssue]):
        self.issues = issues
        super().__init__(
            f"{len(issues)} problem(s) in test pack:\n" + "\n".join(f"  - {i}" for i in issues)
        )


@dataclass(frozen=True)
class Client:
    name: str
    entity_type: str
    business_type: str
    gst_type: str
    fy_start: date
    pack_end_date: date


@dataclass(frozen=True)
class LedgerRow:
    name: str
    group: str
    opening_dr: Decimal
    opening_cr: Decimal


@dataclass(frozen=True)
class VoucherLineRow:
    row: int
    ref_id: str
    date: date
    voucher_type: str
    ledger_name: str
    debit: Decimal
    credit: Decimal
    narration: str
    reference_no: str


@dataclass(frozen=True)
class InvalidLineRow:
    """A line of a deliberately wrong voucher. Amounts stay as typed (text): the point is to test bad input."""

    row: int
    ref_id: str
    date: date
    voucher_type: str
    ledger_name: str
    debit: str
    credit: str
    narration: str
    reference_no: str
    expected_rule_id: str
    expected_message_contains: str


@dataclass(frozen=True)
class BalanceRow:
    ledger_name: str
    closing_dr: Decimal
    closing_cr: Decimal


@dataclass(frozen=True)
class TrialBalanceRow:
    group_name: str
    ledger_name: str
    dr: Decimal
    cr: Decimal


@dataclass(frozen=True)
class Pack:
    folder: Path
    client: Client
    ledgers: tuple[LedgerRow, ...]
    vouchers: tuple[VoucherLineRow, ...]
    invalid_vouchers: tuple[InvalidLineRow, ...]
    expected_balances: tuple[BalanceRow, ...]
    expected_tb: tuple[TrialBalanceRow, ...]
    expected_tb_total: tuple[Decimal, Decimal]  # (dr, cr) from the TOTAL row


# --------------------------------------------------------------------------- helpers


class _Collector:
    def __init__(self) -> None:
        self.issues: list[PackIssue] = []

    def add(self, file: str, row: int | None, message: str) -> None:
        self.issues.append(PackIssue(file, row, message))


def _parse_date(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_amount(text: str) -> Decimal | None:
    """Plain number with exactly 2 decimals: no commas, no sign, no currency symbol."""
    return Decimal(text) if _AMOUNT.match(text) else None


def _read_csv(
    folder: Path, name: str, columns: tuple[str, ...], errs: _Collector
) -> list[tuple[int, dict[str, str]]]:
    """Rows as (excel_row_number, {column: stripped text}). Header must match exactly."""
    path = folder / name
    if not path.is_file():
        errs.add(name, None, "file is missing")
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            errs.add(name, None, "file is empty")
            return []
        if tuple(header) != columns:
            errs.add(name, 1, f"header must be exactly: {','.join(columns)} (found: {','.join(header)})")
            return []
        rows = []
        for number, values in enumerate(reader, start=2):
            if not any(v.strip() for v in values):
                continue  # blank line
            if len(values) != len(columns):
                errs.add(name, number, f"expected {len(columns)} columns, found {len(values)}")
                continue
            rows.append((number, {c: v.strip() for c, v in zip(columns, values, strict=True)}))
        if not rows:
            errs.add(name, None, "file has a header but no data rows")
    return rows


def _load_client(folder: Path, errs: _Collector) -> Client | None:
    name = "client.yaml"
    path = folder / name
    if not path.is_file():
        errs.add(name, None, "file is missing")
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errs.add(name, None, f"not valid YAML: {exc}")
        return None
    if not isinstance(data, dict):
        errs.add(name, None, "must be a list of 'key: value' lines")
        return None

    before = len(errs.issues)
    for key in CLIENT_KEYS:
        if data.get(key) in (None, ""):
            errs.add(name, None, f"'{key}' is missing")
    for key in data:
        if key not in CLIENT_KEYS:
            errs.add(name, None, f"unknown key '{key}'")
    text = {k: str(data[k]).strip() for k in CLIENT_KEYS if data.get(k) not in (None, "")}
    for key, allowed in (
        ("entity_type", ENTITY_TYPES), ("business_type", BUSINESS_TYPES), ("gst_type", GST_TYPES),
    ):
        if key in text and text[key] not in allowed:
            errs.add(name, None, f"'{key}' must be one of {', '.join(allowed)} (found: {text[key]})")
    dates: dict[str, date] = {}
    for key in ("fy_start", "pack_end_date"):
        if key in text:
            parsed = _parse_date(text[key])
            if parsed is None:
                errs.add(name, None, f"'{key}' must be a real date as YYYY-MM-DD (found: {text[key]})")
            else:
                dates[key] = parsed
    if "fy_start" in dates and (dates["fy_start"].month, dates["fy_start"].day) != (4, 1):
        errs.add(name, None, "'fy_start' must be 1 April (financial year is 1 April - 31 March)")
    if len(dates) == 2:
        fy_end = date(dates["fy_start"].year + 1, 3, 31)
        if not dates["fy_start"] <= dates["pack_end_date"] <= fy_end:
            errs.add(name, None, f"'pack_end_date' must be inside the financial year (up to {fy_end})")
    if len(errs.issues) > before:
        return None
    return Client(
        text["name"], text["entity_type"], text["business_type"], text["gst_type"],
        dates["fy_start"], dates["pack_end_date"],
    )


def _load_ledgers(folder: Path, errs: _Collector) -> list[LedgerRow]:
    file = "ledgers.csv"
    out: list[LedgerRow] = []
    seen: dict[str, int] = {}
    for number, r in _read_csv(folder, file, LEDGER_COLS, errs):
        name = r["ledger_name"]
        if not name:
            errs.add(file, number, "ledger_name is empty")
            continue
        if name.lower() in seen:
            errs.add(file, number, f"duplicate ledger '{name}' (same as row {seen[name.lower()]}; names are not case-sensitive)")
        seen.setdefault(name.lower(), number)
        if r["group_name"] not in KNOWN_GROUPS:
            errs.add(file, number, f"unknown group '{r['group_name']}' (use a group from CLAUDE.md section 5)")
        dr, cr = _parse_amount(r["opening_dr"]), _parse_amount(r["opening_cr"])
        if dr is None or cr is None:
            errs.add(file, number, "opening_dr and opening_cr must be plain numbers with 2 decimals, e.g. 1500.00 (use 0.00 for none)")
            continue
        if dr > 0 and cr > 0:
            errs.add(file, number, "a ledger cannot have both an opening debit and an opening credit")
        out.append(LedgerRow(name, r["group_name"], dr, cr))
    if out and sum(x.opening_dr for x in out) != sum(x.opening_cr for x in out):
        errs.add(
            file, None,
            f"opening balances do not balance: total Dr {sum(x.opening_dr for x in out)} "
            f"vs total Cr {sum(x.opening_cr for x in out)}",
        )
    return out


def _check_ref_groups(file: str, rows: list, errs: _Collector) -> None:
    """Rows with the same ref_id are one voucher: date, type, narration, reference_no must agree."""
    first: dict[str, object] = {}
    for r in rows:
        head = first.setdefault(r.ref_id, r)
        for attr in ("date", "voucher_type", "narration", "reference_no"):
            if getattr(r, attr) != getattr(head, attr):
                errs.add(file, r.row, f"ref_id {r.ref_id}: {attr} differs from its first row ({head.row})")


def _load_vouchers(
    folder: Path, client: Client | None, ledger_names: set[str], errs: _Collector
) -> list[VoucherLineRow]:
    file = "vouchers.csv"
    out: list[VoucherLineRow] = []
    for number, r in _read_csv(folder, file, VOUCHER_COLS, errs):
        ok = True
        if not r["ref_id"]:
            errs.add(file, number, "ref_id is empty")
            ok = False
        d = _parse_date(r["date"])
        if d is None:
            errs.add(file, number, f"date must be a real date as YYYY-MM-DD (found: '{r['date']}')")
            ok = False
        elif client and not client.fy_start <= d <= client.pack_end_date:
            errs.add(file, number, f"date {d} is outside the pack period {client.fy_start} to {client.pack_end_date}")
            ok = False
        if r["voucher_type"] not in VOUCHER_TYPES:
            errs.add(file, number, f"voucher_type must be one of {', '.join(VOUCHER_TYPES)} (found: '{r['voucher_type']}')")
            ok = False
        if r["ledger_name"] not in ledger_names:
            errs.add(file, number, f"unknown ledger '{r['ledger_name']}' (must match a name in ledgers.csv exactly)")
            ok = False
        dr, cr = _parse_amount(r["debit"]), _parse_amount(r["credit"])
        if dr is None or cr is None:
            errs.add(file, number, "debit and credit must be plain numbers with 2 decimals (use 0.00 for the empty side)")
            ok = False
        elif (dr > 0) == (cr > 0):
            errs.add(file, number, "each line needs exactly one of debit / credit above zero")
            ok = False
        if not r["narration"]:
            errs.add(file, number, "narration is empty (a valid voucher needs one)")
            ok = False
        if ok:
            out.append(VoucherLineRow(
                number, r["ref_id"], d, r["voucher_type"], r["ledger_name"], dr, cr,
                r["narration"], r["reference_no"],
            ))
    _check_ref_groups(file, out, errs)
    by_ref: dict[str, list[VoucherLineRow]] = {}
    for line in out:
        by_ref.setdefault(line.ref_id, []).append(line)
    for ref, lines in by_ref.items():
        if len(lines) < 2:
            errs.add(file, lines[0].row, f"voucher {ref} has only one line")
        total_dr, total_cr = sum(x.debit for x in lines), sum(x.credit for x in lines)
        if total_dr != total_cr:
            errs.add(file, lines[0].row, f"voucher {ref} is not balanced: Dr {total_dr} vs Cr {total_cr}")
    return out


def _load_invalid(folder: Path, errs: _Collector) -> list[InvalidLineRow]:
    """Wrong vouchers are allowed to have unknown ledgers, bad amounts, empty narration: that is the test."""
    file = "invalid_vouchers.csv"
    out: list[InvalidLineRow] = []
    for number, r in _read_csv(folder, file, INVALID_COLS, errs):
        ok = True
        if not r["ref_id"]:
            errs.add(file, number, "ref_id is empty")
            ok = False
        d = _parse_date(r["date"])
        if d is None:
            errs.add(file, number, f"date must be a real date as YYYY-MM-DD (found: '{r['date']}')")
            ok = False
        if r["voucher_type"] not in VOUCHER_TYPES:
            errs.add(file, number, f"voucher_type must be one of {', '.join(VOUCHER_TYPES)} (found: '{r['voucher_type']}')")
            ok = False
        if not _RULE_ID.match(r["expected_rule_id"]):
            errs.add(file, number, f"expected_rule_id must be V-01 .. V-14 (found: '{r['expected_rule_id']}')")
            ok = False
        if not r["expected_message_contains"]:
            errs.add(file, number, "expected_message_contains is empty (give a word the error message must contain)")
            ok = False
        if ok:
            out.append(InvalidLineRow(
                number, r["ref_id"], d, r["voucher_type"], r["ledger_name"], r["debit"], r["credit"],
                r["narration"], r["reference_no"], r["expected_rule_id"], r["expected_message_contains"],
            ))
    _check_ref_groups(file, out, errs)
    by_ref: dict[str, set[tuple[str, str]]] = {}
    for line in out:
        by_ref.setdefault(line.ref_id, set()).add((line.expected_rule_id, line.expected_message_contains))
    for ref, expectations in by_ref.items():
        if len(expectations) > 1:
            first = next(x for x in out if x.ref_id == ref)
            errs.add(file, first.row, f"voucher {ref}: every line must carry the same expected_rule_id and expected_message_contains")
    return out


def _load_balances(folder: Path, ledger_names: set[str], errs: _Collector) -> list[BalanceRow]:
    file = "expected_ledger_balances.csv"
    out: list[BalanceRow] = []
    seen: set[str] = set()
    for number, r in _read_csv(folder, file, BALANCE_COLS, errs):
        name = r["ledger_name"]
        if name not in ledger_names:
            errs.add(file, number, f"unknown ledger '{name}' (must match a name in ledgers.csv exactly)")
        if name in seen:
            errs.add(file, number, f"ledger '{name}' appears twice")
        seen.add(name)
        dr, cr = _parse_amount(r["closing_dr"]), _parse_amount(r["closing_cr"])
        if dr is None or cr is None:
            errs.add(file, number, "closing_dr and closing_cr must be plain numbers with 2 decimals (use 0.00 for none)")
            continue
        if dr > 0 and cr > 0:
            errs.add(file, number, "a closing balance is either Dr or Cr, not both")
        out.append(BalanceRow(name, dr, cr))
    missing = sorted(ledger_names - seen)
    if out and missing:
        errs.add(file, None, f"every ledger must be listed (use 0.00 / 0.00 for a nil balance); missing: {', '.join(missing)}")
    return out


def _load_tb(
    folder: Path, ledgers: dict[str, LedgerRow], balances: list[BalanceRow], errs: _Collector
) -> tuple[list[TrialBalanceRow], tuple[Decimal, Decimal]]:
    file = "expected_trial_balance.csv"
    rows: list[TrialBalanceRow] = []
    total: tuple[Decimal, Decimal] | None = None
    balance_by_name = {b.ledger_name: b for b in balances}
    seen: set[str] = set()
    for number, r in _read_csv(folder, file, TB_COLS, errs):
        dr, cr = _parse_amount(r["dr"]), _parse_amount(r["cr"])
        if dr is None or cr is None:
            errs.add(file, number, "dr and cr must be plain numbers with 2 decimals (use 0.00 for none)")
            continue
        if r["group_name"] == "TOTAL":
            if total is not None:
                errs.add(file, number, "there must be only one TOTAL row")
            if r["ledger_name"]:
                errs.add(file, number, "the TOTAL row must have an empty ledger_name")
            total = (dr, cr)
            continue
        name = r["ledger_name"]
        if name not in ledgers:
            errs.add(file, number, f"unknown ledger '{name}' (must match a name in ledgers.csv exactly)")
            continue
        if name in seen:
            errs.add(file, number, f"ledger '{name}' appears twice")
        seen.add(name)
        if r["group_name"] != ledgers[name].group:
            errs.add(file, number, f"group '{r['group_name']}' does not match ledgers.csv ('{ledgers[name].group}') for '{name}'")
        if dr > 0 and cr > 0:
            errs.add(file, number, "a ledger line is either Dr or Cr, not both")
        bal = balance_by_name.get(name)
        if bal and (bal.closing_dr, bal.closing_cr) != (dr, cr):
            errs.add(file, number, f"'{name}' is Dr {dr} / Cr {cr} here but Dr {bal.closing_dr} / Cr {bal.closing_cr} in expected_ledger_balances.csv")
        rows.append(TrialBalanceRow(r["group_name"], name, dr, cr))
    if total is None:
        if rows:
            errs.add(file, None, "the TOTAL row is missing (group_name = TOTAL, with the Dr and Cr totals)")
        return rows, (_ZERO, _ZERO)
    sum_dr, sum_cr = sum((x.dr for x in rows), _ZERO), sum((x.cr for x in rows), _ZERO)
    if total != (sum_dr, sum_cr):
        errs.add(file, None, f"TOTAL row (Dr {total[0]} / Cr {total[1]}) does not equal the sum of the lines (Dr {sum_dr} / Cr {sum_cr})")
    if total[0] != total[1]:
        errs.add(file, None, f"the expected trial balance is not balanced: Dr {total[0]} vs Cr {total[1]}")
    missing = sorted(set(ledgers) - seen)
    if rows and missing:
        errs.add(file, None, f"every ledger must appear (use 0.00 / 0.00 for a nil balance); missing: {', '.join(missing)}")
    return rows, total


# --------------------------------------------------------------------------- public


def load_pack(folder: Path) -> Pack:
    """Load and validate a pack folder. Raises PackError listing every problem found."""
    folder = Path(folder)
    errs = _Collector()
    if not folder.is_dir():
        raise PackError([PackIssue(str(folder), None, "folder does not exist")])

    client = _load_client(folder, errs)
    ledgers = _load_ledgers(folder, errs)
    ledger_by_name = {x.name: x for x in ledgers}
    names = set(ledger_by_name)
    vouchers = _load_vouchers(folder, client, names, errs)
    invalid = _load_invalid(folder, errs)
    balances = _load_balances(folder, names, errs)
    tb_rows, tb_total = _load_tb(folder, ledger_by_name, balances, errs)

    signoff = folder / "SIGNOFF.md"
    if not signoff.is_file():
        errs.add("SIGNOFF.md", None, "file is missing")

    if errs.issues:
        raise PackError(errs.issues)
    return Pack(
        folder, client, tuple(ledgers), tuple(vouchers), tuple(invalid),
        tuple(balances), tuple(tb_rows), tb_total,
    )


def _side(net: Decimal) -> str:
    """'Dr 100.00' / 'Cr 100.00' / 'nil' for a signed balance (debit positive)."""
    if net > 0:
        return f"Dr {net}"
    if net < 0:
        return f"Cr {-net}"
    return "nil"


def balance_warnings(pack: Pack) -> list[str]:
    """WARNINGS ONLY: recompute closing balances with plain Decimal sums and compare with the expected file.

    closing = (opening_dr - opening_cr) + sum(debit - credit) of vouchers.csv  (invalid_vouchers.csv is ignored).
    Returns one line per ledger whose expected closing balance differs. Never raises and never modifies a pack
    file: the expected answers are the accountants' to decide, a difference only tells them to look again.
    """
    net = {x.name: x.opening_dr - x.opening_cr for x in pack.ledgers}
    for line in pack.vouchers:
        net[line.ledger_name] += line.debit - line.credit
    warnings = []
    for expected in pack.expected_balances:
        want = expected.closing_dr - expected.closing_cr
        got = net[expected.ledger_name]
        if want != got:
            warnings.append(
                f"expected_ledger_balances.csv: '{expected.ledger_name}' is {_side(want)} there, but "
                f"ledgers.csv + vouchers.csv give {_side(got)} (difference {abs(want - got)})"
            )
    return warnings
