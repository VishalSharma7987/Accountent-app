"""Reads the Phase 3 (GST) pack docs/test-packs/phase3-* as typed plain rows.

Format rules follow the Phase 1/2 loaders (2-decimal amounts, YYYY-MM-DD dates). Nothing here imports the accounting
engine or a service, and no file of the pack is ever written. The GSTR-2B files are kept as raw bytes: the tool's own
importer reads them (their shape is UNVERIFIED against the portal, see tests/fixtures/gstr2b/README.md).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import (
    PackFormatError,
    group_by_ref,
    parse_amount,
    parse_bool,
    parse_date,
    read_rows,
)

_QTY = re.compile(r"^\d+(\.\d{1,3})?$")

EXPECTED_FILES = (
    "expected_invoices", "expected_invoice_items", "expected_ledger_balances", "expected_itc", "expected_reconciliation",
    "expected_reconciliation_totals", "expected_apply2b", "expected_gstr1", "expected_gstr1_documents", "expected_gstr3b",
    "expected_tieout", "expected_exposure", "expected_reversals", "expected_composition", "expected_rule_status",
    "expected_register_tie",
)


@dataclass(frozen=True)
class ItemRec:
    item_name: str
    hsn_sac: str
    uqc: str | None
    quantity: Decimal
    unit_rate: Decimal
    discount: Decimal
    item_ledger: str
    rcm_category: str | None
    itc_category: str | None


@dataclass(frozen=True)
class InvoiceRec:
    ref_id: str
    date: date
    voucher_type: str
    narration: str
    reference_no: str | None
    party_ledger: str
    document_kind: str
    supply_category: str
    place_of_supply: str
    invoice_date: date
    original_invoice_no: str | None
    original_invoice_date: date | None
    note_reason: str | None
    items: tuple[ItemRec, ...]


@dataclass(frozen=True)
class PackP3:
    folder: Path
    client: dict
    composition: dict
    ledgers: list[dict]
    parties: list[dict]
    registrations: list[dict]
    roles: list[dict]
    items: list[dict]
    invoices: list[InvoiceRec]
    payments: list[tuple[str, list[dict]]]
    evidence: list[dict]
    claims: list[dict]
    wrong_cases: list[dict]
    gstr2b: dict[str, bytes]
    expected: dict[str, list[dict]]


def parse_quantity(text: str, where: str = "") -> Decimal:
    text = text.strip()
    if not _QTY.match(text):
        raise PackFormatError(f"{where}quantity '{text}' must be a plain number with up to 3 decimals")
    return Decimal(text)


def build_invoices(rows: list[dict]) -> list[InvoiceRec]:
    """Invoices from csv rows (one row per item line), sorted by date; file order is kept inside one date."""
    out = []
    for ref, group in group_by_ref(rows):
        head = group[0]
        where = f"voucher {ref}: "
        for r in group:
            for col in ("date", "voucher_type", "narration", "reference_no", "party_ledger", "document_kind",
                        "supply_category", "place_of_supply", "invoice_date"):
                if r[col] != head[col]:
                    raise PackFormatError(f"{where}'{col}' differs between its item lines")
        items = tuple(
            ItemRec(r["item_name"], r["hsn_sac"], r["uqc"] or None, parse_quantity(r["quantity"], where),
                    parse_amount(r["unit_rate"], where), parse_amount(r["discount"], where), r["item_ledger"],
                    r["rcm_category"] or None, r["itc_category"] or None)
            for r in group
        )
        out.append(InvoiceRec(
            ref, parse_date(head["date"], where), head["voucher_type"], head["narration"], head["reference_no"] or None,
            head["party_ledger"], head["document_kind"], head["supply_category"], head["place_of_supply"],
            parse_date(head["invoice_date"], where), head["original_invoice_no"] or None,
            parse_date(head["original_invoice_date"], where) if head["original_invoice_date"] else None,
            head["note_reason"] or None, items))
    return sorted(out, key=lambda v: v.date)  # sorted() is stable


def load_pack_p3(folder: Path) -> PackP3:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "pack_end_date", "return_period",
                "exposure_as_on", "claim_period", "registration_gstin"):
        if key not in client:
            raise PackFormatError(f"client.yaml: '{key}' is missing")
    for key in ("fy_start", "pack_end_date", "return_period", "exposure_as_on", "claim_period"):
        if isinstance(client[key], str):
            client[key] = parse_date(client[key], "client.yaml: ")
    composition = yaml.safe_load((folder / "composition_client.yaml").read_text(encoding="utf-8"))
    for key in ("fy_start", "quarter_start"):
        if isinstance(composition[key], str):
            composition[key] = parse_date(composition[key], "composition_client.yaml: ")
    reg = composition["registration"]
    if isinstance(reg["effective_from"], str):
        reg["effective_from"] = parse_date(reg["effective_from"], "composition_client.yaml: ")
    ledgers = read_rows(folder, "ledgers.csv")
    for r in ledgers:
        r["opening_dr"], r["opening_cr"] = parse_amount(r["opening_dr"]), parse_amount(r["opening_cr"])
    parties = read_rows(folder, "parties.csv")
    for p in parties:
        p["bill_wise"] = parse_bool(p["bill_wise"], f"party {p['ledger_name']}: ")
    registrations = read_rows(folder, "gst_registrations.csv")
    for r in registrations:
        r["effective_from"] = parse_date(r["effective_from"], "gst_registrations.csv: ")
    payments = []
    for ref, group in group_by_ref(read_rows(folder, "payments.csv")):
        for r in group:
            r["amount"] = parse_amount(r["amount"], f"payment {ref}: ")
        payments.append((ref, group))
    evidence = read_rows(folder, "itc_evidence.csv")
    for r in evidence:
        r["tax_document_held"] = parse_bool(r["tax_document_held"])
        r["goods_services_received"] = parse_bool(r["goods_services_received"])
        r["received_date"] = parse_date(r["received_date"], f"evidence {r['ref_id']}: ")
    claims = read_rows(folder, "itc_claims.csv")
    for r in claims:
        r["claimed_in_period"] = parse_date(r["claimed_in_period"], f"claim {r['ref_id']}: ")
    return PackP3(
        folder, client, composition, ledgers, parties, registrations, read_rows(folder, "ledger_roles.csv"),
        read_rows(folder, "items.csv"), build_invoices(read_rows(folder, "vouchers.csv")), payments, evidence, claims,
        read_rows(folder, "wrong_cases.csv"),
        {p.name: p.read_bytes() for p in sorted(folder.glob("gstr2b_*.json"))},
        {name: read_rows(folder, name + ".csv") for name in EXPECTED_FILES},
    )
