"""Package D: pure GSTR-2B reconciliation (G-42, G-43, G-44). Literal objects, hand-typed expected values."""

from datetime import date
from decimal import Decimal as D

from app.engine.gst_recon import BookDoc, Doc2B, Link, apply_effects, normalise_doc_no, reconcile

G1 = "27AAPFU0939F1ZV"


def book(vid="v1", no="INV-001", gstin=G1, on=date(2026, 4, 10), taxable="1000.00", igst="0.00", cgst="90.00",
         sgst="90.00", cess="0.00", doc_type="invoice", status="pending"):
    return BookDoc(vid, "PUR/2026-27/0001", gstin, no, on, D(taxable), D(igst), D(cgst), D(sgst), D(cess), doc_type, status)


def doc(did="d1", no="inv/001", gstin=G1, on=date(2026, 4, 10), taxable="1000.00", igst="0.00", cgst="90.00",
        sgst="90.00", cess="0.00", doc_type="invoice", itc="yes", ims="none"):
    return Doc2B(did, gstin, no, on, D(taxable), D(igst), D(cgst), D(sgst), D(cess), doc_type, itc, ims)


def classes(result):
    return [r.cls for r in result.rows]


def test_G42_normalise_number_upper_strips_spaces_separators_and_leading_zeros():
    assert normalise_doc_no("INV-001") == "INV001"
    assert normalise_doc_no(" inv/001 ") == "INV001"
    assert normalise_doc_no("A.B\\C- 9") == "ABC9"
    assert normalise_doc_no("0007") == "7"
    assert normalise_doc_no("000") == "0"


def test_G42_matched_number_written_differently():
    result = reconcile([book()], [doc()])
    assert classes(result) == ["matched"]
    assert result.summary["matched"] == 1
    assert result.rows[0].differences == ()


def test_G42_value_mismatch_one_rupee_off_lists_the_difference():
    result = reconcile([book()], [doc(cgst="91.00")])
    row = result.rows[0]
    assert row.cls == "value_mismatch"
    assert [(d.field, d.books, d.doc_2b, d.difference) for d in row.differences] == [
        ("cgst", D("90.00"), D("91.00"), D("1.00"))
    ]


def test_G42_tolerance_zero_by_default_and_applied_when_set():
    assert classes(reconcile([book()], [doc(cgst="90.01")])) == ["value_mismatch"]
    assert classes(reconcile([book()], [doc(cgst="90.01")], tolerance=D("0.01"))) == ["matched"]
    assert classes(reconcile([book()], [doc(cgst="90.02")], tolerance=D("0.01"))) == ["value_mismatch"]


def test_G42_gstin_differs_by_one_character():
    result = reconcile([book()], [doc(gstin="27AAPFU0939F1ZW")])
    assert classes(result) == ["gstin_mismatch"]
    assert result.rows[0].book is not None and result.rows[0].doc is not None


def test_G42_gstin_mismatch_needs_same_taxable_value():
    result = reconcile([book()], [doc(gstin="27AAPFU0939F1ZW", taxable="999.00")])
    assert sorted(classes(result)) == ["only_in_2b", "only_in_books"]


def test_G42_same_number_other_date_is_not_a_match():
    result = reconcile([book()], [doc(on=date(2026, 4, 11))])
    assert sorted(classes(result)) == ["only_in_2b", "only_in_books"]


def test_G42_period_mismatch_document_sits_in_another_periods_2b():
    result = reconcile([book()], [], other_docs=[doc(did="d9")])
    assert classes(result) == ["period_mismatch"]
    assert result.rows[0].doc.document_id == "d9"


def test_G42_only_in_books_and_only_in_2b():
    result = reconcile([book(no="A1")], [doc(no="B1")])
    assert sorted(classes(result)) == ["only_in_2b", "only_in_books"]
    assert result.summary == {
        "matched": 0, "value_mismatch": 0, "gstin_mismatch": 0, "period_mismatch": 0,
        "only_in_books": 1, "only_in_2b": 1, "ambiguous": 0,
    }


def test_G42_two_candidates_reported_ambiguous_not_resolved():
    books = [book(vid="v1", no="INV-001"), book(vid="v2", no="INV001")]
    result = reconcile(books, [doc()])
    assert classes(result) == ["ambiguous"]
    assert "v1" in result.rows[0].note and "v2" in result.rows[0].note
    assert result.summary["ambiguous"] == 1


def test_G42_document_type_is_part_of_the_key():
    result = reconcile([book()], [doc(doc_type="credit_note")])
    assert sorted(classes(result)) == ["only_in_2b", "only_in_books"]


def test_G43_manual_link_pairs_different_numbers():
    result = reconcile([book(no="X-1")], [doc(no="Y-9")], links=[Link("l1", "d1", "v1", "manual", "same bill")])
    assert classes(result) == ["matched"]
    assert result.rows[0].link_id == "l1"


def test_G43_manual_link_with_different_amount_is_value_mismatch_but_accepted_difference_matches():
    manual = reconcile([book(no="X")], [doc(no="Y", cgst="95.00")], links=[Link("l1", "d1", "v1", "manual", "n")])
    assert classes(manual) == ["value_mismatch"]
    accepted = reconcile([book(no="X")], [doc(no="Y", cgst="95.00")],
                         links=[Link("l1", "d1", "v1", "accepted_difference", "rounding by supplier")])
    assert classes(accepted) == ["matched"]
    assert "accepted" in accepted.rows[0].note.lower()
    assert len(accepted.rows[0].differences) == 1


def test_G44_itc_not_available_and_ims_rejected_are_risks_in_the_note():
    no = reconcile([book()], [doc(itc="no")])
    assert classes(no) == ["matched"] and "not available" in no.rows[0].note.lower()
    rejected = reconcile([book()], [doc(ims="rejected")])
    assert "rejected" in rejected.rows[0].note.lower()


def test_G42_totals_credit_notes_are_subtracted():
    books = [book(vid="v1", no="A", taxable="1000.00"),
             book(vid="v2", no="C1", taxable="200.00", cgst="18.00", sgst="18.00", doc_type="credit_note")]
    docs = [doc(did="d1", no="A", taxable="1000.00"),
            doc(did="d2", no="C1", taxable="200.00", cgst="18.00", sgst="18.00", doc_type="credit_note")]
    result = reconcile(books, docs)
    assert result.totals["books"]["taxable_value"] == D("800.00")
    assert result.totals["books"]["cgst"] == D("72.00")
    assert result.totals["doc_2b"]["cgst"] == D("72.00")
    assert result.totals["difference"]["cgst"] == D("0.00")


def test_G42_row_order_is_deterministic_by_class_then_number():
    result = reconcile([book(vid="v2", no="B"), book(vid="v1", no="A")], [])
    assert [r.book.voucher_id for r in result.rows] == ["v1", "v2"]


def test_G32_effects_matched_in_2b_only_in_books_not_in_2b_ims_states_never_eligible():
    books = [book(vid="m", no="M"), book(vid="o", no="O"), book(vid="r", no="R"), book(vid="p", no="P"),
             book(vid="n", no="N")]
    docs = [doc(did="1", no="M"), doc(did="2", no="R", ims="rejected"), doc(did="3", no="P", ims="pending"),
            doc(did="4", no="N", itc="no")]
    effects = {e.voucher_id: (e.supplier_tax_paid, e.pending_reason) for e in apply_effects(reconcile(books, docs))}
    assert effects == {
        "m": ("in_2b", None),
        "o": ("not_in_2b", "not_in_2b"),
        "r": ("in_2b", "ims_rejected"),
        "p": ("in_2b", "ims_pending"),
        "n": ("in_2b", None),
    }


def test_G32_effects_skip_value_mismatch():
    assert apply_effects(reconcile([book()], [doc(cgst="91.00")])) == []
