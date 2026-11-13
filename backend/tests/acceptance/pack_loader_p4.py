"""Reads the Phase 4 (TDS / TCS) pack docs/test-packs/phase4-* as typed plain rows.

Format rules follow the Phase 1-3 loaders (2-decimal amounts, YYYY-MM-DD dates). Nothing here imports the accounting engine
or a service, and no file of the pack is ever written. The 26AS statement is kept as raw bytes: the tool's own importer reads it
(its layout is UNVERIFIED against a real TRACES file, see backend/tests/fixtures/tds26as/README.md).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import PackFormatError, parse_amount, parse_date, read_rows

_RATE = re.compile(r"^\d+(\.\d{1,4})?$")

EXPECTED_FILES = (
    "expected_vouchers", "expected_items", "expected_ledger_balances", "expected_register", "expected_by_deductee",
    "expected_position", "expected_challans", "expected_interest", "expected_return_rows", "expected_return_totals",
    "expected_certificates", "expected_recon", "expected_recon_summary", "expected_rule_status",
)


@dataclass(frozen=True)
class VoucherRec:
    ref_id: str
    date: date
    voucher_type: str
    reference_no: str | None
    narration: str
    party_ledger: str
    counter_ledger: str
    amount: Decimal
    nature_key: str
    credit_date: date | None
    payment_date: date | None
    cert_ref: str | None


@dataclass(frozen=True)
class ChallanRec:
    ref_id: str
    kind: str
    fy: str  # first | second
    quarter: int
    bsr_code: str
    deposit_date: date
    serial_no: str
    tax: Decimal
    interest: Decimal
    fee: Decimal
    allocations: tuple[tuple[str, Decimal], ...]  # (voucher ref, amount)


@dataclass(frozen=True)
class PackP4:
    folder: Path
    client: dict
    ledgers: list[dict]
    deductees: list[dict]
    certificates: list[dict]
    roles: list[dict]
    vouchers: list[VoucherRec]
    challans: list[ChallanRec]
    statement: bytes
    links: list[dict]
    wrong_cases: list[dict]
    expected: dict[str, list[dict]]


def parse_rate(text: str, where: str = "") -> Decimal:
    text = text.strip()
    if not _RATE.match(text):
        raise PackFormatError(f"{where}rate '{text}' must be a plain number with up to 4 decimals")
    return Decimal(text)


def _opt_date(text: str, where: str) -> date | None:
    return parse_date(text, where) if text else None


def build_vouchers(rows: list[dict]) -> list[VoucherRec]:
    """One row = one voucher with one TDS / TCS item; sorted by date (stable), so numbers are assigned in date order."""
    seen: set[str] = set()
    out = []
    for r in rows:
        where = f"voucher {r['ref_id']}: "
        if r["ref_id"] in seen:
            raise PackFormatError(f"{where}reference used twice")
        seen.add(r["ref_id"])
        out.append(VoucherRec(
            r["ref_id"], parse_date(r["date"], where), r["voucher_type"], r["reference_no"] or None, r["narration"],
            r["party_ledger"], r["counter_ledger"], parse_amount(r["amount"], where), r["nature_key"],
            _opt_date(r["credit_date"], where), _opt_date(r["payment_date"], where), r["cert_ref"] or None))
    return sorted(out, key=lambda v: v.date)


def build_challans(rows: list[dict]) -> list[ChallanRec]:
    out = []
    for r in rows:
        where = f"challan {r['ref_id']}: "
        allocations = []
        for part in r["allocations"].split("+"):
            ref, _, amount = part.partition(":")
            allocations.append((ref.strip(), parse_amount(amount, where)))
        out.append(ChallanRec(
            r["ref_id"], r["kind"], r["fy"], int(r["quarter"]), r["bsr_code"], parse_date(r["deposit_date"], where), r["serial_no"],
            parse_amount(r["tax"], where), parse_amount(r["interest"], where), parse_amount(r["fee"], where), tuple(allocations)))
    return out


def load_pack_p4(folder: Path) -> PackP4:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "second_fy_start", "tan", "partners",
                "balances_as_on_first_year", "balances_as_on_second_year", "interest_as_on"):
        if key not in client:
            raise PackFormatError(f"client.yaml: '{key}' is missing")
    for key in ("fy_start", "second_fy_start", "balances_as_on_first_year", "balances_as_on_second_year", "interest_as_on"):
        if isinstance(client[key], str):
            client[key] = parse_date(client[key], "client.yaml: ")
    certificates = read_rows(folder, "certificates.csv")
    for c in certificates:
        c["rate"] = parse_rate(c["rate"], f"certificate {c['cert_ref']}: ")
        c["max_amount"] = parse_amount(c["max_amount"], f"certificate {c['cert_ref']}: ")
        c["valid_from"] = parse_date(c["valid_from"], f"certificate {c['cert_ref']}: ")
        c["valid_to"] = parse_date(c["valid_to"], f"certificate {c['cert_ref']}: ")
    links = read_rows(folder, "links.csv")
    for link in links:
        link["row_no"] = int(link["row_no"])
    return PackP4(
        folder, client, read_rows(folder, "ledgers.csv"), read_rows(folder, "deductees.csv"), certificates,
        read_rows(folder, "ledger_roles.csv"), build_vouchers(read_rows(folder, "vouchers.csv")),
        build_challans(read_rows(folder, "challans.csv")), (folder / "statement_26as_fy2026-27.csv").read_bytes(), links,
        read_rows(folder, "wrong_cases.csv"), {name: read_rows(folder, name + ".csv") for name in EXPECTED_FILES},
    )
