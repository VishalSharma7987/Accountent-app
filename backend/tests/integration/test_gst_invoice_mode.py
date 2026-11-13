"""Phase 3 package B: invoice-mode vouchers against the test schema (create -> approve -> post -> reverse, G-23, G-26).

Kept small on purpose (remote database). Rates come from the seeded EXAMPLE rule rows (is_example, pending): 8415 is 18%
from 22-09-2025. Expected figures are hand-calculated literals.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.db import connection, migrate
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import VoucherDraft, VoucherLine
from app.services import client_setup, gst_hooks, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import VoucherRuleError

pytestmark = pytest.mark.integration

APRIL_5 = date(2026, 4, 5)
GSTIN_SELF = "27ABCDE1234F1Z0"
GSTIN_BUYER = "29ABCDE1234F1ZW"
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
            conn, ClientProfile("GST Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
        )
        ids = dict(created.ledger_ids)
        for name, group in (("Rahul Enterprises", "sundry_debtors"), ("Sharma Suppliers", "sundry_creditors"),
                            ("Freight Inward", "direct_expenses")):
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, group, actor="setup")
        for name in ROLE_LEDGERS.values():
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, "duties_taxes", actor="setup")
        reg_id = uuid.uuid4()
        conn.execute(
            text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                 "VALUES (:r, :c, :g, '27', 'regular', '2026-04-01')"),
            {"r": reg_id, "c": created.client_id, "g": GSTIN_SELF},
        )
        for role, name in ROLE_LEDGERS.items():
            conn.execute(
                text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                {"r": reg_id, "c": created.client_id, "role": role, "l": ids[name]},
            )
        w = World(created.client_id, reg_id, ids)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def sales_draft(w, *, pos="29", hsn="8415", rate="10000.00"):
    item = ItemLineIn("Air conditioner", hsn, D(1), D(rate), D("0.00"), w.ids["Sales"], uqc="NOS")
    inv = InvoiceIn(str(w.reg_id), "tax_invoice", "b2b", pos, APRIL_5, (item,), counterparty_gstin=GSTIN_BUYER)
    return VoucherDraft(
        w.client_id, "sales", APRIL_5, "Sale of AC", None, w.ids["Rahul Enterprises"], (), gst=inv,
    )


def lines_of(conn, voucher_id):
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                 "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id})
    ]


def counts(conn, voucher_id):
    return conn.execute(
        text("SELECT (SELECT count(*) FROM voucher_gst WHERE voucher_id = :v), "
             "(SELECT count(*) FROM voucher_item_lines WHERE voucher_id = :v), "
             "(SELECT count(*) FROM voucher_gst_line_roles WHERE voucher_id = :v)"), {"v": voucher_id}).one()


def test_G13_invoice_draft_approve_post_reverse_keeps_item_rows(svc_conn, world):
    result = vouchers.create_draft(svc_conn, sales_draft(world), actor="tester")
    assert result.errors == []
    vid = result.voucher_id
    # inter-state (29): IGST 18% of 10,000.00 = 1,800.00; no CGST / SGST line
    assert lines_of(svc_conn, vid) == [
        ("Rahul Enterprises", D("11800.0000"), D("0.0000")),
        ("Sales", D("0.0000"), D("10000.0000")),
        ("Output IGST", D("0.0000"), D("1800.0000")),
    ]
    assert tuple(counts(svc_conn, vid)) == (1, 1, 3)
    shown = gst_hooks.load_invoice(svc_conn, world.client_id, vid)
    assert (shown["invoice_value"], shown["items"][0]["igst"], shown["items"][0]["treatment"]) == ("11800.00", "1800.00", "taxable")
    assert shown["rule_status"]["worst"] == "pending"
    assert {v["gst_role"] for v in shown["line_roles"].values()} == {"party", "taxable", "tax_igst"}

    vouchers.approve(svc_conn, vid, actor="approver")
    assert vouchers.post(svc_conn, vid, actor="poster") == "SAL/2026-27/0001"

    reversal_id = vouchers.reverse(svc_conn, vid, APRIL_5, "wrong buyer", actor="poster")
    assert lines_of(svc_conn, reversal_id) == [
        ("Rahul Enterprises", D("0.0000"), D("11800.0000")),
        ("Sales", D("10000.0000"), D("0.0000")),
        ("Output IGST", D("1800.0000"), D("0.0000")),
    ]
    assert tuple(counts(svc_conn, reversal_id)) == (1, 1, 3)  # item rows copied with the reversal


def test_G26_lines_changed_after_building_cannot_be_approved(svc_conn, world):
    vid = vouchers.create_draft(svc_conn, sales_draft(world), actor="tester").voucher_id
    svc_conn.execute(text("UPDATE voucher_lines SET credit = 1700.00 WHERE voucher_id = :v AND line_no = 3"), {"v": vid})
    with pytest.raises(VoucherRuleError) as e:
        vouchers.approve(svc_conn, vid, actor="approver")
    assert "G-26" in {x.rule_id for x in e.value.errors}


def test_G23_gst_voucher_number_over_the_limit_blocks_posting(svc_conn, world):
    vid = vouchers.create_draft(svc_conn, sales_draft(world), actor="tester").voucher_id
    vouchers.approve(svc_conn, vid, actor="approver")
    # the limit is a rule-table value (16): lower it inside this rolled-back transaction so the first number is too long
    svc_conn.execute(text("UPDATE gst_thresholds SET numeric_value = 10 WHERE threshold_key = 'invoice_number_max_length'"))
    with pytest.raises(VoucherRuleError) as e:
        vouchers.post(svc_conn, vid, actor="poster")  # SAL/2026-27/0001 has 16 characters
    assert [x.rule_id for x in e.value.errors] == ["G-23"]


def test_G20_rcm_purchase_default_rate_warning_and_update_replaces_rows(svc_conn, world):
    item = ItemLineIn("Freight", "996511", D(1), D("10000.00"), D("0.00"), world.ids["Freight Inward"],
                      rcm_category_key="gta_services")
    inv = InvoiceIn(str(world.reg_id), "self_invoice", "unregistered_supplier", "27", APRIL_5, (item,))
    draft = VoucherDraft(world.client_id, "purchase", APRIL_5, "GTA freight", "FR/1", world.ids["Sharma Suppliers"], (), gst=inv)
    # the supplier's state is unknown without a GSTIN or party master: refused, never guessed
    assert [e.rule_id for e in vouchers.create_draft(svc_conn, draft, actor="tester").errors] == ["G-12"]
    inv_gstin = InvoiceIn(str(world.reg_id), "self_invoice", "unregistered_supplier", "27", APRIL_5, (item,),
                          counterparty_gstin="27ABCDE1234F1Z0")
    draft = VoucherDraft(world.client_id, "purchase", APRIL_5, "GTA freight", "FR/1", world.ids["Sharma Suppliers"], (), gst=inv_gstin)
    result = vouchers.create_draft(svc_conn, draft, actor="tester")
    assert result.errors == []
    vid = result.voucher_id
    # default services rate 18% (pending rule, warned): 900.00 + 900.00, Dr input and Cr RCM payable; supplier gets 10,000.00
    assert lines_of(svc_conn, vid) == [
        ("Sharma Suppliers", D("0.0000"), D("10000.0000")),
        ("Freight Inward", D("10000.0000"), D("0.0000")),
        ("Input CGST", D("900.0000"), D("0.0000")),
        ("Input SGST", D("900.0000"), D("0.0000")),
        ("RCM CGST Payable", D("0.0000"), D("900.0000")),
        ("RCM SGST Payable", D("0.0000"), D("900.0000")),
    ]
    shown = gst_hooks.load_invoice(svc_conn, world.client_id, vid)
    assert [w["rule_id"] for w in shown["warnings"]] == ["G-10"] and shown["has_rcm"] is True
    # editing the draft back to a plain voucher removes the GST rows
    plain = VoucherDraft(
        world.client_id, "journal", APRIL_5, "plain", None, None,
        (VoucherLine(world.ids["Freight Inward"], "10.00", None),
         VoucherLine(world.ids["Sharma Suppliers"], None, "10.00")),
    )
    assert vouchers.update_draft(svc_conn, vid, plain, actor="tester").errors == []
    assert tuple(counts(svc_conn, vid)) == (0, 0, 0)


def test_G14_excel_import_item_rows_dry_run_and_commit_build_the_tax_lines(svc_conn, world):
    from xlsx_helpers import make_xlsx

    from app.importers.voucher_excel import COLUMNS, GST_COLUMNS
    from app.services import voucher_import

    header = COLUMNS + GST_COLUMNS

    def sheet_row(ref, **cells):
        base = {name: None for name in header}
        base.update({"ref_id": ref, "date": "2026-04-05", "voucher_type": "sales", "narration": "Sale",
                     "party_ledger": "Rahul Enterprises", "gst_registration": GSTIN_SELF, "document_kind": "tax_invoice",
                     "supply_category": "b2b", "place_of_supply": "27", "counterparty_gstin": GSTIN_BUYER,
                     "item_description": "AC", "hsn_sac": "8415", "uqc": "NOS", "quantity": 1, "unit_rate": "10000.00",
                     "item_ledger": "Sales"})
        base.update(cells)
        return [base[name] for name in header]

    data = make_xlsx([sheet_row("S1"), sheet_row("S2", hsn_sac="9018")], header=header)
    dry = voucher_import.dry_run(svc_conn, world.client_id, data)
    assert (dry.ok_count, dry.error_count) == (1, 1)
    bad = next(v for v in dry.vouchers if v.ref_id == "S2")
    assert [(i.rule_id, i.row) for i in bad.errors] == [("G-10", 3)]  # no rate rule for 9018: the row is named

    done = voucher_import.commit(svc_conn, world.client_id, data, None, actor="importer")
    assert len(done.created) == 1
    # intra-state (27 = 27): 18% of 10,000.00 = 900.00 CGST + 900.00 SGST
    assert lines_of(svc_conn, done.created[0].voucher_id) == [
        ("Rahul Enterprises", D("11800.0000"), D("0.0000")),
        ("Sales", D("0.0000"), D("10000.0000")),
        ("Output CGST", D("0.0000"), D("900.0000")),
        ("Output SGST", D("0.0000"), D("900.0000")),
    ]
