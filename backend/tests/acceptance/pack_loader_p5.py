"""Reads the Phase 5 (Inventory) pack docs/test-packs/phase5-* as typed plain rows.

Format rules follow the Phase 1-4 loaders (2-decimal amounts, YYYY-MM-DD dates); quantities have at most 3 decimals (the wrong-case
file keeps its quantity as raw text on purpose: one case types 4 decimals). Nothing here imports the accounting engine or a service,
and no file of the pack is ever written.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import PackFormatError, group_by_ref, parse_amount, parse_date, read_rows

_QTY = re.compile(r"^\d+\.\d{3}$")

EXPECTED_FILES = (
    "expected_vouchers", "expected_register", "expected_register_totals", "expected_closing_stock", "expected_closing_totals",
    "expected_by_godown", "expected_movement_cost",
)
METHODS = ("fifo", "wa_periodic", "wa_moving")


@dataclass(frozen=True)
class ItemLine5:
    item_name: str
    quantity: Decimal
    unit_rate: Decimal
    godown_name: str | None
    item_ledger: str


@dataclass(frozen=True)
class VoucherRec5:
    ref_id: str
    date: date
    voucher_type: str
    narration: str
    reference_no: str | None
    party_ledger: str
    counterparty_gstin: str
    original_ref: str | None
    note_reason: str | None
    items: tuple[ItemLine5, ...]


@dataclass(frozen=True)
class JournalRec5:
    ref_id: str
    journal_type: str
    date: date
    narration: str
    reason_code: str | None
    reason_note: str | None
    item_name: str
    from_godown_name: str
    to_godown_name: str | None
    quantity: Decimal


@dataclass(frozen=True)
class PackP5:
    folder: Path
    client: dict
    ledgers: list[dict]
    roles: list[dict]
    godowns: list[str]
    items: list[dict]
    opening: list[dict]
    vouchers: list[VoucherRec5]
    journals: list[JournalRec5]
    nrv: list[dict]
    wrong_cases: list[dict]
    expected: dict[str, list[dict]]


def parse_qty(text: str, where: str = "") -> Decimal:
    text = text.strip()
    if not _QTY.match(text):
        raise PackFormatError(f"{where}quantity '{text}' must be a plain number with exactly 3 decimals")
    return Decimal(text)


def build_vouchers(rows: list[dict]) -> list[VoucherRec5]:
    """One voucher per ref (one row per item line), sorted by date (stable)."""
    out = []
    for ref, group in group_by_ref(rows):
        head = group[0]
        where = f"voucher {ref}: "
        for r in group:
            for col in ("date", "voucher_type", "narration", "reference_no", "party_ledger", "original_ref"):
                if r[col] != head[col]:
                    raise PackFormatError(f"{where}'{col}' differs between its item lines")
        items = tuple(
            ItemLine5(r["item_name"], parse_qty(r["quantity"], where), parse_amount(r["unit_rate"], where), r["godown_name"] or None,
                      r["item_ledger"])
            for r in group)
        out.append(VoucherRec5(
            ref, parse_date(head["date"], where), head["voucher_type"], head["narration"], head["reference_no"] or None,
            head["party_ledger"], head["counterparty_gstin"], head["original_ref"] or None, head["note_reason"] or None, items))
    return sorted(out, key=lambda v: v.date)


def build_journals(rows: list[dict]) -> list[JournalRec5]:
    out = []
    for r in rows:
        where = f"journal {r['ref_id']}: "
        out.append(JournalRec5(
            r["ref_id"], r["journal_type"], parse_date(r["date"], where), r["narration"], r["reason_code"] or None,
            r["reason_note"] or None, r["item_name"], r["from_godown_name"], r["to_godown_name"] or None,
            parse_qty(r["quantity"], where)))
    return sorted(out, key=lambda j: j.date)


def load_pack_p5(folder: Path) -> PackP5:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "registration_gstin", "place_of_supply", "report_from",
                "report_to", "nrv_as_on", "negative_stock_mode", "methods"):
        if key not in client:
            raise PackFormatError(f"client.yaml: '{key}' is missing")
    for key in ("fy_start", "report_from", "report_to", "nrv_as_on"):
        if isinstance(client[key], str):
            client[key] = parse_date(client[key], "client.yaml: ")
    if list(client["methods"]) != list(METHODS):
        raise PackFormatError(f"client.yaml: methods must be {list(METHODS)}")
    opening = read_rows(folder, "opening.csv")
    for r in opening:
        r["quantity"] = parse_qty(r["quantity"], f"opening {r['item_name']}: ")
        r["value"] = parse_amount(r["value"], f"opening {r['item_name']}: ")
    nrv = read_rows(folder, "nrv.csv")
    for r in nrv:
        r["as_on_date"] = parse_date(r["as_on_date"], f"nrv {r['item_name']}: ")
        r["nrv_per_unit"] = parse_amount(r["nrv_per_unit"], f"nrv {r['item_name']}: ")
    return PackP5(
        folder, client, read_rows(folder, "ledgers.csv"), read_rows(folder, "ledger_roles.csv"),
        [r["godown_name"] for r in read_rows(folder, "godowns.csv")], read_rows(folder, "items.csv"), opening,
        build_vouchers(read_rows(folder, "vouchers.csv")), build_journals(read_rows(folder, "journals.csv")), nrv,
        read_rows(folder, "wrong_cases.csv"), {name: read_rows(folder, name + ".csv") for name in EXPECTED_FILES})
