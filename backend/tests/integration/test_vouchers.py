"""Step 1.5: voucher lifecycle service (create draft, edit, approve, post, reverse) against the test schema."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import connection, migrate
from app.engine.models import ValidationError, VoucherDraft, VoucherLine
from app.services import client_setup, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal
APRIL_5 = date(2026, 4, 5)


@dataclass
class World:
    client_id: object
    fy_id: object
    ids: dict


def make_world(conn, name="ABC Traders") -> World:
    created = client_setup.create_client(
        conn, ClientProfile(name, "proprietorship", "trading", "regular"),
        fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
    )
    ids = dict(created.ledger_ids)
    for ledger, group in (
        ("HDFC Bank", "bank_accounts"), ("Rahul Enterprises", "sundry_debtors"),
        ("Sharma Suppliers", "sundry_creditors"), ("Outstanding Rent", "current_liabilities"),
    ):
        ids[ledger] = client_setup.add_ledger(conn, created.client_id, ledger, group, actor="setup")
    return World(created.client_id, created.financial_year_id, ids)


def vdraft(w, vtype, lines, *, on=APRIL_5, narration="Test voucher", reference_no=None, party=None, override=None):
    """lines = [(ledger name, debit, credit)]"""
    return VoucherDraft(
        w.client_id, vtype, on, narration, reference_no, w.ids[party] if party else None,
        tuple(VoucherLine(w.ids[name], dr, cr) for name, dr, cr in lines), override,
    )


def payment(w, amount="10000", **kw):
    return vdraft(w, "payment", [("Rent", amount, None), ("Cash", None, amount)], **kw)


def purchase(w, amount="50000", reference="SUP/889", **kw):
    return vdraft(w, "purchase", [("Purchases", amount, None), ("Sharma Suppliers", None, amount)],
                  reference_no=reference, party="Sharma Suppliers", **kw)


def q(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def count(conn, table):
    return scalar(conn, f"SELECT count(*) FROM {table}")


def row(conn, voucher_id):
    return q(conn, "SELECT status, voucher_number, narration, approved_by, posted_by, reverses_voucher_id, "
                   "reversed_by_voucher_id, duplicate_override_reason, created_by FROM vouchers WHERE id = :id", id=voucher_id)[0]


def lines_of(conn, voucher_id):
    return q(conn, "SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                   "WHERE vl.voucher_id = :id ORDER BY vl.line_no", id=voucher_id)


def audit_rows(conn, entity_id):
    return q(conn, "SELECT action, actor, old_data, new_data FROM audit_log WHERE entity_id = :id ORDER BY id", id=entity_id)


def new_draft(conn, w, d=None):
    result = vouchers.create_draft(conn, d or payment(w), actor="tester")
    assert result.errors == []
    return result.voucher_id


def new_approved(conn, w, d=None):
    vid = new_draft(conn, w, d)
    vouchers.approve(conn, vid, actor="approver")
    return vid


def new_posted(conn, w, d=None):
    vid = new_approved(conn, w, d)
    vouchers.post(conn, vid, actor="poster")
    return vid


@pytest.fixture(scope="module")
def shared_worlds(test_engine, test_conn):
    """Two committed clients (with ledgers) built ONCE for the module: the tests themselves run in rolled-back
    transactions, so only vouchers and small changes come and go. Cleaned (guarded) when the module ends."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        worlds = (make_world(conn, "ABC Traders"), make_world(conn, "Other Client"))
    yield worlds
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def w(shared_worlds):
    return shared_worlds[0]


@pytest.fixture
def other(shared_worlds):
    return shared_worlds[1]


def rule_ids(errors: list[ValidationError]):
    return [(e.rule_id, e.line_no) for e in errors]


# ============================================================================================= create_draft


def test_create_draft_saves_a_valid_voucher_as_draft_without_a_number(svc_conn, w):
    result = vouchers.create_draft(svc_conn, payment(w, narration="April rent"), actor="clerk")
    assert result.errors == [] and result.voucher_id is not None
    assert row(svc_conn, result.voucher_id) == ("draft", None, "April rent", None, None, None, None, None, "clerk")
    assert lines_of(svc_conn, result.voucher_id) == [("Rent", D("10000"), D("0")), ("Cash", D("0"), D("10000"))]


def test_create_draft_logs_the_creation_with_the_lines(svc_conn, w):
    vid = new_draft(svc_conn, w)
    [(action, actor, old, new)] = audit_rows(svc_conn, vid)
    assert (action, actor, old) == ("create", "tester", None)
    assert new["voucher_type"] == "payment" and new["voucher_date"] == "2026-04-05" and new["status"] == "draft"
    assert [(x["line_no"], x["debit"], x["credit"]) for x in new["lines"]] == [(1, "10000.00", "0.00"), (2, "0.00", "10000.00")]


def test_create_draft_stores_the_party_reference_and_financial_year(svc_conn, w):
    vid = new_draft(svc_conn, w, purchase(w))
    data = q(svc_conn, "SELECT reference_no, party_ledger_id, financial_year_id, voucher_type FROM vouchers WHERE id = :id", id=vid)[0]
    assert data == ("SUP/889", w.ids["Sharma Suppliers"], w.fy_id, "purchase")


def test_create_draft_with_rule_errors_returns_all_of_them_and_saves_nothing(svc_conn, w):
    bad = vdraft(w, "payment", [("Rent", "10000", None), ("Cash", None, "9000")], narration="", on=date(2027, 4, 1))
    result = vouchers.create_draft(svc_conn, bad, actor="tester")
    assert result.voucher_id is None
    assert rule_ids(result.errors) == [("V-04", None), ("V-06", None), ("V-09", None)]
    assert result.errors[0].message == "Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)"
    assert [count(svc_conn, t) for t in ("vouchers", "voucher_lines")] == [0, 0]
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity = 'voucher'") == 0


def test_create_draft_refuses_a_date_in_a_locked_period(svc_conn, w):
    svc_conn.execute(text("UPDATE periods SET status = 'locked', locked_at = now(), locked_by = 'x' "
                          "WHERE financial_year_id = :fy AND period_start = '2026-04-01'"), {"fy": w.fy_id})
    result = vouchers.create_draft(svc_conn, payment(w), actor="tester")
    assert rule_ids(result.errors) == [("V-07", None)]
    assert result.errors[0].message == "The period 01-04-2026 to 30-04-2026 is locked."


def test_create_draft_refuses_another_clients_ledger(svc_conn, w, other):
    bad = VoucherDraft(w.client_id, "payment", APRIL_5, "n", None, None,
                       (VoucherLine(w.ids["Rent"], "5", None), VoucherLine(other.ids["Cash"], None, "5")))
    result = vouchers.create_draft(svc_conn, bad, actor="tester")
    assert rule_ids(result.errors) == [("V-05", 2)]
    assert result.errors[0].message == "Line 2: ledger 'Cash' belongs to another client."


def test_create_draft_refuses_bad_amounts_and_unknown_client(svc_conn, w):
    result = vouchers.create_draft(svc_conn, vdraft(w, "payment", [("Rent", "10.005", None), ("Cash", None, "10.005")]), actor="tester")
    assert rule_ids(result.errors) == [("V-03", 1), ("V-03", 2)]
    unknown = VoucherDraft("00000000-0000-0000-0000-000000000000", "payment", APRIL_5, "n", None, None, ())
    with pytest.raises(ServiceError) as info:
        vouchers.create_draft(svc_conn, unknown, actor="tester")
    assert info.value.code == "not_found"


def test_create_draft_needs_an_actor(svc_conn, w):
    with pytest.raises(ServiceError) as info:
        vouchers.create_draft(svc_conn, payment(w), actor=" ")
    assert info.value.code == "invalid_actor"


def test_V10_a_possible_duplicate_is_returned_as_an_error_and_not_saved(svc_conn, w):
    first = new_draft(svc_conn, w, purchase(w))
    result = vouchers.create_draft(svc_conn, purchase(w, reference="sup/889 "), actor="tester")
    assert result.voucher_id is None
    assert [(e.rule_id, e.line_no) for e in result.errors] == [("V-10", None)]
    assert result.errors[0].message == (
        "A Purchase voucher with Reference No 'sup/889' and amount 50,000.00 for this party already exists: "
        "a draft dated 05-04-2026. Save it anyway only with a reason."
    )
    assert count(svc_conn, "vouchers") == 1 and first is not None


def test_V10_message_names_the_posted_voucher_number(svc_conn, w):
    new_posted(svc_conn, w, purchase(w))
    result = vouchers.create_draft(svc_conn, purchase(w), actor="tester")
    assert "already exists: PUR/2026-27/0001 dated 05-04-2026." in result.errors[0].message


def test_V10_override_reason_saves_the_duplicate_and_stores_the_reason(svc_conn, w):
    new_draft(svc_conn, w, purchase(w))
    result = vouchers.create_draft(svc_conn, purchase(w, override="Supplier billed twice, both genuine"), actor="tester")
    assert result.errors == []
    assert row(svc_conn, result.voucher_id)[7] == "Supplier billed twice, both genuine"
    assert count(svc_conn, "vouchers") == 2


def test_V10_a_different_amount_or_reference_is_not_a_duplicate(svc_conn, w):
    new_draft(svc_conn, w, purchase(w))
    assert vouchers.create_draft(svc_conn, purchase(w, amount="50001"), actor="t").errors == []
    assert vouchers.create_draft(svc_conn, purchase(w, reference="SUP/890"), actor="t").errors == []


# ============================================================================================= update_draft


def test_update_draft_replaces_the_header_and_lines_and_logs_old_and_new(svc_conn, w):
    vid = new_draft(svc_conn, w, payment(w, narration="First"))
    result = vouchers.update_draft(svc_conn, vid, payment(w, amount="2500.50", narration="Second", reference_no="CHQ-1"), actor="editor")
    assert result.errors == [] and result.voucher_id == vid
    assert row(svc_conn, vid)[:3] == ("draft", None, "Second")
    assert lines_of(svc_conn, vid) == [("Rent", D("2500.50"), D("0")), ("Cash", D("0"), D("2500.50"))]
    action, actor, old, new = audit_rows(svc_conn, vid)[-1]
    assert (action, actor) == ("update", "editor")
    assert old["narration"] == "First" and new["narration"] == "Second"
    assert old["lines"][0]["debit"] == "10000.00" and new["lines"][0]["debit"] == "2500.50"


def test_update_draft_with_errors_changes_nothing(svc_conn, w):
    vid = new_draft(svc_conn, w)
    result = vouchers.update_draft(svc_conn, vid, vdraft(w, "payment", [("Rent", "5", None), ("Cash", None, "4")]), actor="editor")
    assert rule_ids(result.errors) == [("V-04", None)]
    assert lines_of(svc_conn, vid) == [("Rent", D("10000"), D("0")), ("Cash", D("0"), D("10000"))]
    assert len(audit_rows(svc_conn, vid)) == 1


def test_update_draft_does_not_clash_with_its_own_reference(svc_conn, w):
    vid = new_draft(svc_conn, w, purchase(w))
    result = vouchers.update_draft(svc_conn, vid, purchase(w, narration="Edited"), actor="editor")
    assert result.errors == []


@pytest.mark.parametrize("target", ["approved", "posted"])
def test_update_draft_refuses_vouchers_that_are_not_drafts(svc_conn, w, target):
    vid = new_approved(svc_conn, w) if target == "approved" else new_posted(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.update_draft(svc_conn, vid, payment(w, narration="Changed"), actor="editor")
    assert info.value.code == "not_draft"
    assert info.value.message.startswith(f"Only a draft voucher can be edited; this voucher is {target}.")
    assert row(svc_conn, vid)[2] == "Test voucher"


def test_update_draft_cannot_move_a_voucher_to_another_client(svc_conn, w, other):
    vid = new_draft(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.update_draft(svc_conn, vid, payment(other), actor="editor")
    assert info.value.code == "client_mismatch"


def test_update_draft_of_an_unknown_voucher(svc_conn, w):
    with pytest.raises(ServiceError) as info:
        vouchers.update_draft(svc_conn, "00000000-0000-0000-0000-000000000000", payment(w), actor="editor")
    assert info.value.code == "not_found"


# ============================================================================================= delete_draft


def test_delete_draft_removes_the_voucher_and_its_lines_and_logs_it(svc_conn, w):
    vid = new_draft(svc_conn, w)
    vouchers.delete_draft(svc_conn, vid, actor="clerk")
    assert [count(svc_conn, t) for t in ("vouchers", "voucher_lines")] == [0, 0]
    action, actor, old, new = audit_rows(svc_conn, vid)[-1]
    assert (action, actor, new) == ("delete", "clerk", None)
    assert old["narration"] == "Test voucher" and len(old["lines"]) == 2


@pytest.mark.parametrize("target", ["approved", "posted"])
def test_delete_draft_refuses_vouchers_that_are_not_drafts(svc_conn, w, target):
    vid = new_approved(svc_conn, w) if target == "approved" else new_posted(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.delete_draft(svc_conn, vid, actor="clerk")
    assert info.value.code == "not_draft"
    assert count(svc_conn, "vouchers") == 1


# =============================================================================================== approve


def test_approve_moves_a_draft_to_approved_and_logs_it(svc_conn, w):
    vid = new_draft(svc_conn, w)
    vouchers.approve(svc_conn, vid, actor="partner")
    status, number, _, approved_by, *_ = row(svc_conn, vid)
    assert (status, number, approved_by) == ("approved", None, "partner")
    assert scalar(svc_conn, "SELECT approved_at IS NOT NULL FROM vouchers WHERE id = :id", id=vid)
    action, actor, old, new = audit_rows(svc_conn, vid)[-1]
    assert (action, actor, old, new) == ("approve", "partner", {"status": "draft"}, {"status": "approved"})


def test_approve_checks_the_rules_again_a_period_locked_since_creation_blocks_it(svc_conn, w):
    vid = new_draft(svc_conn, w)
    svc_conn.execute(text("UPDATE periods SET status = 'locked' WHERE financial_year_id = :fy AND period_start = '2026-04-01'"), {"fy": w.fy_id})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.approve(svc_conn, vid, actor="partner")
    assert rule_ids(info.value.errors) == [("V-07", None)]
    assert row(svc_conn, vid)[0] == "draft"


def test_approve_catches_a_ledger_deactivated_since_creation(svc_conn, w):
    vid = new_draft(svc_conn, w)
    svc_conn.execute(text("UPDATE ledgers SET is_active = false WHERE id = :id"), {"id": w.ids["Rent"]})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.approve(svc_conn, vid, actor="partner")
    assert info.value.errors[0].message == "Line 1: ledger 'Rent' is inactive."


@pytest.mark.parametrize("state", ["approved", "posted"])
def test_approve_only_accepts_drafts(svc_conn, w, state):
    vid = new_approved(svc_conn, w) if state == "approved" else new_posted(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.approve(svc_conn, vid, actor="partner")
    assert (info.value.code, info.value.message) == ("not_draft", f"Only a draft voucher can be approved (this one is {state}).")


# ========================================================================================= return_to_draft


def test_an_approved_voucher_goes_back_to_draft_and_can_then_be_edited_and_approved_again(svc_conn, w):
    vid = new_approved(svc_conn, w)
    vouchers.return_to_draft(svc_conn, vid, actor="partner")
    assert row(svc_conn, vid)[0] == "draft" and row(svc_conn, vid)[3] is None
    action, _, old, new = audit_rows(svc_conn, vid)[-1]
    assert (action, old, new) == ("return_to_draft", {"status": "approved"}, {"status": "draft"})
    assert vouchers.update_draft(svc_conn, vid, payment(w, amount="123", narration="Corrected"), actor="clerk").errors == []
    vouchers.approve(svc_conn, vid, actor="partner")
    assert row(svc_conn, vid)[:3] == ("approved", None, "Corrected")


@pytest.mark.parametrize("state", ["draft", "posted"])
def test_only_an_approved_voucher_can_go_back_to_draft(svc_conn, w, state):
    vid = new_draft(svc_conn, w) if state == "draft" else new_posted(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.return_to_draft(svc_conn, vid, actor="partner")
    assert info.value.code == "not_approved"


# =================================================================================================== post


def test_post_numbers_the_voucher_and_logs_it(svc_conn, w):
    vid = new_approved(svc_conn, w)
    number = vouchers.post(svc_conn, vid, actor="partner")
    assert number == "PAY/2026-27/0001"
    status, stored, _, _, posted_by, *_ = row(svc_conn, vid)
    assert (status, stored, posted_by) == ("posted", "PAY/2026-27/0001", "partner")
    action, _, old, new = audit_rows(svc_conn, vid)[-1]
    assert (action, old) == ("post", {"status": "approved"})
    assert new == {"status": "posted", "voucher_number": "PAY/2026-27/0001"}
    assert scalar(svc_conn, "SELECT last_number FROM voucher_number_sequences") == 1


def test_post_numbers_each_voucher_type_with_its_own_prefix_and_its_own_counter(svc_conn, w):
    cases = [
        ("contra", [("Cash", None, "100"), ("HDFC Bank", "100", None)], None, None, "CON"),
        ("payment", [("Rent", "100", None), ("Cash", None, "100")], None, None, "PAY"),
        ("receipt", [("Cash", "100", None), ("Rahul Enterprises", None, "100")], None, None, "REC"),
        ("sales", [("Rahul Enterprises", "100", None), ("Sales", None, "100")], None, "Rahul Enterprises", "SAL"),
        ("purchase", [("Purchases", "100", None), ("Sharma Suppliers", None, "100")], "B-1", "Sharma Suppliers", "PUR"),
        ("credit_note", [("Sales", "100", None), ("Rahul Enterprises", None, "100")], None, "Rahul Enterprises", "CRN"),
        ("debit_note", [("Sharma Suppliers", "100", None), ("Purchases", None, "100")], "B-1", "Sharma Suppliers", "DBN"),
        ("journal", [("Rent", "100", None), ("Outstanding Rent", None, "100")], None, None, "JRN"),
    ]
    numbers = []
    for vtype, lines, reference, party, prefix in cases:
        vid = new_approved(svc_conn, w, vdraft(w, vtype, lines, reference_no=reference, party=party))
        numbers.append(vouchers.post(svc_conn, vid, actor="partner"))
        assert numbers[-1] == f"{prefix}/2026-27/0001"
    second_payment = new_approved(svc_conn, w, payment(w, amount="7"))
    assert vouchers.post(svc_conn, second_payment, actor="partner") == "PAY/2026-27/0002"


def test_post_numbers_are_gapless_even_when_drafts_are_deleted(svc_conn, w):
    first, middle, last = (new_draft(svc_conn, w, payment(w, amount=a)) for a in ("1", "2", "3"))
    vouchers.delete_draft(svc_conn, middle, actor="clerk")
    for vid in (first, last):
        vouchers.approve(svc_conn, vid, actor="partner")
    assert [vouchers.post(svc_conn, v, actor="partner") for v in (first, last)] == ["PAY/2026-27/0001", "PAY/2026-27/0002"]


def test_V11_only_an_approved_voucher_can_be_posted(svc_conn, w):
    vid = new_draft(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.post(svc_conn, vid, actor="partner")
    assert (info.value.code, info.value.message) == ("not_approved", "Only an approved voucher can be posted (this one is draft).")
    posted = new_posted(svc_conn, w, payment(w, amount="9"))
    with pytest.raises(ServiceError) as info:
        vouchers.post(svc_conn, posted, actor="partner")
    assert info.value.message == "Only an approved voucher can be posted (this one is posted)."


def test_post_is_blocked_while_the_opening_balances_do_not_balance(svc_conn, w):
    client_setup.set_opening_balance(svc_conn, w.client_id, w.fy_id, w.ids["Cash"], "100", None, actor="setup")
    vid = new_approved(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.post(svc_conn, vid, actor="partner")
    assert (info.value.code, info.value.message) == (
        "openings_unbalanced",
        (
            "Opening balances do not balance: Debit 100.00 and Credit 0.00 are not equal (difference 100.00 Dr). "
            "Fix them before posting."
        ),
    )
    assert row(svc_conn, vid)[0] == "approved"
    client_setup.set_opening_balance(svc_conn, w.client_id, w.fy_id, w.ids["Ramesh Kumar Capital A/c"], None, "100", actor="setup")
    assert vouchers.post(svc_conn, vid, actor="partner") == "PAY/2026-27/0001"


def test_post_checks_the_period_again_one_locked_after_approval_blocks_it_and_burns_no_number(svc_conn, w):
    vid = new_approved(svc_conn, w)
    svc_conn.execute(text("UPDATE periods SET status = 'locked' WHERE financial_year_id = :fy AND period_start = '2026-04-01'"), {"fy": w.fy_id})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.post(svc_conn, vid, actor="partner")
    assert rule_ids(info.value.errors) == [("V-07", None)]
    assert row(svc_conn, vid)[0] == "approved"
    assert count(svc_conn, "voucher_number_sequences") == 0
    svc_conn.execute(text("UPDATE periods SET status = 'open' WHERE financial_year_id = :fy"), {"fy": w.fy_id})
    assert vouchers.post(svc_conn, vid, actor="partner") == "PAY/2026-27/0001"


def test_a_posted_voucher_cannot_be_edited_or_deleted_by_the_service_or_by_the_database(svc_conn, w):
    vid = new_posted(svc_conn, w)
    with pytest.raises(ServiceError):
        vouchers.update_draft(svc_conn, vid, payment(w, narration="x"), actor="clerk")
    with pytest.raises(ServiceError):
        vouchers.delete_draft(svc_conn, vid, actor="clerk")
    for sql in ("UPDATE vouchers SET narration = 'x' WHERE id = :id", "DELETE FROM vouchers WHERE id = :id",
                "UPDATE voucher_lines SET debit = 1 WHERE voucher_id = :id AND line_no = 1"):
        with pytest.raises(DBAPIError), svc_conn.begin_nested():
            svc_conn.execute(text(sql), {"id": vid})
    assert row(svc_conn, vid)[2] == "Test voucher"


# ================================================================================================= reverse


def test_reverse_posts_a_mirror_voucher_and_marks_the_original_reversed(svc_conn, w):
    original = new_posted(svc_conn, w, payment(w, narration="April rent"))
    reversal = vouchers.reverse(svc_conn, original, date(2026, 4, 25), "wrong month", actor="partner")

    assert row(svc_conn, original)[:2] == ("reversed", "PAY/2026-27/0001")
    assert row(svc_conn, original)[6] == reversal
    status, number, narration, _, _, reverses, reversed_by, _, _ = row(svc_conn, reversal)
    assert (status, number, narration, reverses, reversed_by) == (
        "posted", "PAY/2026-27/0002", "Reversal of PAY/2026-27/0001: wrong month", original, None)
    assert lines_of(svc_conn, reversal) == [("Rent", D("0"), D("10000")), ("Cash", D("10000"), D("0"))]
    assert q(svc_conn, "SELECT voucher_type, voucher_date, client_id = :c FROM vouchers WHERE id = :id", id=reversal, c=w.client_id) == [
        ("payment", date(2026, 4, 25), True)]


def test_reverse_writes_audit_rows_for_the_reversal_and_the_original(svc_conn, w):
    original = new_posted(svc_conn, w)
    reversal = vouchers.reverse(svc_conn, original, date(2026, 4, 25), "wrong month", actor="partner")
    assert [(a, actor) for a, actor, _, _ in audit_rows(svc_conn, reversal)] == [
        ("create", "partner"), ("approve", "partner"), ("post", "partner")]
    action, actor, old, new = audit_rows(svc_conn, original)[-1]
    assert (action, actor, old["status"], new["status"]) == ("reverse", "partner", "posted", "reversed")
    assert new["reversed_by"] == str(reversal) and new["reason"] == "wrong month"


def test_reverse_works_for_sales_and_purchase_whose_mirror_breaks_the_type_rule(svc_conn, w):
    sale = new_posted(svc_conn, w, vdraft(w, "sales", [("Rahul Enterprises", "500", None), ("Sales", None, "500")], party="Rahul Enterprises"))
    bought = new_posted(svc_conn, w, purchase(w))
    sale_reversal = vouchers.reverse(svc_conn, sale, date(2026, 4, 10), "cancelled sale", actor="partner")
    purchase_reversal = vouchers.reverse(svc_conn, bought, date(2026, 4, 10), "bill returned", actor="partner")
    assert lines_of(svc_conn, sale_reversal) == [("Rahul Enterprises", D("0"), D("500")), ("Sales", D("500"), D("0"))]
    assert row(svc_conn, purchase_reversal)[:2] == ("posted", "PUR/2026-27/0002")
    assert scalar(svc_conn, "SELECT reference_no FROM vouchers WHERE id = :id", id=purchase_reversal) == "SUP/889"
    assert scalar(svc_conn, "SELECT party_ledger_id FROM vouchers WHERE id = :id", id=purchase_reversal) == w.ids["Sharma Suppliers"]


def test_V12_a_voucher_can_be_reversed_only_once(svc_conn, w):
    original = new_posted(svc_conn, w)
    vouchers.reverse(svc_conn, original, date(2026, 4, 25), "first", actor="partner")
    with pytest.raises(ServiceError) as info:
        vouchers.reverse(svc_conn, original, date(2026, 4, 26), "second", actor="partner")
    assert (info.value.code, info.value.message) == (
        "already_reversed", "Voucher PAY/2026-27/0001 has already been reversed by PAY/2026-27/0002.")
    assert count(svc_conn, "vouchers") == 2


@pytest.mark.parametrize("state", ["draft", "approved"])
def test_only_a_posted_voucher_can_be_reversed(svc_conn, w, state):
    vid = new_draft(svc_conn, w) if state == "draft" else new_approved(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.reverse(svc_conn, vid, date(2026, 4, 25), "oops", actor="partner")
    assert (info.value.code, info.value.message) == ("not_posted", f"Only a posted voucher can be reversed (this one is {state}).")


def test_a_reversal_voucher_cannot_itself_be_reversed(svc_conn, w):
    original = new_posted(svc_conn, w)
    reversal = vouchers.reverse(svc_conn, original, date(2026, 4, 25), "wrong month", actor="partner")
    with pytest.raises(ServiceError) as info:
        vouchers.reverse(svc_conn, reversal, date(2026, 4, 26), "undo", actor="partner")
    assert info.value.code == "reversal_of_reversal"


def test_reversal_date_must_be_in_an_open_period_and_nothing_is_saved_otherwise(svc_conn, w):
    original = new_posted(svc_conn, w)
    svc_conn.execute(text("UPDATE periods SET status = 'locked' WHERE financial_year_id = :fy AND period_start = '2026-05-01'"), {"fy": w.fy_id})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.reverse(svc_conn, original, date(2026, 5, 10), "late fix", actor="partner")
    assert info.value.errors[0].message == "The period 01-05-2026 to 31-05-2026 is locked."
    assert row(svc_conn, original)[0] == "posted" and count(svc_conn, "vouchers") == 1


def test_reversal_date_outside_the_financial_year_is_refused(svc_conn, w):
    original = new_posted(svc_conn, w)
    with pytest.raises(VoucherRuleError) as info:
        vouchers.reverse(svc_conn, original, date(2027, 4, 2), "next year", actor="partner")
    assert rule_ids(info.value.errors) == [("V-06", None)]


def test_reverse_still_works_when_a_ledger_was_deactivated_after_the_original_was_posted(svc_conn, w):
    original = new_posted(svc_conn, w, payment(w, narration="April rent"))
    svc_conn.execute(text("UPDATE ledgers SET is_active = false WHERE id = :id"), {"id": w.ids["Rent"]})
    reversal = vouchers.reverse(svc_conn, original, date(2026, 4, 25), "wrong month", actor="partner")
    assert row(svc_conn, reversal)[0] == "posted" and row(svc_conn, original)[0] == "reversed"


def test_reverse_needs_a_reason(svc_conn, w):
    original = new_posted(svc_conn, w)
    with pytest.raises(ServiceError) as info:
        vouchers.reverse(svc_conn, original, date(2026, 4, 25), "  ", actor="partner")
    assert info.value.code == "reason_required"


def test_a_corrected_voucher_with_the_same_reference_can_be_entered_after_the_reversal(svc_conn, w):
    original = new_posted(svc_conn, w, purchase(w))
    assert vouchers.create_draft(svc_conn, purchase(w), actor="clerk").errors[0].rule_id == "V-10"
    vouchers.reverse(svc_conn, original, date(2026, 4, 25), "wrong amount", actor="partner")
    assert vouchers.create_draft(svc_conn, purchase(w), actor="clerk").errors == []


# ============================================================================================= get_voucher


def test_get_voucher_returns_the_voucher_with_named_lines(svc_conn, w):
    vid = new_posted(svc_conn, w, payment(w, narration="April rent"))
    view = vouchers.get_voucher(svc_conn, vid)
    assert (view.status, view.voucher_number, view.voucher_type, view.narration) == ("posted", "PAY/2026-27/0001", "payment", "April rent")
    assert [(x.line_no, x.ledger_name, x.debit, x.credit) for x in view.lines] == [
        (1, "Rent", D("10000.00"), D("0.00")), (2, "Cash", D("0.00"), D("10000.00"))]
    with pytest.raises(ServiceError) as info:
        vouchers.get_voucher(svc_conn, "00000000-0000-0000-0000-000000000000")
    assert info.value.code == "not_found"
