"""Phase 4.1: TDS on a voucher entered in GST invoice mode (a purchase invoice with the `gst` block AND the `tds` block).

The base of the tax is the invoice value WITHOUT GST (T-18); the GST lines are unchanged; the TDS payable line is added and
the supplier's credit line is reduced by the tax; G-26 and T-13 still pass at approve / post. Needs migrations 0012-0015 and
seeds 0005-0011 in the test schema. Rates come from the seeded rows: HSN 8415 is 18% from 22-09-2025 (example rule row, pending);
contractor 2% for a company with a valid PAN above the single payment limit of 30,000. Expected figures are hand-calculated.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.db import connection, migrate
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import VoucherDraft
from app.engine.tds_types import TdsLineIn
from app.services import client_setup, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import VoucherRuleError

pytestmark = pytest.mark.integration

APRIL_5 = date(2026, 4, 5)
GSTIN_SELF = "27ABCDE1234F1Z0"
GSTIN_SUPPLIER = "27AAACC1234A1ZI"  # the supplier (same state: CGST + SGST)
ROLE_LEDGERS = {
    "output_cgst": "Output CGST", "output_sgst": "Output SGST", "output_igst": "Output IGST",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST",
    "rcm_cgst": "RCM CGST Payable", "rcm_sgst": "RCM SGST Payable", "rcm_igst": "RCM IGST Payable",
}


@dataclass
class World:
    client_id: object
    reg_id: object
    ids: dict


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("GST TDS Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
        )
        c = created.client_id
        ids = dict(created.ledger_ids)
        for name, group in (("Contractor Co", "sundry_creditors"), ("Contract Work", "direct_expenses"), ("TDS Payable", "duties_taxes")):
            ids[name] = client_setup.add_ledger(conn, c, name, group, actor="setup")
        for name in ROLE_LEDGERS.values():
            ids[name] = client_setup.add_ledger(conn, c, name, "duties_taxes", actor="setup")
        reg_id = uuid.uuid4()
        conn.execute(
            text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                 "VALUES (:r, :c, :g, '27', 'regular', '2026-04-01')"),
            {"r": reg_id, "c": c, "g": GSTIN_SELF},
        )
        for role, name in ROLE_LEDGERS.items():
            conn.execute(
                text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                {"r": reg_id, "c": c, "role": role, "l": ids[name]},
            )
        conn.execute(
            text("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (:l, :c, 'AAACC1234A', 'valid', 'company')"),
            {"l": ids["Contractor Co"], "c": c},
        )
        conn.execute(text("INSERT INTO tds_ledger_roles (client_id, role, nature_key, ledger_id) VALUES (:c, 'tds_payable', NULL, :l)"),
                     {"c": c, "l": ids["TDS Payable"]})
        w = World(c, reg_id, ids)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def purchase_invoice(w, tds_amount):
    """Purchase invoice of 1,00,000.00 + 18% GST (intra-state 9,000.00 + 9,000.00) = 1,18,000.00 with a TDS item of `tds_amount`."""
    item = ItemLineIn("Air conditioner works", "8415", D(1), D("100000.00"), D("0.00"), w.ids["Contract Work"], uqc="NOS")
    inv = InvoiceIn(str(w.reg_id), "tax_invoice", "b2b", "27", APRIL_5, (item,), counterparty_gstin=GSTIN_SUPPLIER)
    tds = TdsLineIn(w.ids["Contractor Co"], "contractor", D(tds_amount), None, APRIL_5)
    return VoucherDraft(w.client_id, "purchase", APRIL_5, "Contract bill with GST", "CC/101", w.ids["Contractor Co"], (), gst=inv, tds=(tds,))


def lines_of(conn, voucher_id):
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                 "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id})
    ]


def test_T18_tds_is_on_the_value_without_gst_gst_lines_stay_and_the_party_credit_is_reduced(svc_conn, world):
    result = vouchers.create_draft(svc_conn, purchase_invoice(world, "100000.00"), actor="tester")
    assert result.errors == [], result.errors
    vid = result.voucher_id
    # TDS 2% of 1,00,000.00 (NOT of 1,18,000.00) = 2,000.00; supplier credit 1,18,000.00 - 2,000.00 = 1,16,000.00; GST lines unchanged
    assert lines_of(svc_conn, vid) == [
        ("Contractor Co", D("0.0000"), D("116000.0000")),
        ("Contract Work", D("100000.0000"), D("0.0000")),
        ("Input CGST", D("9000.0000"), D("0.0000")),
        ("Input SGST", D("9000.0000"), D("0.0000")),
        ("TDS Payable", D("0.0000"), D("2000.0000")),
    ]
    item = svc_conn.execute(text("SELECT taxable_base, rate_applied, tds_amount, tds_line_no FROM tds_voucher_items WHERE voucher_id = :v"), {"v": vid}).one()
    assert (item.taxable_base, item.rate_applied, item.tds_amount, item.tds_line_no) == (D("100000.00"), D(2), D("2000.00"), 5)
    vouchers.approve(svc_conn, vid, actor="approver")  # G-26 (invoice lines without the tax line) and T-13 both hold
    assert vouchers.post(svc_conn, vid, actor="poster").startswith("PUR/2026-27/")


def test_T18_a_base_that_includes_the_gst_is_refused(svc_conn, world):
    result = vouchers.create_draft(svc_conn, purchase_invoice(world, "118000.00"), actor="tester")
    assert [e.rule_id for e in result.errors] == ["T-18"]
    assert "1,18,000.00" in result.errors[0].message and "1,00,000.00" in result.errors[0].message


def test_G26_the_party_line_changed_after_building_still_blocks_approval_with_tds_on_the_invoice(svc_conn, world):
    vid = vouchers.create_draft(svc_conn, purchase_invoice(world, "100000.00"), actor="tester").voucher_id
    svc_conn.execute(text("UPDATE voucher_lines SET credit = 115000.00 WHERE voucher_id = :v AND line_no = 1"), {"v": vid})
    with pytest.raises(VoucherRuleError) as e:
        vouchers.approve(svc_conn, vid, actor="approver")
    assert {"G-26"} <= {x.rule_id for x in e.value.errors}
