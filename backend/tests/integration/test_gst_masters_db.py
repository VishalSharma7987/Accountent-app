"""Phase 3 package A against the database: rule loaders on the seeds, registrations, ledger roles, item master,
party GST type and the API. Every test runs in a rolled-back transaction. Expected values are typed literally."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine.gst_types import RateRule
from app.main import app
from app.rules import gst_rules
from app.services import gst_items, gst_registrations, parties
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

GSTIN = "27AAPFU0939F1ZV"
H = {"X-User": "clerk"}


@pytest.fixture
def f(svc_conn) -> Factory:
    return Factory(svc_conn.connection.driver_connection)


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def rule_ids(exc: VoucherRuleError) -> list[str]:
    return [e.rule_id for e in exc.errors]


def test_G10_seeded_rate_rules_pick_by_date_and_the_tables_have_no_overlaps(svc_conn):
    pick = lambda code, kind, on: gst_rules.rate_for(svc_conn, code, kind, on)
    rule, is_default = pick("30049099", "goods", date(2025, 9, 21))
    assert (rule.rate, is_default, rule.verification_status, rule.is_example) == (Decimal(12), False, "pending", True)
    assert pick("30049099", "goods", date(2025, 9, 22))[0].rate == Decimal(5)
    assert pick("851712", "goods", date(2020, 3, 31))[0].rate == Decimal(12)
    assert pick("851712", "goods", date(2020, 4, 1))[0].rate == Decimal(18)
    rule, is_default = pick("995411", "services", date(2026, 4, 1))
    assert (rule.rule_key, rule.rate, is_default) == ("default_services", Decimal(18), True)
    assert pick("99831405", "services", date(2026, 4, 1))[1] is False  # SAC 9983 example row, not the default
    assert pick("9999", "goods", date(2026, 4, 1)) == (None, False)

    assert gst_rules.slab_in_force(gst_rules.slabs(svc_conn, date(2025, 9, 21)), Decimal(28), date(2025, 9, 21))
    assert not gst_rules.slab_in_force(gst_rules.slabs(svc_conn, date(2025, 9, 22)), Decimal(28), date(2025, 9, 22))
    assert gst_rules.status_summary(gst_rules.rcm_rules(svc_conn, date(2026, 4, 1)))["overall"] == "pending"
    assert gst_rules.rcm_rule(svc_conn, "gta_services", date(2026, 4, 1)).supply_kind == "services"
    assert gst_rules.itc_condition(svc_conn, "payment_within_days", date(2026, 4, 1)).parameter_days == 180
    assert gst_rules.threshold(svc_conn, "b2cl_invoice_value", date(2026, 4, 1)).numeric_value == Decimal("250000.0000")
    assert gst_rules.composition_rule(svc_conn, "trader", date(2026, 4, 1)).rate == Decimal("1.0000")
    assert gst_rules.blocked_rule(svc_conn, "motor_vehicles_17_5_a", date(2026, 4, 1)).has_exception is True

    all_rules = [RateRule(*r) for r in svc_conn.execute(text(
        "SELECT id::text, rule_key, code_kind, code_prefix, supply_kind, treatment, rate, cess_rate, "
        "cess_specific_amount, cess_uqc, effective_from, effective_to, source_reference, verification_status, "
        "is_example FROM gst_rate_rules"))]
    assert gst_rules.find_overlaps(all_rules, lambda r: r.rule_key) == []


def test_G01_G06_registration_lifecycle_audit_and_refusals(svc_conn, f):
    client = f.client()
    reg = gst_registrations.create_registration(
        svc_conn, client, gstin=" 27aapfu0939f1zv ", registration_type="regular", trade_name=" Shop ",
        effective_from=date(2026, 4, 1), actor="clerk")
    got = gst_registrations.get_registration(svc_conn, client, reg)
    assert (got.gstin, got.state_code, got.state_name, got.trade_name, got.return_frequency, got.is_active) == (
        GSTIN, "27", "Maharashtra", "Shop", "monthly", True)

    with pytest.raises(ServiceError) as dup:
        gst_registrations.create_registration(svc_conn, client, gstin=GSTIN, registration_type="regular",
                                              effective_from=date(2026, 4, 1), actor="clerk")
    assert dup.value.code == "registration_exists"
    with pytest.raises(VoucherRuleError) as overlap:  # open-ended period already running
        gst_registrations.create_registration(svc_conn, client, gstin=GSTIN, registration_type="regular",
                                              effective_from=date(2026, 10, 1), actor="clerk")
    assert rule_ids(overlap.value) == ["G-06"]
    with pytest.raises(VoucherRuleError) as wrong:
        gst_registrations.create_registration(svc_conn, client, gstin="27AAPFU0939F1ZW", registration_type="regular",
                                              effective_from=date(2026, 4, 1), actor="clerk")
    assert rule_ids(wrong.value) == ["G-02"]
    with pytest.raises(VoucherRuleError) as fit:  # the factory client is a regular taxpayer
        gst_registrations.create_registration(
            svc_conn, client, gstin="29ABCDE1234F1ZW", registration_type="composition",
            composition_category="trader", effective_from=date(2026, 4, 1), actor="clerk")
    assert rule_ids(fit.value) == ["G-05"]
    with pytest.raises(ServiceError) as nobody:
        gst_registrations.create_registration(svc_conn, uuid.uuid4(), gstin=GSTIN, registration_type="regular",
                                              effective_from=date(2026, 4, 1), actor="clerk")
    assert nobody.value.code == "not_found"

    gst_registrations.update_registration(
        svc_conn, client, reg, registration_type="regular", return_frequency="qrmp", trade_name="Shop",
        effective_from=date(2026, 4, 1), effective_to=date(2027, 3, 31), is_active=False, actor="partner")
    closed = gst_registrations.load_registration(svc_conn, client, reg)
    assert (closed.return_frequency, closed.effective_to, closed.is_active) == ("qrmp", date(2027, 3, 31), False)
    # the closed period is now free for the same GSTIN from the next day
    gst_registrations.create_registration(svc_conn, client, gstin=GSTIN, registration_type="regular",
                                          effective_from=date(2027, 4, 1), actor="clerk")
    assert [r.effective_from for r in gst_registrations.list_registrations(svc_conn, client)] == [
        date(2026, 4, 1), date(2027, 4, 1)]
    audit = svc_conn.execute(text(
        "SELECT action, actor FROM audit_log WHERE client_id = :c AND entity = 'gst_registration' ORDER BY id"),
        {"c": client}).all()
    assert [tuple(a) for a in audit] == [("create", "clerk"), ("update", "partner"), ("create", "clerk")]


def test_G08_ledger_roles_group_rule_replace_and_audit(svc_conn, f):
    client, other = f.client(), f.client()
    reg = gst_registrations.create_registration(svc_conn, client, gstin=GSTIN, registration_type="regular",
                                                effective_from=date(2026, 4, 1), actor="clerk")
    with f.conn.pipeline():
        out_cgst = f.ledger(client, "Output CGST", "duties_taxes")
        in_cgst = f.ledger(client, "Input CGST", "duties_taxes")
        rent = f.ledger(client, "Rent", "indirect_expenses")
        foreign = f.ledger(other, "Output CGST", "duties_taxes")
    gst_registrations.set_ledger_roles(svc_conn, client, reg, {"output_cgst": out_cgst, "round_off": rent}, actor="clerk")
    shown = gst_registrations.get_registration(svc_conn, client, reg).ledger_roles
    assert {k: v[1] for k, v in shown.items()} == {"output_cgst": "Output CGST", "round_off": "Rent"}

    with pytest.raises(VoucherRuleError) as bad:
        gst_registrations.set_ledger_roles(svc_conn, client, reg, {"input_cgst": rent}, actor="clerk")
    assert rule_ids(bad.value) == ["G-08"]
    with pytest.raises(VoucherRuleError) as bad_client:
        gst_registrations.set_ledger_roles(svc_conn, client, reg, {"input_cgst": foreign, "input_sgst": "nope"},
                                           actor="clerk")
    assert rule_ids(bad_client.value) == ["G-08", "G-08"]
    assert set(gst_registrations.get_registration(svc_conn, client, reg).ledger_roles) == {"output_cgst", "round_off"}

    gst_registrations.set_ledger_roles(svc_conn, client, reg, {"input_cgst": in_cgst}, actor="clerk")  # replaces all
    assert set(gst_registrations.get_registration(svc_conn, client, reg).ledger_roles) == {"input_cgst"}
    loaded = gst_registrations.load_registration(svc_conn, client, reg)
    assert loaded.ledger_roles == {"input_cgst": str(in_cgst)}
    with pytest.raises(ServiceError) as missing:
        gst_registrations.set_ledger_roles(svc_conn, other, reg, {}, actor="clerk")  # other client's view
    assert missing.value.code == "not_found"


def test_G07_item_master_rules_search_and_deactivate(svc_conn, f):
    client = f.client()
    sales = f.ledger(client, "Sales - Mobiles", "sales_accounts")
    phone = gst_items.create_item(svc_conn, client, name="Mobile phone", item_kind="goods", hsn_sac="851712", uqc="nos",
                                  sales_ledger_id=sales, default_itc_category_key="motor_vehicles_17_5_a", actor="clerk")
    gst_items.create_item(svc_conn, client, name="Audit fee", item_kind="service", hsn_sac="998221", actor="clerk")
    shown = gst_items.get_item(svc_conn, client, phone)
    assert (shown.uqc, shown.sales_ledger_id, shown.default_itc_category_key, shown.is_active) == (
        "NOS", str(sales), "motor_vehicles_17_5_a", True)

    for kw, expected in [
        ({"name": "X", "item_kind": "goods", "hsn_sac": "85", "uqc": "NOS"}, ["G-07"]),
        ({"name": "X", "item_kind": "goods", "hsn_sac": "8517"}, ["G-07"]),
        ({"name": "X", "item_kind": "service", "hsn_sac": "851712"}, ["G-07"]),
        ({"name": "X", "item_kind": "goods", "hsn_sac": "8517", "uqc": "ZZZ"}, ["G-07"]),
    ]:
        with pytest.raises(VoucherRuleError) as bad:
            gst_items.create_item(svc_conn, client, actor="clerk", **kw)
        assert rule_ids(bad.value) == expected
    for kw, code in [
        ({"name": "  ", "item_kind": "service", "hsn_sac": "998221"}, "invalid_name"),
        ({"name": "mobile PHONE", "item_kind": "service", "hsn_sac": "998221"}, "item_exists"),
        ({"name": "Y", "item_kind": "service", "hsn_sac": "998221", "default_rcm_category_key": "nope"}, "invalid_category"),
        ({"name": "Z", "item_kind": "service", "hsn_sac": "998221", "sales_ledger_id": uuid.uuid4()}, "invalid_ledger"),
    ]:
        with pytest.raises(ServiceError) as err:
            gst_items.create_item(svc_conn, client, actor="clerk", **kw)
        assert err.value.code == code

    assert [i.name for i in gst_items.list_items(svc_conn, client)] == ["Audit fee", "Mobile phone"]
    assert [i.name for i in gst_items.list_items(svc_conn, client, q="8517")] == ["Mobile phone"]
    assert [i.name for i in gst_items.list_items(svc_conn, client, q="AUDIT")] == ["Audit fee"]
    assert [i.name for i in gst_items.list_items(svc_conn, client, kind="service")] == ["Audit fee"]
    gst_items.update_item(svc_conn, client, phone, name="Mobile phone", item_kind="goods", hsn_sac="851712", uqc="NOS",
                          is_active=False, actor="clerk")
    after = gst_items.get_item(svc_conn, client, phone)
    assert (after.is_active, after.sales_ledger_id) == (False, None)  # PUT replaces the details
    assert svc_conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'gst_item'"),
                            {"c": client}).scalar_one() == 3


def test_G01_party_gst_registration_type_is_saved_and_checked(svc_conn, f):
    client = f.client()
    rahul = f.ledger(client, "Rahul Enterprises", "sundry_debtors")
    parties.set_party(svc_conn, client, rahul, gstin=GSTIN, gst_registration_type="regular", actor="clerk")
    assert parties.get_party(svc_conn, client, rahul).gst_registration_type == "regular"
    assert [p.gst_registration_type for p in parties.list_parties(svc_conn, client)] == ["regular"]
    for kw, rule in [({"gstin": GSTIN, "gst_registration_type": "unregistered"}, "G-01"),
                     ({"gst_registration_type": "regular"}, "G-01"),
                     ({"gstin": GSTIN, "gst_registration_type": "casual"}, "G-05")]:
        with pytest.raises(VoucherRuleError) as bad:
            parties.set_party(svc_conn, client, rahul, actor="clerk", **kw)
        assert rule_ids(bad.value) == [rule]
    parties.set_party(svc_conn, client, rahul, actor="clerk")  # PUT replaces: the type is cleared
    assert parties.get_party(svc_conn, client, rahul).gst_registration_type is None
    assert svc_conn.execute(text(
        "SELECT new_data->>'gst_registration_type' FROM audit_log WHERE client_id = :c AND entity = 'party' "
        "ORDER BY id LIMIT 1"), {"c": client}).scalar_one() == "regular"


def test_masters_api_registration_items_gstin_check_and_rule_tables(api, f):
    client = f.client()
    base = f"/clients/{client}/gst"

    check = api.post("/gst/validate-gstin", json={"gstin": "27aapfu0939f1zw", "on_date": "2026-04-01"}).json()
    assert (check["valid"], check["state_code"], check["state_name"], check["pan"], check["expected_check_char"]) == (
        False, "27", "Maharashtra", "AAPFU0939F", "V")
    assert [e["rule_id"] for e in check["errors"]] == ["G-02"]
    assert api.post("/gst/validate-gstin", json={"gstin": GSTIN, "on_date": "2026-04-01"}).json()["valid"] is True
    short = api.post("/gst/validate-gstin", json={"gstin": "27AA"}).json()
    assert (short["valid"], short["state_code"], short["expected_check_char"]) == (False, None, None)

    body = {"gstin": GSTIN, "registration_type": "regular", "effective_from": "2026-04-01"}
    assert api.post(f"{base}/registrations", json=body).status_code == 400  # X-User is required
    bad = api.post(f"{base}/registrations", json={**body, "gstin": "27AAPFU0939F1ZW"}, headers=H)
    assert bad.status_code == 422 and [e["rule_id"] for e in bad.json()["errors"]] == ["G-02"]
    created = api.post(f"{base}/registrations", json=body, headers=H)
    assert created.status_code == 201
    reg_id = created.json()["id"]
    assert api.post(f"{base}/registrations", json=body, headers=H).json()["code"] == "registration_exists"
    shown = api.get(f"{base}/registrations/{reg_id}").json()
    assert (shown["state_name"], shown["ledger_roles"], shown["is_active"]) == ("Maharashtra", {}, True)
    updated = api.put(f"{base}/registrations/{reg_id}", headers=H, json={
        "registration_type": "regular", "return_frequency": "qrmp", "effective_from": "2026-04-01",
        "effective_to": "2027-03-31"})
    assert updated.json() == {"ok": True}
    assert api.get(f"{base}/registrations").json()[0]["return_frequency"] == "qrmp"
    assert api.get(f"{base}/registrations/not-a-uuid").status_code == 404

    roles = api.put(f"{base}/registrations/{reg_id}/ledger-roles", headers=H, json={"roles": {"output_cgst": str(uuid.uuid4())}})
    assert roles.status_code == 422 and roles.json()["errors"][0]["rule_id"] == "G-08"

    item = api.post(f"{base}/items", headers=H, json={"name": "Laptop", "item_kind": "goods", "hsn_sac": "8471", "uqc": "NOS"})
    assert item.status_code == 201
    listed = api.get(f"{base}/items", params={"q": "lap", "kind": "goods"}).json()
    assert [(i["name"], i["hsn_sac"], i["uqc"], i["is_active"]) for i in listed] == [("Laptop", "8471", "NOS", True)]
    assert api.post(f"{base}/items", headers=H, json={"name": "Bad", "item_kind": "goods", "hsn_sac": "84"}).status_code == 422

    slabs = api.get("/gst/rate-slabs", params={"on": "2025-09-22"}).json()
    assert slabs["on"] == "2025-09-22" and slabs["status"]["overall"] == "pending"
    assert [r["rate"] for r in slabs["rows"] if not r["is_special"]] == ["0.0000", "5.0000", "18.0000", "40.0000"]
    thresholds = api.get("/gst/thresholds").json()["rows"]
    assert next(r for r in thresholds if r["threshold_key"] == "b2cl_invoice_value")["numeric_value"] == "250000.00"
    assert {r["code"] for r in api.get("/gst/state-codes", params={"on": "2026-04-01"}).json()["rows"]} >= {"27", "96", "99"}
    for path in ("uqc", "rcm-categories", "blocked-credit-categories", "itc-conditions", "composition-rules"):
        table = api.get(f"/gst/{path}")
        assert table.status_code == 200 and table.json()["rows"], path
        assert all(r["verification_status"] and r["source_reference"] for r in table.json()["rows"]), path
