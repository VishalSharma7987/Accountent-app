"""Phase 6 package B: fixed asset register, Companies Act depreciation run -> draft journal, income-tax block working (F-20 .. F-34).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_final_assets_db.py`.

Every test builds its own client inside a rolled-back transaction. Expected values are hand-calculated literals:
  furniture opening 1,00,000 SLM life 10 (class furniture_fittings, life copied): 10,000.00
  machine purchase 2,00,000 on 01-10-2026, residual 10,000, life 15: 190000/15 x 182/365 = 6,315.98   -> run total 16,315.98
  IT block plant_machinery_general (rate 15, FY 2026-27 -> Income-tax Act 2025 row, status pending): see the unit test; 1,05,000.00
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app
from app.services import client_setup, final_assets, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal
ACTOR = "clerk"


class World:
    def __init__(self, conn):
        self.conn = conn
        created = client_setup.create_client(conn, ClientProfile("Asset Co", "company", "manufacturing", "regular"),
                                             fy_start=date(2026, 4, 1), actor="setup")
        self.client_id, self.fy_id = created.client_id, created.financial_year_id
        add = lambda name, group: client_setup.add_ledger(conn, self.client_id, name, group, actor="setup")
        self.furniture_ledger = add("Test Furniture", "fixed_assets")
        self.machine_ledger = add("Test Machinery", "fixed_assets")
        self.accum = add("Test Accumulated Depreciation", "fixed_assets")
        self.expense = add("Test Depreciation", "indirect_expenses")
        conn.execute(text("INSERT INTO final_ledger_roles (client_id, role, ledger_id, set_by) VALUES (:c, 'depreciation_expense', :l, 't')"),
                     {"c": self.client_id, "l": self.expense})

    def asset(self, no, ledger, **kw):
        body = {"asset_no": no, "name": no, "asset_ledger_id": ledger, "accumulated_dep_ledger_id": self.accum,
                "it_block_key": "furniture_fittings", "sched2_class_key": "furniture_fittings", "book_method": "slm", **kw}
        return final_assets.create_asset(self.conn, self.client_id, body, actor=ACTOR)

    def event(self, asset_id, kind, on, **kw):
        return final_assets.add_event(self.conn, self.client_id, asset_id, {"kind": kind, "event_date": on, **kw}, actor=ACTOR)

    def machine(self):
        a = self.asset("MC-1", self.machine_ledger, it_block_key="plant_machinery_general", sched2_class_key="plant_machinery_general",
                       useful_life_years="15", residual_value="10000.00")
        self.event(a, "purchase", date(2026, 10, 1), put_to_use_date=date(2026, 10, 1), amount="200000.00")
        return a

    def furniture(self):
        a = self.asset("FU-1", self.furniture_ledger)
        self.event(a, "opening", date(2026, 4, 1), put_to_use_date=date(2026, 4, 1), amount="100000.00", accumulated_dep_bf="0.00")
        return a


@pytest.fixture
def w(svc_conn):
    return World(svc_conn)


def test_F20_F24_asset_setup_rules_and_class_life_copy(w):
    a = w.asset("FU-1", w.furniture_ledger)                      # life omitted: copied from the Schedule II class row
    [row] = final_assets.list_assets(w.conn, w.client_id)
    assert (row["id"], row["useful_life_years"], row["book_method"], row["cost"]) == (a, "10.00", "slm", D("0.00"))
    with pytest.raises(ServiceError) as dup:
        w.asset("fu-1", w.furniture_ledger)
    assert dup.value.code == "asset_exists"
    with pytest.raises(VoucherRuleError) as diff:                 # F-24: a life different from the class needs a reason
        w.asset("FU-2", w.furniture_ledger, useful_life_years="8")
    assert [e.rule_id for e in diff.value.errors] == ["F-24"]
    w.asset("FU-3", w.furniture_ledger, useful_life_years="8", life_override_reason="Heavy use, two shifts")
    with pytest.raises(VoucherRuleError) as wrong:                # F-20: the ledger must be in the Fixed Assets group
        w.asset("FU-4", w.expense)
    assert [e.rule_id for e in wrong.value.errors] == ["F-20"]
    with pytest.raises(VoucherRuleError) as wdv:                  # F-23: WDV needs a residual value
        w.asset("FU-5", w.furniture_ledger, book_method="wdv")
    assert [e.rule_id for e in wdv.value.errors] == ["F-23"]


def test_F21_event_rules_year_freeze_and_audit(w):
    a = w.furniture()
    for body, rule in (({"kind": "addition", "event_date": date(2026, 3, 1), "put_to_use_date": date(2026, 3, 1), "amount": "10.00"}, "no_financial_year"),
                       ({"kind": "opening", "event_date": date(2026, 10, 1), "put_to_use_date": date(2026, 10, 1), "amount": "10.00"}, "event_order"),
                       ({"kind": "disposal", "event_date": date(2026, 3, 1), "amount": "10.00"}, "no_financial_year")):
        with pytest.raises(ServiceError) as exc:
            final_assets.add_event(w.conn, w.client_id, a, body, actor=ACTOR)
        assert exc.value.code == rule, (body, exc.value.message)
    with pytest.raises(ServiceError) as ten:                      # amounts with 3 decimals are rejected, not rounded
        final_assets.add_event(w.conn, w.client_id, a, {"kind": "addition", "event_date": date(2026, 8, 1),
                                                         "put_to_use_date": date(2026, 8, 1), "amount": "10.005"}, actor=ACTOR)
    assert ten.value.code == "invalid_amount"
    with pytest.raises(ServiceError) as sold:                     # a disposal before the put-to-use date
        w.event(a, "disposal", date(2026, 4, 1), amount="1.00")
        w.event(a, "disposal", date(2026, 5, 1), amount="2.00")
    assert sold.value.code == "event_order"
    events = final_assets.list_events(w.conn, w.client_id, a)
    assert [e["kind"] for e in events] == ["opening", "disposal"]
    with pytest.raises(ServiceError) as start:                    # the opening event cannot go while a disposal depends on it
        final_assets.delete_event(w.conn, w.client_id, a, events[0]["id"], actor=ACTOR)
    assert start.value.code == "event_order"
    final_assets.delete_event(w.conn, w.client_id, a, events[1]["id"], actor=ACTOR)
    n = w.conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'fixed_asset_event'"), {"c": w.client_id}).scalar_one()
    assert n == 3                                                  # opening, one disposal created, that disposal deleted


def test_F23_F26_run_creates_one_draft_journal_and_rerun_rules(w):
    fu = w.furniture()
    w.machine()
    p = final_assets.preview_book(w.conn, w.client_id, w.fy_id)
    assert p["total"] == D("16315.98")
    assert sorted(str(x["depreciation"]) for x in p["lines"]) == ["10000.00", "6315.98"]
    assert [(str(j["debit"]), str(j["credit"])) for j in p["journal_lines"]] == [("16315.98", "0.00"), ("0.00", "16315.98")]
    assert all(x["rule_status"]["verification_status"] == "pending" for x in p["lines"])     # pending shown on the working
    assert p["findings"] == []
    # F-26: ONE draft journal through the voucher service
    run = final_assets.run_book(w.conn, w.client_id, w.fy_id, actor=ACTOR)
    assert run["total"] == D("16315.98")
    v = vouchers.get_voucher(w.conn, run["voucher_id"])
    assert (v.status, v.voucher_type, v.voucher_date) == ("draft", "journal", date(2027, 3, 31))
    assert sorted((str(x.debit), str(x.credit)) for x in v.lines) == [("0.00", "16315.98"), ("16315.98", "0.00")]
    lines = w.conn.execute(text("SELECT depreciation, days_used, days_in_year, method FROM depreciation_run_lines WHERE run_id = :r ORDER BY depreciation"),
                           {"r": run["run_id"]}).all()
    assert [(str(a), b, c, d) for a, b, c, d in lines] == [("6315.9800", 182, 365, "slm"), ("10000.0000", 365, 365, "slm")]
    with pytest.raises(ServiceError) as again:
        final_assets.run_book(w.conn, w.client_id, w.fy_id, actor=ACTOR)
    assert again.value.code == "run_exists"
    with pytest.raises(ServiceError) as frozen:                    # inputs of a year with a live run are frozen
        w.event(w.furniture(), "addition", date(2026, 8, 1), put_to_use_date=date(2026, 8, 1), amount="1.00") if False else \
            final_assets.add_event(w.conn, w.client_id, final_assets.list_assets(w.conn, w.client_id)[0]["id"],
                                   {"kind": "disposal", "event_date": date(2026, 12, 1), "amount": "1.00"}, actor=ACTOR)
    assert frozen.value.code == "asset_in_use"
    # a draft run is deleted with its voucher; then a new run is possible
    final_assets.delete_run(w.conn, w.client_id, run["run_id"], actor=ACTOR)
    assert w.conn.execute(text("SELECT count(*) FROM vouchers WHERE id = :v"), {"v": run["voucher_id"]}).scalar_one() == 0
    run2 = final_assets.run_book(w.conn, w.client_id, w.fy_id, actor=ACTOR)
    # post it: the run can no longer be deleted, the setup of its assets cannot change; reversal frees the year for a new run
    vouchers.approve(w.conn, run2["voucher_id"], actor="partner")
    vouchers.post(w.conn, run2["voucher_id"], actor="partner")
    with pytest.raises(ServiceError) as state:
        final_assets.delete_run(w.conn, w.client_id, run2["run_id"], actor=ACTOR)
    assert state.value.code == "run_state"
    body = {"asset_no": "FU-1", "name": "Renamed", "asset_ledger_id": w.furniture_ledger, "accumulated_dep_ledger_id": w.accum,
            "it_block_key": "furniture_fittings", "sched2_class_key": "furniture_fittings", "book_method": "slm", "residual_value": "500.00"}
    with pytest.raises(ServiceError) as inuse:
        final_assets.update_asset(w.conn, w.client_id, fu, body, actor=ACTOR)
    assert inuse.value.code == "asset_in_use"
    vouchers.reverse(w.conn, run2["voucher_id"], date(2027, 3, 31), "Wrong rates", actor="partner")
    run3 = final_assets.run_book(w.conn, w.client_id, w.fy_id, actor=ACTOR)        # allowed again: the previous voucher is reversed
    assert run3["total"] == D("16315.98")
    runs = final_assets.list_runs(w.conn, w.client_id, w.fy_id)
    assert sorted(r["voucher_status"] for r in runs) == ["draft", "reversed"]
    ref = w.conn.execute(text("SELECT reference_no FROM vouchers WHERE id = :v"), {"v": run3["voucher_id"]}).scalar_one()
    assert ref == "DEP/2026-27/2"


def test_F20_register_for_the_year(w):
    w.furniture()
    w.machine()
    r = final_assets.register(w.conn, w.client_id, w.fy_id)
    by_no = {x["asset_no"]: x for x in r["rows"]}
    assert (by_no["FU-1"]["opening_cost"], by_no["FU-1"]["depreciation_for_year"], by_no["FU-1"]["net_block"]) == (
        D("100000.00"), D("10000.00"), D("90000.00"))
    assert (by_no["MC-1"]["additions"], by_no["MC-1"]["depreciation_for_year"], by_no["MC-1"]["net_block"]) == (
        D("200000.00"), D("6315.98"), D("193684.02"))
    assert (r["totals"]["closing_cost"], r["totals"]["net_block"]) == (D("300000.00"), D("283684.02"))


def test_F30_F34_income_tax_block_working_openings_flags_finalize(w):
    # plant and machinery block: two additions, one disposal (plan example); furniture block with an opening event but no WDV entered
    fu = w.furniture()
    for no, cost, on in (("MC-A", "200000.00", date(2026, 10, 1)), ("MC-B", "100000.00", date(2026, 11, 15))):
        a = w.asset(no, w.machine_ledger, it_block_key="plant_machinery_general", sched2_class_key="plant_machinery_general")
        w.event(a, "purchase", on, put_to_use_date=on, amount=cost)
    old = w.asset("MC-X", w.machine_ledger, it_block_key="plant_machinery_general", sched2_class_key="plant_machinery_general")
    w.event(old, "opening", date(2026, 4, 1), put_to_use_date=date(2020, 4, 1), amount="80000.00", accumulated_dep_bf="0.00")
    w.event(old, "disposal", date(2026, 12, 1), amount="50000.00")
    final_assets.set_it_openings(w.conn, w.client_id, w.fy_id, [{"block_key": "plant_machinery_general", "opening_wdv": "500000.00"}], actor=ACTOR)
    wk = final_assets.it_working(w.conn, w.client_id, w.fy_id)
    assert wk["status"] == "draft"
    [blk] = wk["blocks"]
    assert (blk["block_key"], blk["rate"], blk["rate_act"], blk["rate_verification"]) == ("plant_machinery_general", "15.0000", "it_act_2025", "pending")
    assert (blk["opening_wdv"], blk["additions_full"], blk["additions_half"], blk["disposals"], blk["depreciation"], blk["closing_wdv"]) == (
        D("500000.00"), D("200000.00"), D("100000.00"), D("50000.00"), D("105000.00"), D("645000.00"))
    assert sorted((x["asset_no"], x["days"], x["half"]) for x in blk["assets"]) == [("MC-A", 182, False), ("MC-B", 137, True)]
    assert [(f["rule_id"], f["severity"]) for f in wk["findings"]] == [("F-30", "error")]          # furniture: opening WDV not entered
    assert {"rule": "half_rate_days", "act": "it_act_2025", "verification_status": "pending"} in wk["rule_status"]
    with pytest.raises(ServiceError) as blocked:
        final_assets.finalize_it(w.conn, w.client_id, w.fy_id, None, actor=ACTOR)
    assert blocked.value.code == "invalid_it_working"
    final_assets.set_it_openings(w.conn, w.client_id, w.fy_id, [{"block_key": "furniture_fittings", "opening_wdv": "90000.00"}], actor=ACTOR)
    wk2 = final_assets.it_working(w.conn, w.client_id, w.fy_id)
    assert wk2["findings"] == [] and wk2["total_depreciation"] == D("114000.00")                   # 105,000.00 + 90,000 x 10%
    # no unregistered side effect: a working is not a voucher
    assert w.conn.execute(text("SELECT count(*) FROM vouchers WHERE client_id = :c"), {"c": w.client_id}).scalar_one() == 0
    final_assets.finalize_it(w.conn, w.client_id, w.fy_id, None, actor=ACTOR)
    fin = final_assets.it_working(w.conn, w.client_id, w.fy_id)
    assert fin["status"] == "final" and {b["block_key"]: b["closing_wdv"] for b in fin["blocks"]} == {
        "furniture_fittings": D("81000.00"), "plant_machinery_general": D("645000.00")}
    with pytest.raises(ServiceError) as twice:
        final_assets.finalize_it(w.conn, w.client_id, w.fy_id, None, actor=ACTOR)
    assert twice.value.code == "working_final"
    assert fu is not None


def test_F30_a_rule_in_force_is_required_never_guessed(w):
    # FY 2025-26 rows exist (1961 Act) but a year before 2025-04-01 has none: the opening cannot be entered
    created = client_setup.create_client(w.conn, ClientProfile("Old Co", "company", "trading", "regular"), fy_start=date(2023, 4, 1), actor="setup")
    with pytest.raises(ServiceError) as exc:
        final_assets.set_it_openings(w.conn, created.client_id, created.financial_year_id,
                                     [{"block_key": "furniture_fittings", "opening_wdv": "1.00"}], actor=ACTOR)
    assert exc.value.code == "no_rule"


def test_api_round_trip_status_codes_and_rules(svc_conn, w):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        h = {"X-User": "clerk"}
        base = f"/clients/{w.client_id}"
        r = api.post(f"{base}/fixed-assets", headers=h, json={"asset_no": "FU-1", "name": "Chairs", "asset_ledger_id": str(w.furniture_ledger),
                                                              "accumulated_dep_ledger_id": str(w.accum), "it_block_key": "furniture_fittings",
                                                              "sched2_class_key": "furniture_fittings", "book_method": "slm"})
        assert r.status_code == 201
        aid = r.json()["id"]
        assert api.post(f"{base}/fixed-assets", headers=h, json={"asset_no": "FU-1", "name": "x", "asset_ledger_id": str(w.furniture_ledger),
                                                                 "is_depreciable": False}).json()["code"] == "asset_exists"
        bad = api.post(f"{base}/fixed-assets", headers=h, json={"asset_no": "FU-9", "name": "x", "asset_ledger_id": str(w.expense)})
        assert bad.status_code == 422 and bad.json()["errors"][0]["rule_id"] == "F-20"
        e = api.post(f"{base}/fixed-assets/{aid}/events", headers=h, json={"kind": "addition", "event_date": "2026-06-01",
                                                                           "put_to_use_date": "2026-06-01", "amount": "10.00"})
        assert e.status_code == 422 and e.json()["code"] == "event_order"
        assert api.post(f"{base}/fixed-assets/{aid}/events", headers=h, json={"kind": "opening", "event_date": "2026-04-01",
                                                                              "put_to_use_date": "2026-04-01", "amount": "100000.00"}).status_code == 201
        rules = api.get(f"{base}/fixed-assets/rules", params={"as_on": "2027-03-31"}).json()
        block = next(b for b in rules["it_blocks"] if b["block_key"] == "plant_machinery_general")
        assert (block["rate"], block["act"], block["verification_status"], rules["half_rate_days"], rules["half_rate_percent"]) == (
            "15.0000", "it_act_2025", "pending", 180, "50.0000")
        pv = api.post(f"{base}/depreciation/book/preview", json={"financial_year_id": str(w.fy_id)}).json()
        assert pv["total"] == "10000.00" and pv["lines"][0]["rule_status"]["verification_status"] == "pending"
        run = api.post(f"{base}/depreciation/book/run", headers=h, json={"financial_year_id": str(w.fy_id)})
        assert run.status_code == 201 and run.json()["total"] == "10000.00"
        assert api.post(f"{base}/depreciation/book/run", headers=h, json={"financial_year_id": str(w.fy_id)}).status_code == 409
        runs = api.get(f"{base}/depreciation/book/runs", params={"financial_year_id": str(w.fy_id)}).json()
        assert [(x["voucher_status"], x["total"]) for x in runs] == [("draft", "10000.00")]
        reg = api.get(f"{base}/fixed-assets/register", params={"financial_year_id": str(w.fy_id)}).json()
        assert reg["totals"]["net_block"] == "90000.00"
        assert api.delete(f"{base}/depreciation/book/runs/{run.json()['run_id']}", headers=h).json() == {"ok": True}
        assert api.put(f"{base}/depreciation/it/openings/{w.fy_id}", headers=h,
                       json={"rows": [{"block_key": "furniture_fittings", "opening_wdv": "90000.00"}]}).json() == {"ok": True}
        wk = api.get(f"{base}/depreciation/it/working", params={"financial_year_id": str(w.fy_id)}).json()
        assert (wk["status"], wk["total_depreciation"], wk["blocks"][0]["rate_verification"]) == ("draft", "9000.00", "pending")
        assert api.get(f"{base}/fixed-assets/not-an-id/events").status_code == 404
    finally:
        app.dependency_overrides.clear()
