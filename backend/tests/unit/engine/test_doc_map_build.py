"""Package E: mapping resolution (D-20, D-21, D-24) and the draft builder (D-22, D-23, D-08) on literal data. No DB, no AI."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.engine.doc_build import (
    BuildContext,
    ItemInfo,
    PartyInfo,
    RegistrationInfo,
    build_invoice_draft,
    invoice_from_payload,
    parse_date,
    state_code_from_text,
)
from app.engine.doc_map import (
    LineMap,
    MappingKeyError,
    PartyMap,
    line_key,
    normalise_name,
    party_key,
    resolve_line,
    resolve_party,
)
from app.engine.doc_types import (
    DocType,
    ExtractedInvoice,
    ExtractedLine,
    ExtractedTotals,
    Field,
    Severity,
)

SELF = "27ABCDE1234F1Z0"
SUPPLIER = "29ABCDE1234F1ZW"
STATES = {"27": "Maharashtra", "29": "Karnataka"}
SUP_LEDGER, PURCH_LEDGER, ITEM = "led-sup", "led-purch", "item-1"


def F(v):
    return Field(None if v is None else str(v))


def line(desc="Air conditioner", hsn="8415", qty="2", rate="10000.00", disc="0.00"):
    blank = F(None)
    return ExtractedLine(F(desc), F(hsn), F(qty), F("NOS"), F(rate), F(disc), blank, blank, blank, blank, blank, blank)


def invoice(**kw):
    blank = F(None)
    base = {
        "document_kind": F("purchase_invoice"), "supplier_name": F("Sharma Suppliers Pvt. Ltd."), "supplier_gstin": F(SUPPLIER),
        "buyer_name": F("Client Traders"), "buyer_gstin": F(SELF), "invoice_no": F("SS/101"), "invoice_date": F("05-04-2026"),
        "place_of_supply": F("27-Maharashtra"), "original_invoice_no": blank, "lines": (line(),),
        "totals": ExtractedTotals(blank, blank, blank, blank, blank, blank, blank),
    }
    base.update(kw)
    return ExtractedInvoice(**base)


def ctx(**kw):
    base = {
        "client_id": "c1", "doc_type": DocType.PURCHASE_INVOICE,
        "registrations": (RegistrationInfo("reg-1", SELF, "27", date(2026, 4, 1)),),
        "party_maps": (PartyMap("pm1", "gstin", SUPPLIER, SUP_LEDGER),),
        "line_maps": (LineMap("lm1", "hsn_sac", "8415", None, PURCH_LEDGER, None),),
        "state_names": STATES, "parties": {SUP_LEDGER: PartyInfo(SUP_LEDGER, SUPPLIER, "29")}, "items": {},
    }
    base.update(kw)
    return BuildContext(**base)


def rules(result, sev=None):
    return [(f.rule_id, f.severity.value) for f in result.findings if sev is None or f.severity == sev]


# ---- keys ---------------------------------------------------------------------------------------------------
def test_D20_name_key_is_normalised_spelling_only():
    assert normalise_name("  M/S Sharma  Suppliers Pvt. Ltd. & Sons ") == "m/s sharma suppliers pvt ltd and sons"
    assert party_key("name", "Sharma Suppliers") == "sharma suppliers"
    assert party_key("gstin", " 29abcde1234f1zw ") == "29ABCDE1234F1ZW"


def test_D20_bad_keys_are_refused():
    for kind, raw in (("gstin", "123"), ("gstin", None), ("name", "  "), ("pan", "x")):
        with pytest.raises(MappingKeyError):
            party_key(kind, raw)
    assert line_key("hsn_sac", "84.15 ") == "8415"
    with pytest.raises(MappingKeyError):
        line_key("hsn_sac", "")


# ---- resolve_party ---------------------------------------------------------------------------------------------
def test_D20_unmapped_party_is_review_and_nothing_chosen():
    r = resolve_party(label="Supplier", gstin=SUPPLIER, name="Unknown Co", maps=[], field_path="supplier_name")
    assert r.ledger_id is None and (r.finding.rule_id, r.finding.severity) == ("D-20", Severity.REVIEW)
    assert "no party was created" in r.finding.message


def test_D20_gstin_or_name_match_resolves():
    maps = [PartyMap("a", "name", "sharma suppliers pvt ltd", "L1")]
    r = resolve_party(label="Supplier", gstin=None, name="Sharma Suppliers Pvt. Ltd.", maps=maps, field_path="x")
    assert (r.ledger_id, r.map_ids, r.finding) == ("L1", ("a",), None)


def test_D24_gstin_and_name_pointing_to_different_ledgers_is_ambiguous_review():
    maps = [PartyMap("a", "gstin", SUPPLIER, "L1"), PartyMap("b", "name", "sharma suppliers", "L2")]
    r = resolve_party(label="Supplier", gstin=SUPPLIER, name="Sharma Suppliers", maps=maps, field_path="x")
    assert r.ledger_id is None and (r.finding.rule_id, r.finding.severity) == ("D-24", Severity.REVIEW)


def test_D24_gstin_and_name_agreeing_is_not_ambiguous():
    maps = [PartyMap("a", "gstin", SUPPLIER, "L1"), PartyMap("b", "name", "sharma suppliers", "L1")]
    assert resolve_party(label="Supplier", gstin=SUPPLIER, name="Sharma Suppliers", maps=maps, field_path="x").ledger_id == "L1"


# ---- resolve_line ----------------------------------------------------------------------------------------------
def test_D21_unmapped_line_is_review_with_line_path():
    r = resolve_line(n=2, description="Widget", hsn_sac="9999", party_ledger_id="P", maps=[])
    assert r.ledger_id is None and (r.finding.rule_id, r.finding.field_path) == ("D-21", "lines[1].description")


def test_D21_party_scoped_mapping_wins_over_general():
    maps = [LineMap("g", "hsn_sac", "8415", None, "GEN", None), LineMap("s", "hsn_sac", "8415", "P", "SPEC", "I1")]
    r = resolve_line(n=1, description="x", hsn_sac="8415", party_ledger_id="P", maps=maps)
    assert (r.ledger_id, r.item_id) == ("SPEC", "I1")
    assert resolve_line(n=1, description="x", hsn_sac="8415", party_ledger_id="OTHER", maps=maps).ledger_id == "GEN"


def test_D24_description_and_hsn_disagreeing_is_ambiguous():
    maps = [LineMap("a", "hsn_sac", "8415", None, "L1", None), LineMap("b", "description", "air conditioner", None, "L2", None)]
    r = resolve_line(n=1, description="Air Conditioner", hsn_sac="8415", party_ledger_id=None, maps=maps)
    assert r.ledger_id is None and r.finding.rule_id == "D-24"


# ---- builder -------------------------------------------------------------------------------------------------
def test_D25_complete_purchase_builds_a_gst_invoice_draft_without_amounts():
    r = build_invoice_draft(invoice(), ctx())
    assert r.findings == () and r.blocked is False
    d = r.draft
    assert (d.voucher_type, d.voucher_date, d.reference_no, d.party_ledger_id, d.lines) == (
        "purchase", date(2026, 4, 5), "SS/101", SUP_LEDGER, ())
    assert d.narration == "Purchase invoice SS/101 dated 05-04-2026 Sharma Suppliers Pvt. Ltd. (from document)"
    g = d.gst
    assert (g.gst_registration_id, g.document_kind, g.supply_category, g.place_of_supply, g.counterparty_gstin) == (
        "reg-1", "tax_invoice", "b2b", "27", SUPPLIER)
    (it,) = g.items
    assert (it.description, it.hsn_sac, it.quantity, it.unit_rate, it.discount, it.ledger_id) == (
        "Air conditioner", "8415", D(2), D("10000.00"), D("0.00"), PURCH_LEDGER)
    assert r.party_map_ids == ("pm1",) and r.line_map_ids == ("lm1",)


def test_D20_unknown_supplier_builds_no_draft():
    r = build_invoice_draft(invoice(), ctx(party_maps=()))
    assert r.draft is None and ("D-20", "review") in rules(r)


def test_D21_unknown_line_ledger_builds_no_draft_and_creates_nothing():
    r = build_invoice_draft(invoice(), ctx(line_maps=()))
    assert r.draft is None and rules(r) == [("D-21", "review")]


def test_D22_document_gstin_differs_from_party_master_gstin_is_error():
    c = ctx(parties={SUP_LEDGER: PartyInfo(SUP_LEDGER, "27ABCDE1234F1Z0", "27")})
    r = build_invoice_draft(invoice(), c)
    assert r.draft is None and ("D-22", "error") in rules(r)


def test_D08_client_gstin_not_a_registration_is_error():
    r = build_invoice_draft(invoice(buyer_gstin=F("33ABCDE1234F1Z0")), ctx())
    assert r.draft is None and ("D-08", "error") in rules(r)


def test_D23_unknown_printed_state_is_review():
    r = build_invoice_draft(invoice(place_of_supply=F("Atlantis")), ctx())
    assert r.draft is None and rules(r) == [("D-23", "review")]


def test_D23_missing_pos_on_purchase_comes_from_our_registration_state():
    r = build_invoice_draft(invoice(place_of_supply=F(None)), ctx())
    assert r.draft.gst.place_of_supply == "27"


def test_D23_missing_pos_on_sale_without_buyer_gstin_or_state_is_review():
    inv = invoice(supplier_gstin=F(SELF), supplier_name=F("Client Traders"), buyer_gstin=F(None), buyer_name=F("Walk In"),
                  place_of_supply=F(None))
    c = ctx(doc_type=DocType.SALES_INVOICE, party_maps=(PartyMap("pm", "name", "walk in", "CUST"),),
            parties={"CUST": PartyInfo("CUST")})
    r = build_invoice_draft(inv, c)
    assert r.draft is None and rules(r) == [("D-23", "review")]


def test_D25_sale_to_walk_in_with_party_state_is_b2c_and_uses_party_state():
    inv = invoice(supplier_gstin=F(SELF), supplier_name=F("Client Traders"), buyer_gstin=F(None), buyer_name=F("Walk In"),
                  place_of_supply=F(None), invoice_no=F(None))
    c = ctx(doc_type=DocType.SALES_INVOICE, party_maps=(PartyMap("pm", "name", "walk in", "CUST"),),
            parties={"CUST": PartyInfo("CUST", None, "29")})
    d = build_invoice_draft(inv, c).draft
    assert (d.voucher_type, d.gst.supply_category, d.gst.place_of_supply, d.reference_no) == ("sales", "b2c", "29", None)


def test_D16_missing_hsn_taken_from_item_master_or_reviewed():
    maps = (LineMap("lm", "description", "air conditioner", None, PURCH_LEDGER, ITEM),)
    ok = build_invoice_draft(invoice(lines=(line(hsn=None),)), ctx(line_maps=maps, items={ITEM: ItemInfo(ITEM, "8415", "NOS")}))
    assert ok.draft.gst.items[0].hsn_sac == "8415" and ok.draft.gst.items[0].item_id == ITEM and ok.draft.gst.items[0].uqc == "NOS"
    bad = build_invoice_draft(invoice(lines=(line(hsn=None),)), ctx(line_maps=maps))
    assert bad.draft is None and ("D-16", "review") in rules(bad)


def test_D06_unreadable_quantity_and_date_are_errors_not_guesses():
    r = build_invoice_draft(invoice(invoice_date=F("2026-13-45"), lines=(line(qty="two"),)), ctx())
    assert r.draft is None
    assert ("D-06", "error") in rules(r)


def test_D25_note_without_reason_and_original_date_is_review():
    c = ctx(doc_type=DocType.DEBIT_NOTE)
    r = build_invoice_draft(invoice(original_invoice_no=F("SS/90")), c)
    assert r.draft is None and rules(r) == [("D-25", "review"), ("D-25", "review")]
    c2 = ctx(doc_type=DocType.DEBIT_NOTE, note_reason="correction_in_invoice", original_invoice_date=date(2026, 3, 1))
    d = build_invoice_draft(invoice(original_invoice_no=F("SS/90")), c2).draft
    assert (d.voucher_type, d.gst.original_invoice_no, d.gst.original_invoice_date, d.gst.note_reason) == (
        "debit_note", "SS/90", date(2026, 3, 1), "correction_in_invoice")


def test_D09_bank_statement_is_not_draftable():
    r = build_invoice_draft(invoice(), ctx(doc_type=DocType.BANK_STATEMENT))
    assert r.draft is None and rules(r) == [("D-09", "error")]


# ---- helpers -------------------------------------------------------------------------------------------------
def test_D06_date_and_state_parsers():
    assert parse_date("05-04-2026") == parse_date("05/04/2026") == parse_date("2026-04-05") == date(2026, 4, 5)
    assert parse_date("31-02-2026") is None and parse_date("5 April") is None
    assert [state_code_from_text(t, STATES) for t in ("29", "29-Karnataka", "Karnataka (29)", "karnataka", "99", "")] == [
        "29", "29", "29", "29", None, None]


def test_D25_payload_reader_makes_engine_data():
    payload = {"supplier_name": {"value": "ABC", "page": 1, "bbox": ["0.1", "0.1", "0.5", "0.2"], "confidence": "0.95"},
               "lines": [{"description": {"value": "Pen"}, "quantity": {"value": "3"}}], "totals": {}}
    inv = invoice_from_payload(payload)
    assert inv.supplier_name.value == "ABC" and inv.supplier_name.source.page == 1 and inv.supplier_name.confidence == D("0.95")
    assert inv.lines[0].description.value == "Pen" and inv.lines[0].hsn_sac.value is None and inv.invoice_no.value is None
