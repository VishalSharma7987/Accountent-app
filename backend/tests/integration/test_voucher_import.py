"""Step 1.8: Excel voucher import service (dry run and commit) and vouchers.validate_draft."""

import io
from dataclasses import dataclass
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from xlsx_helpers import APRIL_5, GOOD_ROWS, inject_cached_value, make_xlsx

from app.db import connection, migrate
from app.engine.models import VoucherDraft, VoucherLine
from app.services import client_setup, voucher_import, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration


@dataclass
class World:
    client_id: object
    ids: dict


def build_world(conn, name="ABC Traders") -> World:
    created = client_setup.create_client(
        conn, ClientProfile(name, "proprietorship", "trading", "regular"),
        fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
    )
    ids = dict(created.ledger_ids)
    for ledger, group in (("Rahul Enterprises", "sundry_debtors"), ("Sharma Suppliers", "sundry_creditors")):
        ids[ledger] = client_setup.add_ledger(conn, created.client_id, ledger, group, actor="setup")
    return World(created.client_id, ids)


@pytest.fixture(scope="module")
def worlds(test_engine, test_conn):
    """Two committed clients built once; each test runs in a rolled-back transaction."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        pair = (build_world(conn), build_world(conn, "Other Client"))
    yield pair
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def w(worlds):
    return worlds[0]


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def issues(voucher):
    return [(e.rule_id, e.line_no, e.row, e.message) for e in voucher.errors]


def by_ref(result):
    return {v.ref_id: v for v in result.vouchers}


def row(ref, on, vtype, ledger, dr=None, cr=None, narration="Test", reference=None, party=None):
    return [ref, on, vtype, ledger, dr, cr, narration, reference, party]


# ========================================================================================== validate_draft


def draft(w, lines, *, vtype="payment", reference=None, party=None, narration="Test voucher"):
    return VoucherDraft(w.client_id, vtype, APRIL_5, narration, reference, w.ids[party] if party else None,
                        tuple(VoucherLine(w.ids[n], dr, cr) for n, dr, cr in lines))


def test_validate_draft_returns_the_errors_create_draft_would_return_and_saves_nothing(svc_conn, w):
    bad = draft(w, [("Rent", "10000", None), ("Cash", None, "9000")])
    errors = vouchers.validate_draft(svc_conn, bad)
    assert [(e.rule_id, e.message) for e in errors] == [
        ("V-04", "Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)")]
    assert vouchers.create_draft(svc_conn, bad, actor="t").errors == errors
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers") == 0
    assert vouchers.validate_draft(svc_conn, draft(w, [("Rent", "5", None), ("Cash", None, "5")])) == []
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity = 'voucher'") == 0


def test_validate_draft_includes_the_duplicate_check_and_can_ignore_the_voucher_being_edited(svc_conn, w):
    purchase = draft(w, [("Purchases", "500", None), ("Sharma Suppliers", None, "500")], vtype="purchase",
                     reference="SUP/1", party="Sharma Suppliers")
    first = vouchers.create_draft(svc_conn, purchase, actor="t").voucher_id
    assert [e.rule_id for e in vouchers.validate_draft(svc_conn, purchase)] == ["V-10"]
    assert vouchers.validate_draft(svc_conn, purchase, draft_id=first) == []


# ================================================================================================== dry run


def test_dry_run_of_a_correct_file_says_ok_for_every_voucher_and_saves_nothing(svc_conn, w):
    result = voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(GOOD_ROWS))
    assert [(v.ref_id, v.first_row, v.status, v.errors) for v in result.vouchers] == [
        ("V1", 2, "ok", []), ("V2", 4, "ok", [])]
    assert (result.ok_count, result.error_count) == (2, 0)
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers") == 0


def test_ledger_names_are_matched_ignoring_case_and_spaces_around_them(svc_conn, w):
    rows = [row("V1", APRIL_5, "payment", " RENT ", 100), row("V1", APRIL_5, "payment", "cash", None, 100)]
    assert voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)).vouchers[0].status == "ok"


def test_an_unknown_ledger_is_an_error_on_its_row_and_is_never_created(svc_conn, w):
    rows = [row("V1", APRIL_5, "payment", "Petrol", 100), row("V1", APRIL_5, "payment", "Cash", None, 100)]
    voucher = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)))["V1"]
    assert voucher.status == "error"
    assert issues(voucher) == [
        ("V-05", 1, 2, "Line 1: ledger 'Petrol' does not exist for this client; the import never creates ledgers.")]
    assert scalar(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c AND name = 'Petrol'", c=w.client_id) == 0


def test_a_ledger_of_another_client_counts_as_unknown(svc_conn, w, worlds):
    svc_conn.execute(text("UPDATE ledgers SET name = 'Their Only Ledger' WHERE id = :id"), {"id": worlds[1].ids["Rent"]})
    rows = [row("V1", APRIL_5, "payment", "Their Only Ledger", 100), row("V1", APRIL_5, "payment", "Cash", None, 100)]
    voucher = voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)).vouchers[0]
    assert [i[0] for i in issues(voucher)] == ["V-05"]


def test_rule_errors_are_mapped_to_the_excel_rows_of_the_lines_or_the_first_row(svc_conn, w):
    rows = [
        # V1 unbalanced -> voucher level -> first row (2)
        row("V1", APRIL_5, "payment", "Rent", 10000), row("V1", APRIL_5, "payment", "Cash", None, 9000),
        # V2 three decimals on its 2nd line -> that line's row (5)
        row("V2", APRIL_5, "payment", "Rent", 100), row("V2", APRIL_5, "payment", "Cash", None, "100.005"),
        # V3 no narration -> first row (6)
        row("V3", APRIL_5, "payment", "Rent", 100, None, ""), row("V3", APRIL_5, "payment", "Cash", None, 100, ""),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)))
    assert issues(result["V1"]) == [
        ("V-04", None, 2, "Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)")]
    assert issues(result["V2"]) == [("V-03", 2, 5, "Line 2: amount 100.005 has more than 2 decimal places.")]
    assert issues(result["V3"]) == [("V-09", None, 6, "Narration is required.")]
    assert all(v.status == "error" for v in result.values())


def test_party_and_reference_rules_apply_to_imports_too(svc_conn, w):
    rows = [
        row("V1", APRIL_5, "sales", "Cash", 100, None, "Cash sale", None, "Rahul Enterprises"),   # V-13
        row("V1", APRIL_5, "sales", "Sales", None, 100, "Cash sale", None, "Rahul Enterprises"),
        row("V2", APRIL_5, "purchase", "Purchases", 50, None, "Goods"),                              # V-14
        row("V2", APRIL_5, "purchase", "Cash", None, 50, "Goods"),
        row("V3", APRIL_5, "sales", "Cash", 5, None, "Sale", "INV", "Nobody Ltd"),                  # unknown party
        row("V3", APRIL_5, "sales", "Sales", None, 5, "Sale", "INV", "Nobody Ltd"),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)))
    assert issues(result["V1"]) == [("V-13", None, 2, "Party ledger 'Rahul Enterprises' is not in the voucher's lines.")]
    assert issues(result["V2"]) == [("V-14", None, 4, "A Purchase voucher needs the supplier's bill number in Reference No.")]
    assert issues(result["V3"]) == [
        ("V-05", None, 6, "The party ledger 'Nobody Ltd' does not exist for this client; the import never creates ledgers.")]


def test_file_format_problems_are_reported_per_voucher_with_their_row(svc_conn, w):
    rows = [
        row("V1", "April fifth", "payment", "Rent", 100), row("V1", "April fifth", "payment", "Cash", None, 100),
        row("V2", APRIL_5, "payment", "Rent", "=100+50"), row("V2", APRIL_5, "payment", "Cash", None, 150),
        row("V3", APRIL_5, "payment", "Rent", "1,000.50"), row("V3", APRIL_5, "payment", "Cash", None, "1000.50"),
    ]
    result = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)))
    assert result["V1"].status == "error" and issues(result["V1"])[0][2:] == (
        2, "date must be a real date, as an Excel date or text like 2026-04-05 or 05-04-2026")
    assert issues(result["V2"]) == [
        (None, None, 4, "debit holds a formula with no saved result; open the file in Excel, save it, and upload it again")]
    assert result["V3"].status == "ok"  # "1,000.50" text: the comma is stripped explicitly by the importer


def test_a_calculated_amount_that_is_not_2_decimals_is_rejected_by_the_engine_with_its_row(svc_conn, w):
    data = make_xlsx([row("V1", APRIL_5, "payment", "Rent", "placeholder"), row("V1", APRIL_5, "payment", "Cash", None, "0.3")])
    wb = load_workbook(io.BytesIO(data))
    wb.active["E2"] = "=0.1+0.2"
    out = io.BytesIO()
    wb.save(out)
    data = inject_cached_value(out.getvalue(), "E2", "0.30000000000000004")
    voucher = voucher_import.dry_run(svc_conn, w.client_id, data).vouchers[0]
    assert issues(voucher) == [
        ("V-03", 1, 2, "Line 1: amount 0.30000000000000004 has more than 2 decimal places.")]


def test_a_possible_duplicate_of_a_saved_voucher_is_an_error_because_the_sheet_has_no_override(svc_conn, w):
    vouchers.create_draft(svc_conn, draft(w, [("Rahul Enterprises", "5000.50", None), ("Sales", None, "5000.50")], vtype="sales",
                                          reference="INV-1", party="Rahul Enterprises", narration="Existing"), actor="t")
    voucher = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(GOOD_ROWS)))["V2"]
    assert [(i[0], i[2]) for i in issues(voucher)] == [("V-10", 4)]
    assert "already exists: a draft dated 05-04-2026" in voucher.errors[0].message


def test_a_voucher_that_repeats_an_earlier_voucher_of_the_same_file_is_a_duplicate(svc_conn, w):
    rows = GOOD_ROWS + [r[:0] + ["V3"] + r[1:] for r in GOOD_ROWS[2:]]
    result = by_ref(voucher_import.dry_run(svc_conn, w.client_id, make_xlsx(rows)))
    assert result["V2"].status == "ok"
    assert [(i[0], i[2]) for i in issues(result["V3"])] == [("V-10", 6)]
    assert issues(result["V3"])[0][3] == (
        "This voucher repeats voucher V2 of the same file: same type, party, Reference No 'INV-1' and amount 5,000.50.")


def test_dry_run_refuses_an_unreadable_file_and_an_unknown_client(svc_conn, w):
    with pytest.raises(ServiceError) as info:
        voucher_import.dry_run(svc_conn, w.client_id, b"not excel")
    assert (info.value.code, info.value.message) == ("invalid_file", "The upload is not a valid Excel (.xlsx) file.")
    with pytest.raises(ServiceError) as info:
        voucher_import.dry_run(svc_conn, "00000000-0000-0000-0000-000000000000", make_xlsx(GOOD_ROWS))
    assert info.value.code == "not_found"
    bad_header = make_xlsx(GOOD_ROWS, header=["a", "b"])
    with pytest.raises(ServiceError) as info:
        voucher_import.dry_run(svc_conn, w.client_id, bad_header)
    assert info.value.code == "invalid_file" and info.value.message.startswith("The first row of the sheet must be exactly:")


# ================================================================================================== commit


def test_commit_creates_drafts_for_every_ok_voucher_and_skips_the_bad_ones(svc_conn, w):
    rows = GOOD_ROWS + [row("V3", APRIL_5, "payment", "Rent", 10), row("V3", APRIL_5, "payment", "Cash", None, 9)]
    result = voucher_import.commit(svc_conn, w.client_id, make_xlsx(rows), None, actor="clerk")
    assert [c.ref_id for c in result.created] == ["V1", "V2"]
    assert [(s.ref_id, s.reason) for s in result.skipped] == [
        ("V3", "has errors: Debit 10.00 and Credit 9.00 are not equal (difference 1.00)")]
    saved = svc_conn.execute(text("SELECT id, status, voucher_number, created_by, narration FROM vouchers ORDER BY narration")).all()
    assert [(s[1], s[2], s[3], s[4]) for s in saved] == [("draft", None, "clerk", "April rent"), ("draft", None, "clerk", "Sale to Rahul")]
    assert {s[0] for s in saved} == {c.voucher_id for c in result.created}


def test_commit_never_approves_or_posts(svc_conn, w):
    voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), None, actor="clerk")
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE status <> 'draft'") == 0
    assert scalar(svc_conn, "SELECT count(*) FROM voucher_number_sequences") == 0
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE action IN ('approve', 'post')") == 0


def test_commit_stores_lines_party_and_reference_exactly(svc_conn, w):
    result = voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), ["V2"], actor="clerk")
    voucher_id = result.created[0].voucher_id
    assert svc_conn.execute(text("SELECT reference_no, party_ledger_id, voucher_date FROM vouchers WHERE id = :id"), {"id": voucher_id}).one() == (
        "INV-1", w.ids["Rahul Enterprises"], date(2026, 4, 6))
    lines = svc_conn.execute(text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                                  "WHERE vl.voucher_id = :id ORDER BY vl.line_no"), {"id": voucher_id}).all()
    assert [(n, f"{d:.2f}", f"{c:.2f}") for n, d, c in lines] == [
        ("Rahul Enterprises", "5000.50", "0.00"), ("Sales", "0.00", "5000.50")]


def test_commit_only_creates_the_selected_vouchers_and_explains_the_rest(svc_conn, w):
    result = voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), ["V2", "V9"], actor="clerk")
    assert [c.ref_id for c in result.created] == ["V2"]
    assert sorted((s.ref_id, s.reason) for s in result.skipped) == [("V1", "not selected"), ("V9", "not in the file")]
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers") == 1


def test_selecting_a_voucher_with_errors_skips_it_with_the_reason(svc_conn, w):
    rows = [row("V1", APRIL_5, "payment", "Petrol", 100), row("V1", APRIL_5, "payment", "Cash", None, 100)]
    result = voucher_import.commit(svc_conn, w.client_id, make_xlsx(rows), ["V1"], actor="clerk")
    assert result.created == []
    assert [(s.ref_id, s.reason) for s in result.skipped] == [
        ("V1", "has errors: Line 1: ledger 'Petrol' does not exist for this client; the import never creates ledgers.")]


def test_commit_writes_an_audit_row_for_every_created_draft(svc_conn, w):
    result = voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), None, actor="clerk")
    rows = svc_conn.execute(text("SELECT action, actor, entity FROM audit_log WHERE entity_id = ANY(:ids)"),
                            {"ids": [c.voucher_id for c in result.created]}).all()
    assert sorted(rows) == [("create", "clerk", "voucher")] * 2


def test_importing_the_same_file_twice_does_not_duplicate_vouchers_that_have_a_reference(svc_conn, w):
    first = voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), None, actor="clerk")
    second = voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), None, actor="clerk")
    assert [c.ref_id for c in first.created] == ["V1", "V2"]
    # V1 has no reference no, so V-10 cannot tell it is a repeat (by design); V2 has INV-1 and is refused
    assert [c.ref_id for c in second.created] == ["V1"]
    assert [s.ref_id for s in second.skipped] == ["V2"]
    assert second.skipped[0].reason.startswith("has errors: A Sales voucher with Reference No 'INV-1'")


def test_commit_needs_an_actor_and_refuses_unreadable_files(svc_conn, w):
    with pytest.raises(ServiceError) as info:
        voucher_import.commit(svc_conn, w.client_id, make_xlsx(GOOD_ROWS), None, actor=" ")
    assert info.value.code == "invalid_actor"
    with pytest.raises(ServiceError) as info:
        voucher_import.commit(svc_conn, w.client_id, b"junk", None, actor="clerk")
    assert info.value.code == "invalid_file"
