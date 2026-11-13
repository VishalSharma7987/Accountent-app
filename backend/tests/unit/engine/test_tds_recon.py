"""Package E: 26AS <-> books matching (T-42, T-43). Literal rule rows and hand-made figures; expected values typed by hand."""

from datetime import date
from decimal import Decimal as D

from app.engine.tds_recon import (
    BookEntry,
    RecLink,
    Row26,
    SectionMap,
    map_section,
    normalise_section,
    reconcile,
)

SECTIONS = [
    SectionMap("contractor", "194C"), SectionMap("contractor", "393(1)"),  # new Act table row shared with other natures
    SectionMap("professional_fees", "194J(b)"), SectionMap("professional_fees", "393(1)"),
]
PAN_A, PAN_B = "AAAPA1111A", "BBBPB2222B"
TOL = D("1.00")


def row(n, pan, section, on, paid, tax, tan="MUMA12345B"):
    return Row26(f"r{n}", n, tan, "Deductor", pan, section, on, D(paid), D(tax), D(tax))


def book(i, pan, nature, on, paid, tax, section="194C"):
    return BookEntry(i, pan, nature, f"Party {i}", section, on, D(paid), D(tax))


def run(rows, books, links=(), side="deductor", known=(PAN_A, PAN_B), tol=TOL):
    return reconcile(side, rows, books, SECTIONS, set(known), list(links), tol)


def test_T42_matched_by_pan_section_and_month():
    result = run([row(1, PAN_A, "194C", date(2026, 4, 20), "100000.00", "1000.00")],
                 [book("i1", PAN_A, "contractor", date(2026, 4, 18), "100000.00", "1000.00")])
    assert result.summary == {"matched": 1, "amount_mismatch": 0, "only_in_books": 0, "only_in_26as": 0, "date_mismatch": 0}
    assert result.rows[0].difference == D("0.00") and result.rows[0].section_mapping_status == "mapped"


def test_T42_amount_within_tolerance_is_matched_and_outside_is_mismatch():
    inside = run([row(1, PAN_A, "194C", date(2026, 4, 20), "100000.00", "1000.00")],
                 [book("i1", PAN_A, "contractor", date(2026, 4, 20), "100000.00", "999.50")])
    assert inside.rows[0].cls == "matched" and inside.rows[0].difference == D("0.50")
    outside = run([row(1, PAN_A, "194C", date(2026, 4, 20), "100000.00", "1000.00")],
                  [book("i1", PAN_A, "contractor", date(2026, 4, 20), "90000.00", "900.00")])
    assert outside.rows[0].cls == "amount_mismatch"
    assert (outside.rows[0].difference, outside.rows[0].paid_difference) == (D("100.00"), D("10000.00"))


def test_T42_same_amount_in_another_month_is_date_mismatch():
    result = run([row(1, PAN_A, "194C", date(2026, 5, 2), "100000.00", "1000.00")],
                 [book("i1", PAN_A, "contractor", date(2026, 4, 28), "100000.00", "1000.00")])
    assert result.rows[0].cls == "date_mismatch" and result.rows[0].difference == D("0.00")


def test_T42_only_in_books_and_only_in_26as():
    result = run([row(1, PAN_A, "194JB", date(2026, 4, 20), "50000.00", "5000.00")],
                 [book("i1", PAN_B, "contractor", date(2026, 4, 20), "100000.00", "1000.00")])
    assert result.summary == {"matched": 0, "amount_mismatch": 0, "only_in_books": 1, "only_in_26as": 1, "date_mismatch": 0}
    only26 = next(r for r in result.rows if r.cls == "only_in_26as")
    assert only26.reason == "not_in_books" and only26.book is None


def test_T42_old_and_new_code_both_map_to_the_same_nature():
    assert map_section("194C", SECTIONS) == ("mapped", "contractor")
    assert map_section(" Section 194-c ", SECTIONS) == ("mapped", "contractor")
    assert normalise_section("393 (1)") == "3931"
    assert normalise_section("194JA") == normalise_section("194J(a)") == "194JA"
    assert map_section("194J", SECTIONS) == ("unmapped", None)  # a printed 194J without the clause maps to nothing: reported, never guessed


def test_T43_unmapped_section_is_reported_never_guessed():
    result = run([row(1, PAN_A, "194Z", date(2026, 4, 20), "100.00", "10.00")],
                 [book("i1", PAN_A, "contractor", date(2026, 4, 20), "100.00", "10.00")])
    assert [(r.cls, r.section_mapping_status, r.reason) for r in result.rows if r.row] == [("only_in_26as", "unmapped", "unmapped_section")]
    assert result.summary["only_in_books"] == 1


def test_T43_section_shared_by_several_natures_is_ambiguous_not_matched():
    result = run([row(1, PAN_A, "393(1)", date(2026, 4, 20), "100.00", "10.00")],
                 [book("i1", PAN_A, "contractor", date(2026, 4, 20), "100.00", "10.00")])
    first = next(r for r in result.rows if r.row)
    assert (first.cls, first.section_mapping_status, first.reason) == ("only_in_26as", "ambiguous", "ambiguous_section")


def test_T43_unknown_pan_is_reported():
    result = run([row(1, "CCCPC3333C", "194C", date(2026, 4, 20), "100.00", "10.00")], [])
    assert (result.rows[0].cls, result.rows[0].reason) == ("only_in_26as", "unknown_pan")
    blank = run([row(1, None, "194C", date(2026, 4, 20), "100.00", "10.00")], [])
    assert blank.rows[0].reason == "unknown_pan"


def test_T43_book_item_of_deductee_without_pan_is_reported_as_pan_missing():
    result = run([], [book("i1", None, "contractor", date(2026, 4, 20), "100.00", "10.00")])
    assert (result.rows[0].cls, result.rows[0].reason) == ("only_in_books", "pan_missing")


def test_T42_two_rows_same_key_pair_one_to_one_closest_amount_first():
    rows = [row(1, PAN_A, "194C", date(2026, 4, 5), "1.00", "500.00"), row(2, PAN_A, "194C", date(2026, 4, 25), "1.00", "700.00")]
    books = [book("i1", PAN_A, "contractor", date(2026, 4, 25), "1.00", "700.00"), book("i2", PAN_A, "contractor", date(2026, 4, 5), "1.00", "500.00")]
    result = run(rows, books)
    pairs = {r.row.row_no: r.book.book_id for r in result.rows}
    assert pairs == {1: "i2", 2: "i1"} and result.summary["matched"] == 2


def test_T42_one_book_entry_cannot_match_two_rows():
    rows = [row(1, PAN_A, "194C", date(2026, 4, 5), "1.00", "500.00"), row(2, PAN_A, "194C", date(2026, 4, 6), "1.00", "500.00")]
    result = run(rows, [book("i1", PAN_A, "contractor", date(2026, 4, 5), "1.00", "500.00")])
    assert result.summary["matched"] == 1 and result.summary["only_in_26as"] == 1


def test_T43_manual_link_fixes_the_pair_and_still_reports_the_difference():
    rows = [row(1, "CCCPC3333C", "194Z", date(2026, 6, 1), "100.00", "10.00")]
    books = [book("i1", PAN_A, "contractor", date(2026, 4, 20), "200.00", "4.00")]
    link = RecLink("l1", "r1", "i1", "accepted_difference", "same bill, TDS rate mix-up")
    result = run(rows, books, [link])
    only = result.rows[0]
    assert (only.cls, only.link_id, only.link_kind, only.difference, only.paid_difference) == ("matched", "l1", "accepted_difference", D("6.00"), D("-100.00"))
    assert result.summary["matched"] == 1 and result.summary["only_in_books"] == 0


def test_T43_link_to_a_vanished_book_entry_is_ignored_and_flagged():
    result = run([row(1, PAN_A, "194C", date(2026, 4, 20), "1.00", "10.00")], [], [RecLink("l1", "r1", "gone", "manual", "x")])
    assert result.rows[0].cls == "only_in_26as" and result.rows[0].link_stale is True


def test_T42_deductee_side_matches_on_month_and_amount_only():
    rows = [row(1, None, "194C", date(2026, 4, 20), "100000.00", "1000.00"), row(2, None, "194JB", date(2026, 5, 10), "50000.00", "5000.00")]
    books = [BookEntry("v1", None, None, None, None, date(2026, 4, 25), D("0.00"), D("1000.00"), voucher_id="v1"),
             BookEntry("v2", None, None, None, None, date(2026, 6, 2), D("0.00"), D("5000.00"), voucher_id="v2")]
    result = run(rows, books, side="deductee", known=())
    classes = {r.row.row_no: (r.cls, r.section_mapping_status) for r in result.rows}
    assert classes == {1: ("matched", "not_applicable"), 2: ("date_mismatch", "not_applicable")}


def test_T42_empty_inputs_give_zero_summary():
    result = run([], [])
    assert result.rows == [] and result.summary == {"matched": 0, "amount_mismatch": 0, "only_in_books": 0, "only_in_26as": 0, "date_mismatch": 0}
