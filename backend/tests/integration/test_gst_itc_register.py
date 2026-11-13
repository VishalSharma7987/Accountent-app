"""Phase 3 package C: ITC register on posting, evidence, claim deadline, 180-day reversal and re-claim drafts.

Purchases are created through B's invoice mode (a `gst` block with the supplier's GSTIN); posting and reversing call the
ITC hooks by themselves. Registration and ledger roles are written with plain SQL. One committed world per module; each
test is rolled back.

Hand-calculated numbers (bill SUP/1 dated 03-04-2026: taxable 1,000.00, CGST 90.00, SGST 90.00, bill 1,180.00):
  paid 400.00 -> outstanding 780.00; share 780/1180 -> CGST 90 x 780/1180 = 59.4915 -> 59.49, SGST 59.49 (total 118.98)
  later paid 280.00 -> outstanding 500.00; share CGST 90 x 500/1180 = 38.1356 -> 38.14; reclaim 59.49 - 38.14 = 21.35 each
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from books import build_books
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import Allocation, VoucherDraft, VoucherLine
from app.main import app
from app.services import client_setup, gst_itc, parties, vouchers
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

D = Decimal
GSTIN = "27AAPFU0939F1ZV"
SUPPLIER_GSTIN = "27ABCDE1234F1Z0"


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        b = build_books(conn)
        for name, group in (
            ("Input CGST", "duties_taxes"), ("Input SGST", "duties_taxes"), ("Input IGST", "duties_taxes"),
            ("Input Cess", "duties_taxes"), ("ITC Reversal", "indirect_expenses"),
        ):
            b.ids[name] = client_setup.add_ledger(conn, b.client_id, name, group, actor="setup")
        parties.set_party(conn, b.client_id, b.ids["Sharma Suppliers"], bill_wise=True, actor="setup")
        reg = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                "VALUES (:i, :c, :g, '27', 'regular', '2026-04-01')"
            ),
            {"i": reg, "c": b.client_id, "g": GSTIN},
        )
        for role, ledger in (
            ("input_cgst", "Input CGST"), ("input_sgst", "Input SGST"), ("input_igst", "Input IGST"),
            ("input_cess", "Input Cess"), ("itc_reversal", "ITC Reversal"),
        ):
            conn.execute(
                text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                {"r": reg, "c": b.client_id, "role": role, "l": b.ids[ledger]},
            )
        b.ids["registration"] = reg
    yield b
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def purchase(conn, w, ref="SUP/1", on=date(2026, 4, 3), category=None):
    """A POSTED purchase built in B's invoice mode (taxable 1,000.00, CGST 90.00, SGST 90.00); the post hook makes the ITC entry."""
    ids = w.ids
    item = ItemLineIn("Item", "8415", D(1), D("1000.00"), D("0.00"), str(ids["Purchases"]), uqc="NOS", itc_category_key=category)
    inv = InvoiceIn(str(ids["registration"]), "tax_invoice", "b2b", "27", on, (item,), counterparty_gstin=SUPPLIER_GSTIN)
    result = vouchers.create_draft(
        conn, VoucherDraft(w.client_id, "purchase", on, "Goods from Sharma", ref, ids["Sharma Suppliers"], (), gst=inv), actor="clerk"
    )
    assert result.errors == [], result.errors
    vid = result.voucher_id
    vouchers.approve(conn, vid, actor="partner")
    vouchers.post(conn, vid, actor="partner")
    return vid


def pay(conn, w, amount, on, ref="SUP/1"):
    d = VoucherDraft(
        w.client_id, "payment", on, "Paid Sharma", None, w.ids["Sharma Suppliers"],
        (VoucherLine(w.ids["Sharma Suppliers"], amount, None, (Allocation("against_ref", amount, ref),)),
         VoucherLine(w.ids["HDFC Bank"], None, amount)),
    )
    result = vouchers.create_draft(conn, d, actor="clerk")
    assert result.errors == [], result.errors
    vouchers.approve(conn, result.voucher_id, actor="partner")
    vouchers.post(conn, result.voucher_id, actor="partner")


def post_journal(conn, w, voucher_id):
    vouchers.approve(conn, voucher_id, actor="partner")
    vouchers.post(conn, voucher_id, actor="partner")


def entry_of(conn, w, vid):
    entries = gst_itc.list_register(conn, w.client_id)["entries"]
    return entries, next(e for e in entries if e["voucher_id"] == vid)


def test_G30_G31_G32_G33_posting_creates_entry_then_evidence_confirm_claim_and_deadline(svc_conn, world):
    w, c = world, svc_conn
    vid = purchase(c, w)
    _, e = entry_of(c, w, vid)
    assert (e["status"], e["pending_reason"], e["cgst"], e["sgst"], e["igst"], e["cess"]) == (
        "pending", "evidence_missing", D("90.00"), D("90.00"), D("0.00"), D("0.00"))
    assert (e["supplier_invoice_no"], e["claim_deadline"], e["source"], e["doc_type"]) == ("SUP/1", date(2027, 11, 30), "regular", "invoice")
    gst_itc.on_post(c, w.client_id, vid, "partner")  # a second run adds nothing
    assert len(gst_itc.list_register(c, w.client_id)["entries"]) == 1
    # G-31: evidence recorded, supplier's tax not yet seen in 2B -> pending not_in_2b
    e = gst_itc.update_evidence(c, w.client_id, e["id"], tax_document_held=True, goods_services_received=True,
                                received_date=date(2026, 4, 5), actor="clerk")
    assert (e["status"], e["pending_reason"]) == ("pending", "not_in_2b")
    # G-32: manual confirmation needs a reason
    with pytest.raises(ServiceError) as info:
        gst_itc.confirm(c, w.client_id, e["id"], reason=" ", actor="clerk")
    assert info.value.code == "reason_required"
    e = gst_itc.confirm(c, w.client_id, e["id"], reason="Supplier confirmed GSTR-1 filing by mail", actor="clerk")
    assert (e["status"], e["supplier_tax_paid"]) == ("eligible", "manual_confirmed")
    # G-33: claiming after 30-11-2027 is refused, in time it is recorded
    with pytest.raises(ServiceError) as info:
        gst_itc.set_claimed_period(c, w.client_id, e["id"], date(2027, 12, 1), actor="clerk")
    assert info.value.code == "claim_deadline_passed"
    e = gst_itc.set_claimed_period(c, w.client_id, e["id"], date(2026, 5, 1), actor="clerk")
    assert e["claimed_in_period"] == date(2026, 5, 1)
    with pytest.raises(ServiceError) as info:  # evidence is frozen once claimed
        gst_itc.update_evidence(c, w.client_id, e["id"], tax_document_held=False, goods_services_received=True, actor="clerk")
    assert info.value.code == "itc_invalid_transition"
    events = gst_itc.events(c, w.client_id, e["id"])
    assert [(x["from_status"], x["to_status"]) for x in events] == [
        (None, "pending"), ("pending", "pending"), ("pending", "eligible"), ("eligible", "eligible")]


def test_G30_G36_tag_blocked_before_claim_blocks_and_after_claim_drafts_a_reversal(svc_conn, world):
    w, c = world, svc_conn
    _, e = entry_of(c, w, purchase(c, w))
    with pytest.raises(ServiceError) as info:
        gst_itc.tag_blocked(c, w.client_id, e["id"], category_key="no_such", note="x", actor="clerk")
    assert info.value.code == "invalid_category"
    blocked = gst_itc.tag_blocked(c, w.client_id, e["id"], category_key="club_fitness_membership_17_5_b", note="Gym fees", actor="clerk")
    assert (blocked["status"], blocked["blocked_category_key"]) == ("blocked", "club_fitness_membership_17_5_b")
    # a second purchase, claimed first, then identified late: a DRAFT journal Dr ITC Reversal 180.00 / Cr Input CGST 90 + SGST 90
    _, e2 = entry_of(c, w, purchase(c, w, ref="SUP/2"))
    gst_itc.update_evidence(c, w.client_id, e2["id"], tax_document_held=True, goods_services_received=True,
                            received_date=date(2026, 4, 5), supplier_tax_paid="manual_confirmed", evidence_note="paid", actor="clerk")
    gst_itc.set_claimed_period(c, w.client_id, e2["id"], date(2026, 5, 1), actor="clerk")
    gst_itc.tag_blocked(c, w.client_id, e2["id"], category_key="club_fitness_membership_17_5_b", note="Gym", actor="clerk", as_on=date(2026, 6, 1))
    [rev] = gst_itc.list_reversals(c, w.client_id)
    assert (rev["status"], rev["reason"], rev["amounts"]["cgst"], rev["amounts"]["sgst"]) == ("drafted", "blocked_identified_late", D("90.00"), D("90.00"))
    voucher = vouchers.get_voucher(c, rev["reversal_voucher_id"])
    assert (voucher.status, [(x.debit, x.credit) for x in voucher.lines]) == (
        "draft", [(D("180.00"), D("0.00")), (D("0.00"), D("90.00")), (D("0.00"), D("90.00"))])
    post_journal(c, w, rev["reversal_voucher_id"])
    assert gst_itc.get_entry(c, w.client_id, e2["id"])["status"] == "reversed"


def test_G37_reversing_the_purchase_marks_its_entries_reversed(svc_conn, world):
    w, c = world, svc_conn
    vid = purchase(c, w)
    _, e = entry_of(c, w, vid)
    vouchers.reverse(c, vid, date(2026, 4, 20), "Wrong bill", actor="partner")  # the reverse hook marks the entries
    assert gst_itc.get_entry(c, w.client_id, e["id"])["status"] == "reversed"
    with pytest.raises(ServiceError) as info:
        gst_itc.confirm(c, w.client_id, e["id"], reason="again", actor="clerk")
    assert info.value.code == "itc_invalid_transition"


def test_G34_G35_G36_180_day_exposure_reversal_draft_reclaim_and_register_tie(svc_conn, world):
    w, c = world, svc_conn
    vid = purchase(c, w)
    _, e = entry_of(c, w, vid)
    pay(c, w, "400.00", date(2026, 6, 1))
    # on 28-09-2026 (178 days) the bill is within 30 days of the limit; on 01-11-2026 (212 days) it is due
    near = gst_itc.exposure_180(c, w.client_id, w.ids["registration"], date(2026, 9, 28))
    assert (len(near["items"]), len(near["approaching"])) == (0, 1)
    x = gst_itc.exposure_180(c, w.client_id, w.ids["registration"], date(2026, 11, 1))
    [item] = x["items"]
    assert (item["days"], item["due_on_day"], item["outstanding"], item["cgst"], item["sgst"], item["igst"]) == (
        212, date(2026, 9, 30), D("780.00"), D("59.49"), D("59.49"), D("0.00"))
    assert (x["rule_status"], str(item["unpaid_share"]["fraction"])) == ("pending", "0.6610")
    [made] = gst_itc.create_reversals(c, w.client_id, w.ids["registration"], date(2026, 11, 1), None, actor="clerk")
    assert (made["cgst"], made["sgst"], made["igst"]) == ("59.49", "59.49", "0.00")
    with pytest.raises(ServiceError) as info:  # G-36: same amount cannot be reversed twice
        gst_itc.create_reversals(c, w.client_id, w.ids["registration"], date(2026, 11, 1), None, actor="clerk")
    assert info.value.code == "reversal_exists"
    with pytest.raises(ServiceError) as info:  # not posted yet -> no re-claim
        gst_itc.reclaim(c, w.client_id, made["reversal_id"], date(2026, 11, 15), actor="clerk")
    assert info.value.code == "itc_invalid_transition"
    post_journal(c, w, made["voucher_id"])
    assert gst_itc.get_entry(c, w.client_id, e["id"])["status"] == "pending"  # partial reversal: the entry stays
    # G-35: 280.00 paid later -> outstanding 500.00, share 38.14 each, reclaim 59.49 - 38.14 = 21.35 each
    pay(c, w, "280.00", date(2026, 11, 10))
    got = gst_itc.reclaim(c, w.client_id, made["reversal_id"], date(2026, 11, 15), actor="clerk")
    assert (got["cgst"], got["sgst"]) == ("21.35", "21.35")
    with pytest.raises(ServiceError) as info:  # once per payment: the re-claim draft is pending
        gst_itc.reclaim(c, w.client_id, made["reversal_id"], date(2026, 11, 15), actor="clerk")
    assert info.value.code == "itc_invalid_transition"
    post_journal(c, w, got["reclaim_voucher_id"])
    [rev] = gst_itc.list_reversals(c, w.client_id)
    assert (rev["status"], rev["reclaimed"]["cgst"], rev["reclaimed"]["sgst"]) == ("reversed", D("21.35"), D("21.35"))
    # Input CGST ledger: Dr 90.00 - Cr 59.49 + Dr 21.35 = Dr 51.86 = register 90.00 - net reversed 38.14
    tie = gst_itc.register_tie(c, w.client_id, w.ids["registration"], date(2026, 11, 30))
    assert tie["ties"] is True
    assert tie["input_ledgers"]["cgst"] == {"amount": "51.86", "side": "Dr"} == tie["itc_register"]["cgst"]


def test_api_register_amounts_are_strings_and_unknown_entry_is_404(svc_conn, world):
    w = world
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        vid = purchase(svc_conn, w)
        body = api.get(f"/clients/{w.client_id}/gst/itc").json()
        [e] = [x for x in body["entries"] if x["voucher_id"] == str(vid)]
        assert (e["cgst"], e["status"], body["totals"]["pending"]["cgst"]) == ("90.00", "pending", "90.00")
        r = api.put(f"/clients/{w.client_id}/gst/itc/{e['id']}/evidence", headers={"X-User": "t"},
                    json={"tax_document_held": True, "goods_services_received": True, "received_date": "2026-04-05"})
        assert (r.status_code, r.json()["pending_reason"]) == (200, "not_in_2b")
        assert api.get(f"/clients/{w.client_id}/gst/itc/{uuid.uuid4()}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_G32_apply_2b_result_from_the_reconciliation_sets_pending_reason_and_never_eligible(svc_conn, world):
    from app.engine.gst_recon import ItcEffect

    w, c = world, svc_conn
    vid = purchase(c, w)
    _, e = entry_of(c, w, vid)
    gst_itc.update_evidence(c, w.client_id, e["id"], tax_document_held=True, goods_services_received=True,
                            received_date=date(2026, 4, 5), actor="clerk")
    reg = w.ids["registration"]
    [r] = gst_itc.apply_2b_result(c, w.client_id, reg, date(2026, 4, 1), [ItcEffect(vid, "in_2b", "ims_rejected", "matched")], "clerk")
    assert (r["from_status"], r["to_status"]) == ("pending", "pending")
    assert gst_itc.get_entry(c, w.client_id, e["id"])["pending_reason"] == "ims_rejected"
    [r] = gst_itc.apply_2b_result(c, w.client_id, reg, date(2026, 4, 1), [ItcEffect(vid, "in_2b", None, "matched")], "clerk")
    assert (r["from_status"], r["to_status"]) == ("pending", "eligible")
