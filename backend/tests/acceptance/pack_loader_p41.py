"""Reads the Phase 4.1 addendum docs/test-packs/phase4-greenfield-contractors-2026/p41 (a second small client, Sunrise Traders).

Same format rules as pack_loader_p4 (2-decimal amounts, YYYY-MM-DD dates). Nothing here imports the accounting engine or a service.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import PackFormatError, parse_amount, parse_date, read_rows
from pack_loader_p4 import parse_rate

EXPECTED_FILES = ("expected_items", "expected_lines")


@dataclass(frozen=True)
class VoucherRec41:
    ref_id: str
    date: date
    voucher_type: str
    reference_no: str | None
    narration: str
    party_ledger: str
    counter_ledger: str
    amount: Decimal  # the amount on which the nature applies (for a GST invoice: the value WITHOUT GST the accountant types)
    nature_key: str
    credit_date: date | None
    payment_date: date | None
    cert_ref: str | None
    set_pan: str | None  # the deductee's PAN is confirmed (status valid) just before this voucher
    gst_invoice_value: Decimal | None  # set = a GST purchase invoice of this taxable value (one item, HSN 8415, intra-state)


@dataclass(frozen=True)
class PackP41:
    folder: Path
    client: dict
    ledgers: list[dict]
    gst_roles: list[dict]
    roles: list[dict]
    deductees: list[dict]
    certificates: list[dict]
    vouchers: list[VoucherRec41]
    wrong_cases: list[dict]
    expected: dict[str, list[dict]]


def _opt_date(text: str, where: str) -> date | None:
    return parse_date(text, where) if text else None


def build_vouchers(rows: list[dict]) -> list[VoucherRec41]:
    seen: set[str] = set()
    out = []
    for r in rows:
        where = f"p41 voucher {r['ref_id']}: "
        if r["ref_id"] in seen:
            raise PackFormatError(f"{where}reference used twice")
        seen.add(r["ref_id"])
        out.append(VoucherRec41(
            r["ref_id"], parse_date(r["date"], where), r["voucher_type"], r["reference_no"] or None, r["narration"], r["party_ledger"],
            r["counter_ledger"], parse_amount(r["amount"], where), r["nature_key"], _opt_date(r["credit_date"], where),
            _opt_date(r["payment_date"], where), r["cert_ref"] or None, r["set_pan"] or None,
            parse_amount(r["gst_invoice_value"], where) if r["gst_invoice_value"] else None))
    return sorted(out, key=lambda v: v.date)  # stable: the order of posting is the order of dates


def load_pack_p41(folder: Path) -> PackP41:
    client = yaml.safe_load((folder / "client.yaml").read_text(encoding="utf-8"))
    for key in ("name", "entity_type", "business_type", "gst_type", "fy_start", "second_fy_start", "tan", "gstin",
                "registration_effective_from", "individual_huf_not_tax_audited_2026_27", "invoice_supplier_gstin"):
        if key not in client:
            raise PackFormatError(f"p41/client.yaml: '{key}' is missing")
    for key in ("fy_start", "second_fy_start", "registration_effective_from"):
        if isinstance(client[key], str):
            client[key] = parse_date(client[key], "p41/client.yaml: ")
    certificates = read_rows(folder, "certificates.csv")
    for c in certificates:
        where = f"p41 certificate {c['cert_ref']}: "
        c["rate"], c["max_amount"] = parse_rate(c["rate"], where), parse_amount(c["max_amount"], where)
        c["valid_from"], c["valid_to"] = parse_date(c["valid_from"], where), parse_date(c["valid_to"], where)
    return PackP41(
        folder, client, read_rows(folder, "ledgers.csv"), read_rows(folder, "gst_roles.csv"), read_rows(folder, "ledger_roles.csv"),
        read_rows(folder, "deductees.csv"), certificates, build_vouchers(read_rows(folder, "vouchers.csv")),
        read_rows(folder, "wrong_cases.csv"), {name: read_rows(folder, name + ".csv") for name in EXPECTED_FILES},
    )
