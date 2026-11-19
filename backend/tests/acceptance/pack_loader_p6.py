"""Reads the Phase 6 pack docs/test-packs/phase6-* (period-end and final accounts) as typed plain rows.

The pack folder holds one sub-folder per client (proprietor, partnership, company) with the same file names. Format rules follow
the Phase 1-5 loaders (2-decimal amounts, YYYY-MM-DD dates); rates have 4 decimals. The voucher file has the Phase 2 layout and is read
with the Phase 2 loader. Nothing here imports the accounting engine or a service, and no file of the pack is ever written.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import (
    PackFormatError,
    VoucherRec,
    build_vouchers,
    parse_amount,
    parse_date,
    read_rows,
)

MARKER = "phase6.yaml"  # the file that tells the Phase 1-5 runners to leave this folder alone
CLIENTS = ("proprietor", "partnership", "company")
_SIGNED = re.compile(r"^-?\d+\.\d{2}$")
_RATE = re.compile(r"^\d+\.\d{4}$")

# expected files (a client may not have every one): name -> amount columns (2-decimal text, may be negative)
EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    "expected_trial_balance": ("debit", "credit"),
    "expected_adjustments": ("debit", "credit"),
    "expected_depreciation": ("opening_accumulated", "depreciation", "closing_accumulated"),
    "expected_register": ("opening_cost", "additions", "disposals", "closing_cost", "opening_accumulated", "depreciation_for_year",
                          "closing_accumulated", "net_block"),
    "expected_it_blocks": ("opening_wdv", "additions_full", "additions_half", "disposals", "depreciation", "closing_wdv"),
    "expected_statements": ("amount",),
    "expected_cash_flow": ("amount",),
    "expected_closing": ("debit", "credit"),
    "expected_carried": ("debit", "credit"),
    "expected_carried_it": ("opening_wdv",),
    "expected_sch3": ("amount",),
    "expected_notes": ("amount",),
}


@dataclass(frozen=True)
class AdjustmentRec:
    ref_id: str
    adj_type: str
    as_on_date: date
    amount: Decimal | None
    debit_ledger: str
    credit_ledger: str
    party_ledger: str
    rate_percent: Decimal | None
    partner: str
    months: int | None
    basis_note: str


@dataclass(frozen=True)
class ClientPack6:
    key: str
    folder: Path
    client: dict
    ledgers: list[dict]
    vouchers: list[VoucherRec]
    adjustments: list[AdjustmentRec]
    assets: list[dict]
    events: list[dict]
    it_openings: list[dict]
    closing_stock: list[dict]
    classification: list[dict]
    partners: list[dict]
    partner_terms: list[dict]
    expected: dict[str, list[dict]]


@dataclass(frozen=True)
class PackP6:
    folder: Path
    meta: dict
    clients: dict[str, ClientPack6]


def _optional(folder: Path, name: str) -> list[dict]:
    return read_rows(folder, name) if (folder / name).is_file() else []


def _signed(text: str, where: str) -> Decimal:
    text = text.strip()
    if not _SIGNED.match(text):
        raise PackFormatError(f"{where}amount '{text}' must be a plain number with 2 decimals (a minus sign is allowed)")
    return Decimal(text)


def _rate(text: str, where: str) -> Decimal | None:
    text = text.strip()
    if not text:
        return None
    if not _RATE.match(text):
        raise PackFormatError(f"{where}rate '{text}' must be a plain number with 4 decimals")
    return Decimal(text)


def _opt_amount(text: str, where: str) -> Decimal | None:
    return parse_amount(text, where) if text.strip() else None


def build_adjustments(rows: list[dict]) -> list[AdjustmentRec]:
    out = []
    for r in rows:
        where = f"adjustment {r['ref_id']}: "
        months = r["months"].strip()
        out.append(AdjustmentRec(
            r["ref_id"], r["adj_type"], parse_date(r["as_on_date"], where), _opt_amount(r["amount"], where), r["debit_ledger"],
            r["credit_ledger"], r["party_ledger"], _rate(r["rate_percent"], where), r["partner"], int(months) if months else None,
            r["basis_note"]))
    return out


def _check_expected(name: str, rows: list[dict]) -> list[dict]:
    for n, r in enumerate(rows, start=2):
        for col in EXPECTED_FILES[name]:
            if col in r and r[col] != "":
                _signed(r[col], f"{name}.csv row {n}: ")
    return rows


def load_client(folder: Path) -> ClientPack6:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "years", "close_years"):
        if key not in client:
            raise PackFormatError(f"{folder.name}/client.yaml: '{key}' is missing")
    if isinstance(client["fy_start"], str):
        client["fy_start"] = parse_date(client["fy_start"], "client.yaml: ")
    ledgers = read_rows(folder, "ledgers.csv")
    for r in ledgers:
        where = f"ledger {r['ledger_name']}: "
        r["opening_dr"] = parse_amount(r["opening_dr"], where)
        r["opening_cr"] = parse_amount(r["opening_cr"], where)
    events = read_rows(folder, "asset_events.csv") if (folder / "asset_events.csv").is_file() else []
    for r in events:
        where = f"asset event {r['asset_no']}: "
        r["event_date"] = parse_date(r["event_date"], where)
        r["put_to_use_date"] = parse_date(r["put_to_use_date"], where) if r["put_to_use_date"] else None
        r["amount"] = parse_amount(r["amount"], where)
        r["accumulated_dep_bf"] = parse_amount(r["accumulated_dep_bf"], where)
    assets = _optional(folder, "assets.csv")
    for r in assets:
        r["residual"] = parse_amount(r["residual"], f"asset {r['asset_no']}: ")
    openings = _optional(folder, "it_openings.csv")
    for r in openings:
        r["opening_wdv"] = parse_amount(r["opening_wdv"], f"IT opening {r['block_key']}: ")
    stock = _optional(folder, "closing_stock.csv")
    for r in stock:
        where = f"closing stock {r['fy']}: "
        r["as_on_date"] = parse_date(r["as_on_date"], where)
        r["cost_value"] = _opt_amount(r["cost_value"], where)
        r["write_down"] = _opt_amount(r["write_down"], where)
    terms = _optional(folder, "partner_terms.csv")
    for r in terms:
        where = f"partner terms {r['partner']}: "
        for col in ("profit_share_percent", "interest_on_capital_rate", "interest_on_drawings_rate"):
            r[col] = _rate(r[col], where)
        r["remuneration_annual"] = _opt_amount(r["remuneration_annual"], where)
    expected = {name: _check_expected(name, _optional(folder, name + ".csv")) for name in EXPECTED_FILES}
    return ClientPack6(
        folder.name, folder, client, ledgers, build_vouchers(read_rows(folder, "vouchers.csv"), {}),
        build_adjustments(_optional(folder, "adjustments.csv")), assets, events, openings, stock, _optional(folder, "classification.csv"),
        _optional(folder, "partners.csv"), terms, expected)


def load_pack_p6(folder: Path) -> PackP6:
    meta = yaml.safe_load((folder / MARKER).read_text(encoding="utf-8"))
    if list(meta.get("clients", [])) != list(CLIENTS):
        raise PackFormatError(f"{MARKER}: clients must be {list(CLIENTS)}")
    return PackP6(folder, meta, {key: load_client(folder / key) for key in CLIENTS})
