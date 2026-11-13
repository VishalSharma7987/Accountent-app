"""TDS deduction on vouchers against the test schema (Phase 4, package B): tax line, items, T-13, position, register.

Needs migrations 0012-0014 and seeds 0008-0009 (rule data) in the test schema. Masters (deductees, ledger roles, certificate,
buyer flag) are inserted here with plain SQL, so these tests do not depend on package A's services.
Expected figures are hand-calculated from the seeded rules: contractor 1% (individual / HUF) or 2% (others), no-PAN 20%,
single payment 30,000, annual 1,00,000, whole amount once crossed.
"""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.db import connection, migrate
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.tds_types import TdsLineIn
from app.main import app
from app.services import client_setup, tds_deduction, tds_hooks, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal
H = {"X-User": "tester"}


@dataclass
class World:
    client_id: object
    fy25: object
    fy26: object
    ids: dict


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("TDS Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2025, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
        )
        c = created.client_id
        ids = dict(created.ledger_ids)
        for name, group in (
            ("Contract Expense", "indirect_expenses"), ("Contractor Co", "sundry_creditors"), ("Ind Contractor", "sundry_creditors"),
            ("No PAN Co", "sundry_creditors"), ("TDS Payable", "duties_taxes"), ("Wrongly Placed", "indirect_expenses"),
            ("HDFC Bank", "bank_accounts"),
        ):
            ids[name] = client_setup.add_ledger(conn, c, name, group, actor="setup")
        fy26 = uuid.uuid4()
        conn.execute(text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:f, :c, '2026-04-01', '2027-03-31')"), {"f": fy26, "c": c})
        conn.execute(
            text("INSERT INTO periods (client_id, financial_year_id, period_start, period_end) SELECT :c, :f, d::date, "
                 "(d + interval '1 month' - interval '1 day')::date FROM generate_series('2026-04-01'::date, '2027-03-01'::date, '1 month') d"),
            {"c": c, "f": fy26},
        )
        for name, pan, status, kind in (("Contractor Co", "AAACC1234A", "valid", "company"), ("Ind Contractor", "ABCPK1234A", "valid", "individual"),
                                        ("No PAN Co", None, "missing", "company")):
            conn.execute(
                text("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (:l, :c, :p, :s, :t)"),
                {"l": ids[name], "c": c, "p": pan, "s": status, "t": kind},
            )
        conn.execute(text("INSERT INTO tds_ledger_roles (client_id, role, nature_key, ledger_id) VALUES (:c, 'tds_payable', NULL, :l)"),
                     {"c": c, "l": ids["TDS Payable"]})
        conn.execute(
            text("INSERT INTO tds_lower_deduction_certs (id, client_id, deductee_ledger_id, certificate_no, nature_key, rate, max_amount, valid_from, valid_to) "
                 "VALUES (:i, :c, :l, 'LDC/26/1', 'contractor', 1, 150000, '2026-04-01', '2027-03-31')"),
            {"i": uuid.UUID(int=77), "c": c, "l": ids["Contractor Co"]},
        )
        fy25 = conn.execute(text("SELECT id FROM financial_years WHERE client_id = :c AND start_date = '2025-04-01'"), {"c": c}).scalar_one()
        w = World(c, fy25, fy26, ids)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def purchase(w, who, amount, on, *, ref, pay=None, credit=None, cert=None, nature="contractor"):
    lines = (VoucherLine(w.ids["Contract Expense"], amount, None), VoucherLine(w.ids[who], None, amount))
    item = TdsLineIn(w.ids[who], nature, D(amount), credit, pay or (None if credit else on), cert)
    return VoucherDraft(w.client_id, "purchase", on, "Contract work", ref, w.ids[who], lines, tds=(item,))


def saved(conn, draft):
    result = vouchers.create_draft(conn, draft, actor="tester")
    assert result.errors == [], result.errors
    return result.voucher_id


def post_it(conn, vid):
    vouchers.approve(conn, vid, actor="approver")
    vouchers.post(conn, vid, actor="poster")


def lines_of(conn, vid):
    rows = conn.execute(
        text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id WHERE vl.voucher_id = :v ORDER BY vl.line_no"),
        {"v": vid},
    ).all()
    return [(n, d.quantize(D("0.01")), c.quantize(D("0.01"))) for n, d, c in rows]


def items_of(conn, vid):
    return conn.execute(
        text("SELECT act, section_ref, table_ref, rate_applied, rate_reason, taxable_base, tds_amount, tds_line_no, cumulative_before, "
             "cumulative_after, threshold_crossed, tax_already_on_base, lower_cert_id FROM tds_voucher_items WHERE voucher_id = :v ORDER BY item_no"),
        {"v": vid},
    ).all()


# ---- T-01: the Act follows the earlier date; the generated tax line ------------------------------------------------------
def test_T01_voucher_on_31_March_2026_is_1961_act_and_on_1_April_2026_is_2025_act(svc_conn, world):
    a = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 3, 31), ref="B-31"))
    b = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 4, 1), ref="B-01"))
    for vid in (a, b):
        assert lines_of(svc_conn, vid) == [
            ("Contract Expense", D("100000.00"), D("0.00")), ("Contractor Co", D("0.00"), D("98000.00")), ("TDS Payable", D("0.00"), D("2000.00"))]
    old, new = items_of(svc_conn, a)[0], items_of(svc_conn, b)[0]
    assert (old.act, old.section_ref, old.table_ref, old.rate_applied, old.tds_amount, old.tds_line_no) == ("it_act_1961", "194C", None, D("2"), D("2000.00"), 3)
    assert (new.act, new.section_ref, new.rate_applied, new.tds_amount) == ("it_act_2025", "393(1)", D("2"), D("2000.00"))
    assert new.table_ref is not None
    block = tds_hooks.load_tds(svc_conn, world.client_id, a)
    assert block["items"][0]["tds_amount"] == "2000.00" and block["items"][0]["verification_status"] == "pending"
    assert block["rule_status"]["worst"] == "pending" and block["rule_status"]["pending_sources"]


def test_T01_credit_in_March_and_payment_in_April_uses_the_earlier_date(svc_conn, world):
    vid = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 3, 28), ref="B-28", credit=date(2026, 3, 28), pay=date(2026, 4, 3)))
    row = items_of(svc_conn, vid)[0]
    assert (row.act, row.section_ref) == ("it_act_1961", "194C")


def test_T01_payment_date_outside_every_financial_year_of_the_client_is_refused(svc_conn, world):
    result = vouchers.create_draft(svc_conn, purchase(world, "Contractor Co", "100000", date(2025, 4, 10), pay=date(2025, 3, 20), ref="B-OLD"), actor="tester")
    assert [(e.rule_id, e.line_no) for e in result.errors] == [("T-01", 1)]


def test_T08_missing_pan_deducts_at_the_higher_rate(svc_conn, world):
    vid = saved(svc_conn, purchase(world, "No PAN Co", "100000", date(2026, 6, 10), ref="NP-1"))
    assert lines_of(svc_conn, vid)[1:] == [("No PAN Co", D("0.00"), D("80000.00")), ("TDS Payable", D("0.00"), D("20000.00"))]
    assert items_of(svc_conn, vid)[0].rate_reason == "no_pan"


def test_T14_payable_ledger_must_be_mapped_and_under_duties_and_taxes(svc_conn, world):
    svc_conn.execute(text("UPDATE tds_ledger_roles SET ledger_id = :l WHERE client_id = :c"), {"l": world.ids["Wrongly Placed"], "c": world.client_id})
    result = vouchers.create_draft(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-14"), actor="tester")
    assert [e.rule_id for e in result.errors] == ["T-14"]
    svc_conn.execute(text("DELETE FROM tds_ledger_roles WHERE client_id = :c"), {"c": world.client_id})
    result = vouchers.create_draft(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-14"), actor="tester")
    assert [e.rule_id for e in result.errors] == ["T-14"]


def test_T15_purchase_of_goods_without_the_buyer_flag_is_refused(svc_conn, world):
    d = purchase(world, "Contractor Co", "6000000", date(2026, 6, 10), ref="Q-1", nature="purchase_of_goods")
    assert [e.rule_id for e in vouchers.create_draft(svc_conn, d, actor="tester").errors] == ["T-15"]


def test_T09_party_without_a_deductee_row_is_refused(svc_conn, world):
    d = purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-9")
    other = TdsLineIn(world.ids["HDFC Bank"], "contractor", D("100000"), None, date(2026, 6, 10))
    assert [e.rule_id for e in vouchers.create_draft(svc_conn, dataclasses.replace(d, tds=(other,)), actor="tester").errors] == ["T-09"]


def test_T16_update_draft_replaces_the_items_and_the_tax_line(svc_conn, world):
    vid = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-16"))
    result = vouchers.update_draft(svc_conn, vid, purchase(world, "Contractor Co", "200000", date(2026, 6, 10), ref="B-16"), actor="tester")
    assert result.errors == []
    assert lines_of(svc_conn, vid)[2] == ("TDS Payable", D("0.00"), D("4000.00"))
    assert [(r.taxable_base, r.tds_amount) for r in items_of(svc_conn, vid)] == [(D("200000.00"), D("4000.00"))]
    vouchers.update_draft(svc_conn, vid, VoucherDraft(world.client_id, "purchase", date(2026, 6, 10), "Plain", "B-16", None,
                                                      (VoucherLine(world.ids["Contract Expense"], "5", None), VoucherLine(world.ids["Contractor Co"], None, "5"))), actor="tester")
    assert items_of(svc_conn, vid) == []


# ---- T-13: a tampered draft cannot be approved ----------------------------------------------------------------------------
def test_T13_tax_line_changed_after_calculation_blocks_approval(svc_conn, world):
    vid = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-13"))
    svc_conn.execute(text("UPDATE voucher_lines SET credit = 1500 WHERE voucher_id = :v AND line_no = 3"), {"v": vid})
    svc_conn.execute(text("UPDATE voucher_lines SET credit = 98500 WHERE voucher_id = :v AND line_no = 2"), {"v": vid})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.approve(svc_conn, vid, actor="approver")
    assert [e.rule_id for e in info.value.errors] == ["T-13"]
    assert "does not match the calculated tax 2,000.00" in info.value.errors[0].message


def test_T13_stored_tax_changed_blocks_approval(svc_conn, world):
    vid = saved(svc_conn, purchase(world, "Contractor Co", "100000", date(2026, 6, 10), ref="B-13B"))
    svc_conn.execute(text("UPDATE tds_voucher_items SET tds_amount = 1500 WHERE voucher_id = :v"), {"v": vid})
    with pytest.raises(VoucherRuleError) as info:
        vouchers.approve(svc_conn, vid, actor="approver")
    assert info.value.errors[0].rule_id == "T-13" and "stored tax (1,500.00) differs from the recalculation (2,000.00)" in info.value.errors[0].message


# ---- T-07: threshold crossing across posted vouchers, reversal, register, position --------------------------------------------
def test_T07_crossing_the_annual_threshold_catches_up_and_a_reversal_takes_the_voucher_out_of_the_books(svc_conn, world):
    who, on = "Ind Contractor", date(2026, 6, 5)
    v1 = saved(svc_conn, purchase(world, who, "20000", on, ref="I-1"))
    post_it(svc_conn, v1)
    v2 = saved(svc_conn, purchase(world, who, "25000", date(2026, 6, 10), ref="I-2"))
    post_it(svc_conn, v2)
    assert [lines_of(svc_conn, v)[2:] for v in (v1, v2)] == [[], []]  # below every threshold: no tax line
    assert items_of(svc_conn, v2)[0].rate_reason == "below_threshold"
    v3 = saved(svc_conn, purchase(world, who, "60000", date(2026, 6, 20), ref="I-3"))
    row = items_of(svc_conn, v3)[0]
    # whole amount once crossed: 1% of (20,000 + 25,000 + 60,000) = 1,050.00
    assert (row.cumulative_before, row.cumulative_after, row.taxable_base, row.tax_already_on_base, row.tds_amount, row.threshold_crossed) == (
        D("45000.00"), D("105000.00"), D("105000.00"), D("0.00"), D("1050.00"), True)
    assert lines_of(svc_conn, v3)[1:] == [("Ind Contractor", D("0.00"), D("58950.00")), ("TDS Payable", D("0.00"), D("1050.00"))]
    post_it(svc_conn, v3)

    position = tds_deduction.threshold_position(svc_conn, world.client_id, world.ids[who], "contractor", date(2026, 7, 1))
    assert (position["cumulative_amount"], position["tax_deducted"], position["annual_threshold"], position["headroom"]) == (
        "105000.00", "1050.00", "100000.00", "0.00")
    reg = tds_deduction.register(svc_conn, world.client_id, financial_year_id=world.fy26, quarter=1, nature_key=None, deductee_ledger_id=None)
    assert [r["tds_amount"] for r in reg["rows"]] == ["0.00", "0.00", "1050.00"] and reg["totals"]["tds_amount"] == "1050.00"
    assert reg["rows"][2]["balance"] == "1050.00" and reg["rows"][2]["voucher_number"].startswith("PUR/2026-27/")
    assert tds_deduction.register(svc_conn, world.client_id, financial_year_id=world.fy26, quarter=2, nature_key=None, deductee_ledger_id=None)["rows"] == []
    by = tds_deduction.by_deductee(svc_conn, world.client_id, world.fy26)
    assert (by[0]["cumulative_amount"], by[0]["tax_deducted"], by[0]["threshold"], by[0]["threshold_crossed_on"]) == ("105000.00", "1050.00", "100000.00", "2026-06-20")

    vouchers.reverse(svc_conn, v3, date(2026, 6, 25), "wrong party", actor="tester")
    position = tds_deduction.threshold_position(svc_conn, world.client_id, world.ids[who], "contractor", date(2026, 7, 1))
    assert (position["cumulative_amount"], position["tax_deducted"], position["headroom"]) == ("45000.00", "0.00", "55000.00")
    reg = tds_deduction.register(svc_conn, world.client_id, financial_year_id=world.fy26, quarter=None, nature_key=None, deductee_ledger_id=None)
    assert reg["totals"]["tds_amount"] == "0.00" and len(reg["rows"]) == 2


# ---- T-12: certificate limit used up across posted vouchers ---------------------------------------------------------------------
def test_T12_certificate_limit_runs_out_between_two_vouchers(svc_conn, world):
    cert = uuid.UUID(int=77)
    v1 = saved(svc_conn, purchase(world, "Contractor Co", "120000", date(2026, 6, 10), ref="C-1", cert=cert))
    first = items_of(svc_conn, v1)[0]
    assert (first.rate_reason, first.rate_applied, first.tds_amount, first.lower_cert_id) == ("lower_certificate", D("1"), D("1200.00"), cert)  # 1% of 1,20,000
    post_it(svc_conn, v1)
    # limit 1,50,000, 1,20,000 used: 30,000 at 1% = 300 and 30,000 at 2% = 600
    v2 = saved(svc_conn, purchase(world, "Contractor Co", "60000", date(2026, 6, 20), ref="C-2", cert=cert))
    second = items_of(svc_conn, v2)[0]
    assert (second.rate_reason, second.taxable_base, second.tds_amount) == ("lower_certificate", D("60000.00"), D("900.00"))
    assert lines_of(svc_conn, v2)[2] == ("TDS Payable", D("0.00"), D("900.00"))


# ---- API: tds-preview, T-05, register -----------------------------------------------------------------------------------------------
def test_T05_preview_and_typed_tax_through_the_api(svc_conn, world):
    app.dependency_overrides[deps.get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        body = {
            "voucher_type": "purchase", "voucher_date": "2026-06-10", "narration": "Contract work", "reference_no": "API-1",
            "party_ledger_id": str(world.ids["Ind Contractor"]),
            "lines": [{"ledger_id": str(world.ids["Contract Expense"]), "debit": "40000.00"},
                      {"ledger_id": str(world.ids["Ind Contractor"]), "credit": "40000.00"}],
            "tds": {"items": [{"deductee_ledger_id": str(world.ids["Ind Contractor"]), "nature_key": "contractor", "amount": "40000.00",
                               "payment_date": "2026-06-10"}]},
        }
        before = svc_conn.execute(text("SELECT count(*) FROM vouchers")).scalar_one()
        r = api.post(f"/clients/{world.client_id}/vouchers/tds-preview", json=body, headers=H)
        assert r.status_code == 200
        out = r.json()
        assert out["errors"] == []
        assert [(x["ledger_name"], x["debit"], x["credit"]) for x in out["lines"]] == [
            ("Contract Expense", "40000.00", "0.00"), ("Ind Contractor", "0.00", "39600.00"), ("TDS Payable", "0.00", "400.00")]
        item = out["tds"]["items"][0]
        assert (item["tds_amount"], item["rate_applied"], item["tds_line_no"], item["section_ref"], item["deductee_name"]) == ("400.00", "1", 3, "393(1)", "Ind Contractor")
        assert svc_conn.execute(text("SELECT count(*) FROM vouchers")).scalar_one() == before  # nothing written

        body["tds"]["items"][0]["tds_amount"] = "999.00"
        bad = api.post(f"/clients/{world.client_id}/vouchers", json=body, headers=H)
        assert bad.status_code == 422 and bad.json()["errors"][0]["rule_id"] == "T-05"
        preview_bad = api.post(f"/clients/{world.client_id}/vouchers/tds-preview", json=body, headers=H).json()
        assert preview_bad["errors"][0]["rule_id"] == "T-05" and preview_bad["lines"] == []

        del body["tds"]["items"][0]["tds_amount"]
        created = api.post(f"/clients/{world.client_id}/vouchers", json=body, headers=H)
        assert created.status_code == 201
        got = api.get(f"/vouchers/{created.json()['voucher_id']}").json()
        assert got["tds"]["items"][0]["tds_amount"] == "400.00" and len(got["lines"]) == 3
        reg = api.get(f"/clients/{world.client_id}/tds/register", params={"financial_year_id": str(world.fy26)})
        assert reg.status_code == 200 and reg.json()["rows"] == []  # a draft is not in the register
        pos = api.get(f"/clients/{world.client_id}/tds/threshold-position",
                      params={"deductee_ledger_id": str(world.ids["Ind Contractor"]), "nature_key": "contractor", "on": "2026-06-30"})
        assert pos.json()["annual_threshold"] == "100000.00" and pos.json()["headroom"] == "100000.00"
    finally:
        app.dependency_overrides.clear()
