"""Phase 6 package A against the test schema: ledger roles, setup-ledgers, partners, deed terms, adjustment helpers (F-01 .. F-11).

Two committed worlds are built once per module (a partnership with partners A and B, and a proprietorship); each test runs in a
rolled-back transaction. Run through the lock script:
`C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_final_adjustments_db.py`.
Expected values are hand-calculated (see tests/unit/engine/test_final_adjustments.py).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.models import VoucherDraft, VoucherLine
from app.main import app
from app.services import client_setup, vouchers
from app.services import final_adjustments as svc
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal
H = {"X-User": "tester"}
ON = date(2027, 3, 31)


@dataclass
class World:
    client_id: object
    fy_id: object
    ids: dict
    partners: dict


def _add(conn, client_id, ids, name, group):
    if name not in ids:
        ids[name] = client_setup.add_ledger(conn, client_id, name, group, actor="setup")


def build_partnership(conn) -> World:
    c = client_setup.create_client(conn, ClientProfile("Alpha and Co", "partnership", "trading", "regular"), fy_start=date(2026, 4, 1),
                                   actor="setup", partners=["A", "B"])
    ids = dict(c.ledger_ids)
    for name, group in (("Rent Expense", "indirect_expenses"), ("Outstanding Expenses", "current_liabilities"),
                        ("Prepaid Expenses", "current_assets"), ("Mr A", "sundry_debtors"), ("Mr B", "sundry_debtors"),
                        ("Sharma Suppliers", "sundry_creditors"), ("A Drawings", "capital_account")):
        _add(conn, c.client_id, ids, name, group)
    for name, dr, cr in (("Mr A", "50000", None), ("Mr B", "30000", None), ("Cash", "420000", None),
                         ("A Capital A/c", None, "300000"), ("B Capital A/c", None, "200000")):
        client_setup.set_opening_balance(conn, c.client_id, c.financial_year_id, ids[name], dr, cr, actor="setup")
    svc.setup_ledgers(conn, c.client_id, c.financial_year_id, actor="setup")
    partners = {n: svc.create_partner(conn, c.client_id, n, ids[f"{n} Capital A/c"], ids[f"{n} Current A/c"], actor="setup") for n in ("A", "B")}
    svc.put_terms(conn, c.client_id, c.financial_year_id, [
        {"partner_id": partners["A"], "profit_share_percent": D("60"), "interest_on_capital_rate": D("10"), "interest_on_drawings_rate": D("12"),
         "remuneration_annual": D("60000"), "deed_reference": "Deed 01-04-2026 cl. 5"},
        {"partner_id": partners["B"], "profit_share_percent": D("40"), "interest_on_capital_rate": D("10"), "interest_on_drawings_rate": None,
         "remuneration_annual": None, "deed_reference": "Deed 01-04-2026 cl. 5"},
    ], actor="setup")
    return World(c.client_id, c.financial_year_id, ids, partners)


def build_proprietor(conn) -> World:
    c = client_setup.create_client(conn, ClientProfile("Solo Traders", "proprietorship", "trading", "regular"), fy_start=date(2026, 4, 1),
                                   actor="setup", proprietor_name="Ramesh")
    return World(c.client_id, c.financial_year_id, dict(c.ledger_ids), {})


@pytest.fixture(scope="module")
def worlds(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        built = (build_partnership(conn), build_proprietor(conn))
    yield built
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def w(worlds):
    return worlds[0]


@pytest.fixture
def solo(worlds):
    return worlds[1]


def req(w, adj_type, **kw):
    base = {"adj_type": adj_type, "as_on_date": ON, "basis_note": "Year-end working"}
    base.update(kw)
    for key in ("debit_ledger_id", "credit_ledger_id", "party_ledger_id"):
        if isinstance(base.get(key), str):
            base[key] = w.ids[base[key]]
    if isinstance(base.get("partner_id"), str):
        base["partner_id"] = w.partners[base["partner_id"]]
    return svc.AdjustmentRequest(**base)


def scalar(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


def lines_of(conn, voucher_id):
    rows = conn.execute(text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                             "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id}).all()
    return [(n, Decimal(d), Decimal(c)) for n, d, c in rows]


def post(conn, voucher_id):
    vouchers.approve(conn, voucher_id, actor="approver")
    vouchers.post(conn, voucher_id, actor="poster")


def rule_ids(exc: VoucherRuleError):
    return [e.rule_id for e in exc.errors]


# ============================================================================================ setup-ledgers and roles


def test_F02_setup_ledgers_created_roles_for_partnership_and_is_idempotent(svc_conn, w):
    roles = svc.get_ledger_roles(svc_conn, w.client_id)
    assert sorted(r["role"] for r in roles) == sorted([
        "trading_account", "profit_and_loss", "depreciation_expense", "accumulated_depreciation", "bad_debts", "doubtful_debts_expense",
        "provision_doubtful_debts", "stock_ledger", "interest_on_capital", "interest_on_drawings", "partner_remuneration"])
    again = svc.setup_ledgers(svc_conn, w.client_id, w.fy_id, actor="tester")
    assert len(again) == 11 and not any(r["created"] for r in again)
    stock = next(r for r in again if r["role"] == "stock_ledger")
    assert stock["ledger_name"] == "Opening Stock"   # the single existing Stock-in-hand ledger is reused, not duplicated


def test_F02_setup_ledgers_for_a_company_sets_the_existing_surplus_ledger(svc_conn):
    c = client_setup.create_client(svc_conn, ClientProfile("Beta Ltd", "company", "service", "regular"), fy_start=date(2026, 4, 1), actor="setup")
    rows = svc.setup_ledgers(svc_conn, c.client_id, c.financial_year_id, actor="tester")
    by_role = {r["role"]: r for r in rows}
    assert by_role["surplus_in_pl"]["ledger_name"] == "Surplus in Profit & Loss" and by_role["surplus_in_pl"]["created"] is False
    assert by_role["trading_account"]["created"] is True and by_role["trading_account"]["ledger_name"] == "Trading Account"
    assert "interest_on_capital" not in by_role
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'final_ledger_role'", c=c.client_id) == len(rows) == 9


def test_F02_put_role_wrong_group_conflict_and_entity_gate(svc_conn, w, solo):
    with pytest.raises(VoucherRuleError) as e:
        svc.set_ledger_role(svc_conn, w.client_id, "bad_debts", w.ids["Mr A"], actor="t")
    assert rule_ids(e.value) == ["F-02"]
    bad_ledger = scalar(svc_conn, "SELECT ledger_id FROM final_ledger_roles WHERE client_id = :c AND role = 'bad_debts'", c=w.client_id)
    with pytest.raises(ServiceError) as e2:   # the Bad Debts ledger already has a role: a second role is refused
        svc.set_ledger_role(svc_conn, w.client_id, "doubtful_debts_expense", bad_ledger, actor="t")
    assert e2.value.code == "role_conflict"
    with pytest.raises(VoucherRuleError) as e3:
        svc.set_ledger_role(svc_conn, solo.client_id, "interest_on_capital", solo.ids["Drawings A/c"], actor="t")
    assert rule_ids(e3.value) == ["F-09"]
    svc.set_ledger_role(svc_conn, w.client_id, "bad_debts", w.ids["Rent Expense"], actor="t")   # moving a role to another fitting ledger works
    assert scalar(svc_conn, "SELECT l.name FROM final_ledger_roles r JOIN ledgers l ON l.id = r.ledger_id WHERE r.client_id = :c AND r.role = 'bad_debts'",
                  c=w.client_id) == "Rent Expense"
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'final_ledger_role' AND action = 'update'", c=w.client_id) == 1


# ============================================================================================ partners and terms


def test_F62_partner_name_and_ledger_clash_and_entity(svc_conn, w, solo):
    extra = client_setup.add_ledger(svc_conn, w.client_id, "C Capital A/c", "capital_account", actor="t")
    with pytest.raises(ServiceError) as e:
        svc.create_partner(svc_conn, w.client_id, " a ", extra, None, actor="t")
    assert e.value.code == "partner_exists"
    with pytest.raises(ServiceError) as e:
        svc.create_partner(svc_conn, w.client_id, "C", w.ids["A Capital A/c"], None, actor="t")
    assert e.value.code == "partner_exists"
    with pytest.raises(VoucherRuleError) as e3:   # a partner's ledger must be under Capital Account
        svc.create_partner(svc_conn, w.client_id, "D", w.ids["Mr A"], None, actor="t")
    assert rule_ids(e3.value) == ["F-02"]
    with pytest.raises(ServiceError) as e:
        svc.create_partner(svc_conn, solo.client_id, "X", solo.ids["Drawings A/c"], None, actor="t")
    assert e.value.code == "invalid_entity"
    cid = svc.create_partner(svc_conn, w.client_id, "C", extra, None, actor="t")
    assert [p["name"] for p in svc.list_partners(svc_conn, w.client_id)] == ["A", "B", "C"]
    svc.update_partner(svc_conn, w.client_id, cid, {"is_active": False}, actor="t")
    assert next(p for p in svc.list_partners(svc_conn, w.client_id) if p["name"] == "C")["is_active"] is False
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'partner'", c=w.client_id) == 4   # A, B (setup), C create + update


def test_F62_partner_with_terms_cannot_change_ledgers(svc_conn, w):
    other = client_setup.add_ledger(svc_conn, w.client_id, "A New Capital", "capital_account", actor="t")
    with pytest.raises(ServiceError) as e:
        svc.update_partner(svc_conn, w.client_id, w.partners["A"], {"capital_ledger_id": other}, actor="t")
    assert e.value.code == "partner_in_use"


def test_F62_terms_get_put_and_share_must_be_100(svc_conn, w):
    got = svc.get_terms(svc_conn, w.client_id, w.fy_id)
    assert got["share_total"] == D("100.0000") and got["share_ok"] is True and [r["name"] for r in got["rows"]] == ["A", "B"]
    with pytest.raises(VoucherRuleError) as e:
        svc.put_terms(svc_conn, w.client_id, w.fy_id, [
            {"partner_id": w.partners["A"], "profit_share_percent": D("60.5")}, {"partner_id": w.partners["B"], "profit_share_percent": D("40")}], actor="t")
    assert rule_ids(e.value) == ["F-62"] and "100.5000" in e.value.errors[0].message
    assert svc.get_terms(svc_conn, w.client_id, w.fy_id)["share_total"] == D("100.0000")   # nothing was written
    with pytest.raises(ServiceError) as e2:   # a deed value without the deed reference
        svc.put_terms(svc_conn, w.client_id, w.fy_id, [
            {"partner_id": w.partners["A"], "profit_share_percent": D("50"), "remuneration_annual": D("1000")},
            {"partner_id": w.partners["B"], "profit_share_percent": D("50")}], actor="t")
    assert e2.value.code == "invalid_terms"
    svc.put_terms(svc_conn, w.client_id, w.fy_id, [
        {"partner_id": w.partners["A"], "profit_share_percent": D("33.3333")}, {"partner_id": w.partners["B"], "profit_share_percent": D("66.6667")}], actor="t")
    row = svc.get_terms(svc_conn, w.client_id, w.fy_id)["rows"][0]
    assert row["profit_share_percent"] == D("33.3333") and row["remuneration_annual"] is None
    audit = svc_conn.execute(text("SELECT old_data, new_data FROM audit_log WHERE client_id = :c AND entity = 'partner_fy_terms' ORDER BY id DESC LIMIT 1"),
                             {"c": w.client_id}).one()
    assert audit[0]["rows"][0]["deed_reference"] == "Deed 01-04-2026 cl. 5" and audit[1]["rows"][0]["profit_share_percent"] == "33.3333"


def test_F62_terms_of_a_closed_year_are_frozen(svc_conn, w, monkeypatch):
    monkeypatch.setattr(svc.final_hooks, "year_is_closed", lambda *a: True)
    with pytest.raises(ServiceError) as e:
        svc.put_terms(svc_conn, w.client_id, w.fy_id, [{"partner_id": w.partners["A"], "profit_share_percent": D("100")}], actor="t")
    assert e.value.code == "year_closed"


# ============================================================================================ adjustments


def test_F03_F11_outstanding_rent_creates_a_draft_journal_and_logs_it(svc_conn, w):
    out = svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", amount=D("5000"), debit_ledger_id="Rent Expense",
                                                credit_ledger_id="Outstanding Expenses"), actor="tester")
    assert out["amount"] == D("5000.00") and out["auto_reverse_voucher_id"] is None
    assert lines_of(svc_conn, out["voucher_id"]) == [("Rent Expense", D("5000.00"), D("0.00")), ("Outstanding Expenses", D("0.00"), D("5000.00"))]
    status, vtype, number, narration = svc_conn.execute(text("SELECT status, voucher_type, voucher_number, narration FROM vouchers WHERE id = :v"),
                                                        {"v": out["voucher_id"]}).one()
    assert (status, vtype, number) == ("draft", "journal", None) and "Year-end working" in narration
    rows = svc.list_adjustments(svc_conn, w.client_id, w.fy_id)
    assert [(r["adj_type"], r["amount"], r["voucher_status"]) for r in rows] == [("outstanding_expense", D("5000.00"), "draft")]
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity = 'adjustment_entry' AND entity_id = :i AND action = 'create'", i=out["adjustment_id"]) == 1


def test_F11_preview_writes_nothing(svc_conn, w):
    before = scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id)
    p = svc.preview(svc_conn, w.client_id, req(w, "prepaid_expense", amount=D("2000"), debit_ledger_id="Prepaid Expenses", credit_ledger_id="Rent Expense"))
    assert p["amount"] == D("2000.00") and [x["ledger_name"] for x in p["lines"]] == ["Prepaid Expenses", "Rent Expense"] and p["findings"] == []
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id) == before
    assert scalar(svc_conn, "SELECT count(*) FROM adjustment_entries WHERE client_id = :c", c=w.client_id) == 0


def test_F01_rule_errors_come_back_as_422_style_errors_and_write_nothing(svc_conn, w):
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", amount=D("10.005"), debit_ledger_id="Rent Expense",
                                              credit_ledger_id="Outstanding Expenses"), actor="t")
    assert rule_ids(e.value) == ["F-01"]
    with pytest.raises(VoucherRuleError) as e:   # V-06: a date outside every financial year of the client
        svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", as_on_date=date(2030, 3, 31), amount=D("5"), debit_ledger_id="Rent Expense",
                                              credit_ledger_id="Outstanding Expenses"), actor="t")
    assert rule_ids(e.value) == ["F-01"]
    assert scalar(svc_conn, "SELECT count(*) FROM adjustment_entries WHERE client_id = :c", c=w.client_id) == 0


def test_F10_duplicate_blocked_unless_a_reason_is_given_and_stored(svc_conn, w):
    kw = {"amount": D("5000"), "debit_ledger_id": "Rent Expense", "credit_ledger_id": "Outstanding Expenses"}
    svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")
    with pytest.raises(ServiceError) as e:
        svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")
    assert e.value.code == "adjustment_duplicate" and "5,000.00" in e.value.message
    warn = svc.preview(svc_conn, w.client_id, req(w, "outstanding_expense", **kw))["findings"]
    assert [f["rule_id"] for f in warn] == ["F-10"]
    out = svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", duplicate_reason="Two separate months", **kw), actor="t")
    stored = svc.list_adjustments(svc_conn, w.client_id, w.fy_id)
    assert len(stored) == 2 and next(a for a in stored if a["id"] == out["adjustment_id"])["params"]["duplicate_reason"] == "Two separate months"


def test_F10_a_reversed_adjustment_does_not_count_as_a_duplicate(svc_conn, w):
    kw = {"amount": D("5000"), "debit_ledger_id": "Rent Expense", "credit_ledger_id": "Outstanding Expenses"}
    first = svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")
    post(svc_conn, first["voucher_id"])
    vouchers.reverse(svc_conn, first["voucher_id"], ON, "Entered twice", actor="t")
    assert svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")["amount"] == D("5000.00")


def test_F04_auto_reversal_needs_the_next_year_then_creates_a_swapped_draft(svc_conn, w):
    kw = {"amount": D("5000"), "debit_ledger_id": "Rent Expense", "credit_ledger_id": "Outstanding Expenses", "auto_reverse_on": date(2027, 4, 1)}
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")
    assert rule_ids(e.value) == ["F-04"]
    assert scalar(svc_conn, "SELECT count(*) FROM adjustment_entries WHERE client_id = :c", c=w.client_id) == 0
    fy2 = uuid.uuid4()
    svc_conn.execute(text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:i, :c, '2027-04-01', '2028-03-31')"), {"i": fy2, "c": w.client_id})
    svc_conn.execute(text("INSERT INTO periods (client_id, financial_year_id, period_start, period_end) VALUES (:c, :i, '2027-04-01', '2027-04-30')"),
                     {"c": w.client_id, "i": fy2})
    out = svc.create(svc_conn, w.client_id, req(w, "outstanding_expense", **kw), actor="t")
    rev = out["auto_reverse_voucher_id"]
    assert lines_of(svc_conn, rev) == [("Rent Expense", D("0.00"), D("5000.00")), ("Outstanding Expenses", D("5000.00"), D("0.00"))]
    assert scalar(svc_conn, "SELECT voucher_date FROM vouchers WHERE id = :v", v=rev) == date(2027, 4, 1)
    svc.delete_adjustment(svc_conn, w.client_id, out["adjustment_id"], actor="t")   # a draft pair is deleted together
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE id IN (:a, :b)", a=out["voucher_id"], b=rev) == 0


def test_F11_delete_only_while_draft(svc_conn, w):
    kw = {"amount": D("2000"), "debit_ledger_id": "Prepaid Expenses", "credit_ledger_id": "Rent Expense"}
    gone = svc.create(svc_conn, w.client_id, req(w, "prepaid_expense", **kw), actor="t")
    svc.delete_adjustment(svc_conn, w.client_id, gone["adjustment_id"], actor="t")
    assert svc.list_adjustments(svc_conn, w.client_id, w.fy_id) == []
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity = 'adjustment_entry' AND action = 'delete'") == 1
    kept = svc.create(svc_conn, w.client_id, req(w, "prepaid_expense", **kw), actor="t")
    post(svc_conn, kept["voucher_id"])
    with pytest.raises(ServiceError) as e:
        svc.delete_adjustment(svc_conn, w.client_id, kept["adjustment_id"], actor="t")
    assert e.value.code == "adjustment_state"
    assert svc.list_adjustments(svc_conn, w.client_id, w.fy_id)[0]["voucher_number"] is not None


def test_F06_F05_bad_debt_then_provision_on_the_debtors_left(svc_conn, w):
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, w.client_id, req(w, "bad_debt", amount=D("50000.01"), party_ledger_id="Mr A"), actor="t")
    assert rule_ids(e.value) == ["F-06"]
    bad = svc.create(svc_conn, w.client_id, req(w, "bad_debt", amount=D("10000"), party_ledger_id="Mr A"), actor="t")
    assert lines_of(svc_conn, bad["voucher_id"]) == [("Bad Debts", D("10000.00"), D("0.00")), ("Mr A", D("0.00"), D("10000.00"))]
    warn = svc.preview(svc_conn, w.client_id, req(w, "provision_doubtful_debts", rate_percent=D("5")))
    assert warn["amount"] == D("4000.00") and [f["rule_id"] for f in warn["findings"]] == ["F-05"]   # 80,000 x 5%: the bad debt is not posted yet
    post(svc_conn, bad["voucher_id"])
    prov = svc.create(svc_conn, w.client_id, req(w, "provision_doubtful_debts", rate_percent=D("5")), actor="t")
    assert prov["amount"] == D("3500.00")   # (50,000 + 30,000 - 10,000) x 5%
    assert lines_of(svc_conn, prov["voucher_id"]) == [("Provision for Doubtful Debts Expense", D("3500.00"), D("0.00")),
                                                     ("Provision for Doubtful Debts", D("0.00"), D("3500.00"))]
    p = svc.list_adjustments(svc_conn, w.client_id, w.fy_id, "provision_doubtful_debts")[0]["params"]
    assert p["debtors"] == "70000.00" and p["required"] == "3500.00" and p["existing"] == "0.00"
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, w.client_id, req(w, "provision_doubtful_debts", rate_percent=D("5"), amount=D("3500")), actor="t")
    assert rule_ids(e.value) == ["F-05"]


def test_F07_F08_partner_helpers_use_the_deed_terms(svc_conn, w):
    ioc = svc.create(svc_conn, w.client_id, req(w, "interest_on_capital", partner_id="A"), actor="t")
    assert ioc["amount"] == D("30000.00")   # 3,00,000 x 10% for the whole year
    assert lines_of(svc_conn, ioc["voucher_id"]) == [("Interest on Capital", D("30000.00"), D("0.00")), ("A Current A/c", D("0.00"), D("30000.00"))]
    assert svc.preview(svc_conn, w.client_id, req(w, "interest_on_capital", partner_id="B"))["amount"] == D("20000.00")
    rem = svc.create(svc_conn, w.client_id, req(w, "partner_remuneration", partner_id="A", months=5), actor="t")
    assert rem["amount"] == D("25000.00")
    assert lines_of(svc_conn, rem["voucher_id"]) == [("Partners Remuneration", D("25000.00"), D("0.00")), ("A Current A/c", D("0.00"), D("25000.00"))]
    with pytest.raises(VoucherRuleError) as e:   # B has no remuneration in the deed
        svc.create(svc_conn, w.client_id, req(w, "partner_remuneration", partner_id="B"), actor="t")
    assert rule_ids(e.value) == ["F-08"]
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, w.client_id, req(w, "interest_on_capital", partner_id="A", amount=D("30000")), actor="t")
    assert rule_ids(e.value) == ["F-07"]


def test_F07_interest_on_drawings_reads_the_posted_drawings(svc_conn, w):
    drawing = vouchers.create_draft(svc_conn, VoucherDraft(
        w.client_id, "journal", date(2026, 10, 1), "Partner drawings settled against supplier", None, None,
        (VoucherLine(w.ids["A Drawings"], D("12000"), None), VoucherLine(w.ids["Sharma Suppliers"], None, D("12000")))), actor="t")
    assert drawing.errors == []
    post(svc_conn, drawing.voucher_id)
    out = svc.create(svc_conn, w.client_id, req(w, "interest_on_drawings", partner_id="A", party_ledger_id="A Drawings"), actor="t")
    assert out["amount"] == D("718.03")   # 12,000 x 182 days x 12% / 365
    assert lines_of(svc_conn, out["voucher_id"]) == [("A Current A/c", D("718.03"), D("0.00")), ("Interest on Drawings", D("0.00"), D("718.03"))]


def test_F09_proprietorship_is_refused_the_partner_helpers(svc_conn, solo):
    svc.setup_ledgers(svc_conn, solo.client_id, solo.fy_id, actor="t")
    r = svc.AdjustmentRequest("partner_remuneration", ON, "Year-end working")
    with pytest.raises(VoucherRuleError) as e:
        svc.create(svc_conn, solo.client_id, r, actor="t")
    assert rule_ids(e.value) == ["F-09"]


# ============================================================================================ HTTP


def test_api_routes_contract_shapes_and_error_statuses(svc_conn, w):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        base = f"/clients/{w.client_id}"
        roles = api.get(f"{base}/final/ledger-roles")
        assert roles.status_code == 200 and len(roles.json()) == 11
        terms = api.get(f"{base}/partners/terms", params={"financial_year_id": str(w.fy_id)})   # fixed path wins over /partners/{id}
        assert terms.status_code == 200 and terms.json()["share_total"] == "100.0000" and terms.json()["share_ok"] is True
        assert terms.json()["rows"][0]["remuneration_annual"] == "60000.00"
        assert len(api.get(f"{base}/partners").json()) == 2
        body = {"adj_type": "outstanding_expense", "as_on_date": "2027-03-31", "basis_note": "Rent for March", "amount": "5000",
                "debit_ledger_id": str(w.ids["Rent Expense"]), "credit_ledger_id": str(w.ids["Outstanding Expenses"])}
        p = api.post(f"{base}/adjustments/preview", json=body)
        assert p.status_code == 200 and p.json()["amount"] == "5000.00" and p.json()["lines"][0]["debit"] == "5000.00"
        created = api.post(f"{base}/adjustments", json=body, headers=H)
        assert created.status_code == 201 and created.json()["auto_reverse_voucher_id"] is None
        dup = api.post(f"{base}/adjustments", json=body, headers=H)
        assert dup.status_code == 409 and dup.json()["code"] == "adjustment_duplicate"
        listed = api.get(f"{base}/adjustments", params={"financial_year_id": str(w.fy_id)})
        assert listed.status_code == 200 and listed.json()[0]["voucher_status"] == "draft"
        typed = api.post(f"{base}/adjustments", json={"adj_type": "interest_on_capital", "as_on_date": "2027-03-31", "basis_note": "x", "amount": "1",
                                                       "partner_id": str(w.partners["A"])}, headers=H)
        assert typed.status_code == 422 and typed.json()["errors"][0]["rule_id"] == "F-07"
        wrong = api.put(f"{base}/final/ledger-roles/bad_debts", json={"ledger_id": str(w.ids["Mr A"])}, headers=H)
        assert wrong.status_code == 422 and wrong.json()["errors"][0]["rule_id"] == "F-02"
        assert api.delete(f"{base}/adjustments/{created.json()['adjustment_id']}", headers=H).status_code == 200
        assert api.put(f"{base}/partners/{w.partners['A']}", json={"is_active": False}, headers=H).status_code == 200
    finally:
        app.dependency_overrides.clear()
