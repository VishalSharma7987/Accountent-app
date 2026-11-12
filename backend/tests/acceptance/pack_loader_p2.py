"""Reads the Phase 2 pack (docs/test-packs/abc-traders-phase2-jun-2026) as typed plain rows.

Format rules are the Phase 1 ones (2-decimal amounts, YYYY-MM-DD dates). The Phase 1 loader is not used because it
insists on files this pack does not have (invalid_vouchers.csv, expected_ledger_balances.csv). Nothing here imports the
accounting engine or a service, and no file of the pack is ever written.
"""

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

_AMOUNT = re.compile(r"^\d+\.\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PackFormatError(Exception):
    pass


def parse_amount(text: str, where: str = "") -> Decimal:
    """Plain number with exactly 2 decimals (no commas, no sign)."""
    text = text.strip()
    if not _AMOUNT.match(text):
        raise PackFormatError(f"{where}amount '{text}' must be a plain number with 2 decimals")
    return Decimal(text)


def parse_date(text: str, where: str = "") -> date:
    text = text.strip()
    if not _DATE.match(text):
        raise PackFormatError(f"{where}date '{text}' must be YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise PackFormatError(f"{where}date '{text}' is not a real date") from None


def parse_bool(text: str, where: str = "") -> bool:
    value = text.strip().lower()
    if value in ("true", "yes"):
        return True
    if value in ("false", "no"):
        return False
    raise PackFormatError(f"{where}flag '{text}' must be true or false")


def read_rows(folder: Path, name: str) -> list[dict[str, str]]:
    """Every data row of a csv as {column: stripped text}; blank lines are skipped."""
    path = folder / name
    if not path.is_file():
        raise PackFormatError(f"{name}: file is missing")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
            if any((v or "").strip() for v in row.values())
        ]


def group_by_ref(rows: list[dict], key: str = "ref_id") -> list[tuple[str, list[dict]]]:
    """Rows of one voucher together, vouchers in order of first appearance."""
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row[key]].append(row)
    return list(out.items())


@dataclass(frozen=True)
class Alloc:
    kind: str
    amount: str  # 2-decimal text, as the services take it
    bill_ref: str | None
    due_date: date | None


@dataclass(frozen=True)
class Line:
    ledger_name: str
    debit: Decimal
    credit: Decimal
    allocations: tuple[Alloc, ...] = ()


@dataclass(frozen=True)
class VoucherRec:
    ref_id: str
    date: date
    voucher_type: str
    narration: str
    reference_no: str | None
    party_ledger: str | None
    lines: tuple[Line, ...]
    expected_rule_id: str | None = None
    expected_message_contains: str | None = None
    goods_received_date: date | None = None  # optional column of vouchers.csv (Purchase only)


def load_allocations(rows: list[dict]) -> dict[tuple[str, int], tuple[Alloc, ...]]:
    """(ref_id, 1-based line_no) -> allocations, in file order."""
    out: dict[tuple[str, int], list[Alloc]] = defaultdict(list)
    for n, r in enumerate(rows, start=2):
        where = f"allocations row {n}: "
        out[(r["ref_id"], int(r["line_no"]))].append(Alloc(
            r["kind"], f"{parse_amount(r['amount'], where):.2f}", r["bill_ref"] or None,
            parse_date(r["due_date"], where) if r["due_date"] else None,
        ))
    return {k: tuple(v) for k, v in out.items()}


def build_vouchers(rows: list[dict], allocations: dict[tuple[str, int], tuple[Alloc, ...]]) -> list[VoucherRec]:
    """Voucher records from csv rows, sorted by date (file order kept inside one date)."""
    out = []
    for ref, group in group_by_ref(rows):
        head = group[0]
        where = f"voucher {ref}: "
        lines = tuple(
            Line(r["ledger_name"], parse_amount(r["debit"], where), parse_amount(r["credit"], where),
                 allocations.get((ref, n), ()))
            for n, r in enumerate(group, start=1)
        )
        for r in group:
            for col in ("date", "voucher_type", "narration", "reference_no", "party_ledger"):
                if r[col] != head[col]:
                    raise PackFormatError(f"{where}'{col}' differs between its lines")
        out.append(VoucherRec(
            ref, parse_date(head["date"], where), head["voucher_type"], head["narration"],
            head["reference_no"] or None, head["party_ledger"] or None, lines,
            head.get("expected_rule_id") or None, head.get("expected_message_contains") or None,
            parse_date(head["goods_received_date"], where) if head.get("goods_received_date") else None,
        ))
    return sorted(out, key=lambda v: v.date)  # sorted() is stable


@dataclass(frozen=True)
class PartyRec:
    ledger_name: str
    gstin: str | None
    pan: str | None
    state_code: str | None
    credit_days: int
    msme_category: str
    udyam_no: str | None
    msme_written_agreement: bool
    bill_wise: bool
    ref_id: str | None = None
    expected_rule_id: str | None = None
    expected_message_contains: str | None = None
    msme_activity: str | None = None
    udyam_registration_date: date | None = None
    msme_agreed_days: int | None = None


def build_party(r: dict) -> PartyRec:
    where = f"party {r['ledger_name']}: "
    return PartyRec(
        r["ledger_name"], r["gstin"] or None, r["pan"] or None, r["state_code"] or None,
        int(r["credit_days"] or 0), r["msme_category"] or "none", r["udyam_no"] or None,
        parse_bool(r["msme_written_agreement"] or "false", where), parse_bool(r["bill_wise"] or "true", where),
        r.get("ref_id") or None, r.get("expected_rule_id") or None, r.get("expected_message_contains") or None,
        r.get("activity") or None,
        parse_date(r["udyam_registration_date"], where) if r.get("udyam_registration_date") else None,
        int(r["msme_agreed_days"]) if r.get("msme_agreed_days") else None,
    )


@dataclass(frozen=True)
class PackP2:
    folder: Path
    client: dict
    ledgers: list[dict]
    parties: list[PartyRec]
    opening_bills: list[dict]
    bank_opening_items: list[dict]
    vouchers: list[VoucherRec]
    reversals: list[dict]
    wrong_vouchers: list[VoucherRec]
    wrong_parties: list[PartyRec]
    bank_format: dict
    expected: dict[str, list[dict]]


EXPECTED_FILES = (
    "expected_trial_balance", "expected_outstanding_receivable", "expected_outstanding_payable",
    "expected_ageing", "expected_cash_book", "expected_msme_due", "expected_matches", "expected_brs",
    "expected_bank_only_drafts",
)


def load_pack_p2(folder: Path) -> PackP2:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "pack_end_date"):
        if key not in client:
            raise PackFormatError(f"client.yaml: '{key}' is missing")
    for key in ("fy_start", "pack_end_date"):
        if isinstance(client[key], str):
            client[key] = parse_date(client[key], "client.yaml: ")
    allocations = load_allocations(read_rows(folder, "allocations.csv"))
    wrong_allocations = load_allocations(read_rows(folder, "wrong_allocations.csv"))
    return PackP2(
        folder, client,
        [{**r, "opening_dr": parse_amount(r["opening_dr"]), "opening_cr": parse_amount(r["opening_cr"])}
         for r in read_rows(folder, "ledgers.csv")],
        [build_party(r) for r in read_rows(folder, "parties.csv")],
        read_rows(folder, "opening_bills.csv"),
        read_rows(folder, "bank_opening_items.csv"),
        build_vouchers(read_rows(folder, "vouchers.csv"), allocations),
        read_rows(folder, "reversals.csv"),
        build_vouchers(read_rows(folder, "wrong_vouchers.csv"), wrong_allocations),
        [build_party(r) for r in read_rows(folder, "wrong_parties.csv")],
        json.loads((folder / "bank_format.json").read_text(encoding="utf-8")),
        {name: read_rows(folder, name + ".csv") for name in EXPECTED_FILES},
    )
