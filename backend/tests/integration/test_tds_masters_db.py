"""Phase 4 package A against the database: rule loaders on seeds 0008 / 0009, deductee master, certificates (used amount
from posted items), ledger roles, TAN and 194Q flags, and the API. Every test runs in a rolled-back transaction.
Expected values are typed literally (seed values read from database/seeds/0008_tds_sections_rates.sql)."""

from datetime import date
from decimal import Decimal

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app
from app.rules import tds_rules
from app.services import tds_masters
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

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


def audit_actions(conn, entity):
    return [r[0] for r in conn.execute(text("SELECT action FROM audit_log WHERE entity = :e ORDER BY id"), {"e": entity})]


def test_T02_T50_rule_loaders_pick_by_date_and_report_status(svc_conn):
    last_old, first_new = date(2026, 3, 31), date(2026, 4, 1)
    old = tds_rules.rate_lookup(svc_conn, "contractor", "others", last_old)
    new = tds_rules.rate_lookup(svc_conn, "contractor", "others", first_new)
    assert (old.act, old.rate, old.no_pan_rate, old.verification_status) == ("it_act_1961", Decimal("2.0000"), Decimal("20.0000"), "pending")
    assert (old.single_payment_threshold, old.annual_threshold, old.threshold_mode) == (Decimal("30000.0000"), Decimal("100000.0000"), "whole_amount")
    assert (new.act, new.rate, new.verification_status) == ("it_act_2025", Decimal("2.0000"), "secondary_verified")
    assert tds_rules.rate_lookup(svc_conn, "contractor", "individual_huf", first_new).rate == Decimal("1.0000")
    assert tds_rules.rate_lookup(svc_conn, "ecommerce_participant", "others", first_new).rate == Decimal("0.1000")
    assert tds_rules.rate_lookup(svc_conn, "contractor", "others", date(2025, 3, 31)) is None   # before the data starts: T-02
    assert tds_rules.rate_lookup(svc_conn, "no_such_nature", "others", first_new) is None

    refs = tds_rules.load_section_refs(svc_conn)
    assert tds_rules.pick_section_ref(refs, "contractor", "it_act_1961", last_old).section_ref == "194C"
    ref = tds_rules.pick_section_ref(refs, "contractor", "it_act_2025", first_new)
    assert (ref.section_ref, ref.table_ref) == ("393(1)", "Sl. 6(i)")
    row = next(r for r in tds_rules.section_map(tds_rules.load_natures(svc_conn), refs, first_new) if r["nature_key"] == "contractor")
    assert (row["sec_1961"], row["sec_2025"], row["act_in_force"]) == ("194C", "393(1)", "it_act_2025")

    # no overlapping rows: the 1961 rows end the day before the 2025 rows start (one rule in force per key and date)
    for on in (last_old, first_new):
        rows = tds_rules.load_rates(svc_conn, on)
        keys = [(r.nature_key, r.deductee_group) for r in rows]
        assert len(keys) == len(set(keys)), on
    assert tds_rules.status_summary(tds_rules.load_rates(svc_conn, first_new, "rent_land_building"))["overall"] == "pending"
    status = tds_rules.rule_status({"rate": tds_rules.load_rates(svc_conn, first_new, "rent_land_building")})
    assert status["worst"] == "pending" and status["pending_sources"]
    assert len(tds_rules.load_forms(svc_conn, first_new)) > 0 and len(tds_rules.load_due_dates(svc_conn, first_new)) > 0
    assert len(tds_rules.load_interest_rules(svc_conn, first_new)) > 0 and len(tds_rules.load_provisions(svc_conn, first_new)) > 0


def test_T09_T10_T12_deductee_master_and_certificates(svc_conn, f):
    client_id, fy_id = f.setup()
    party = f.ledger(client_id, "Raj Contractors", "sundry_creditors")
    expense = f.ledger(client_id, "Contract Expense", "indirect_expenses")
    dead = f.ledger(client_id, "Old Supplier", "sundry_creditors")
    svc_conn.execute(text("UPDATE ledgers SET is_active = false WHERE id = :i"), {"i": dead})

    # refusals write nothing
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.set_deductee(svc_conn, client_id, expense, pan="ABCPE1234F", pan_status="valid", deductee_type="individual", actor="clerk")
    assert rule_ids(e.value) == ["T-09"]
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.set_deductee(svc_conn, client_id, dead, pan=None, pan_status="missing", deductee_type="company", actor="clerk")
    assert rule_ids(e.value) == ["T-09"]
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.set_deductee(svc_conn, client_id, party, pan="ABC", pan_status="valid", deductee_type="individual", actor="clerk")
    assert rule_ids(e.value) == ["T-10"]
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.set_deductee(svc_conn, client_id, party, pan=None, pan_status="missing", deductee_type="company",
                                 default_nature_key="nosuch", actor="clerk")
    assert rule_ids(e.value) == ["T-03"]
    with pytest.raises(ServiceError) as e:
        tds_masters.set_deductee(svc_conn, client_id, "00000000-0000-0000-0000-000000000000", pan=None, pan_status="missing",
                                 deductee_type="company", actor="clerk")
    assert e.value.code == "not_found"
    assert tds_masters.list_deductees(svc_conn, client_id) == []

    # create (PAN typed in lower case is stored in capitals), warning T-11 for a company PAN on an individual
    warnings = tds_masters.set_deductee(svc_conn, client_id, party, pan=" abcce1234f ", pan_status="valid",
                                        deductee_type="individual", default_nature_key="contractor", actor="clerk")
    assert [w.rule_id for w in warnings] == ["T-11"]
    d = tds_masters.get_deductee(svc_conn, client_id, party)
    assert (d.pan, d.pan_status, d.deductee_type, d.default_nature_key, d.ledger_name) == (
        "ABCCE1234F", "valid", "individual", "contractor", "Raj Contractors")
    assert d.pan_warning and "4th letter 'C'" in d.pan_warning
    # replace: now a company, no warning; engine data view
    assert tds_masters.set_deductee(svc_conn, client_id, party, pan="ABCCE1234F", pan_status="valid", deductee_type="company",
                                    actor="clerk") == []
    eng = tds_masters.load_deductee(svc_conn, client_id, party)
    assert (eng.pan, eng.deductee_type, eng.default_nature_key) == ("ABCCE1234F", "company", None)
    assert audit_actions(svc_conn, "tds_deductee") == ["create", "update"]
    assert [x.ledger_id for x in tds_masters.list_deductees(svc_conn, client_id, "raj")] == [party]
    assert tds_masters.list_deductees(svc_conn, client_id, "zzz") == []

    # certificates
    kw = {"certificate_no": "LDC/26-27/1", "nature_key": "contractor", "rate": Decimal(1), "max_amount": Decimal("500000.00"),
          "valid_from": date(2026, 4, 1), "valid_to": date(2027, 3, 31), "actor": "clerk"}
    cert_id = tds_masters.add_certificate(svc_conn, client_id, party, **kw)
    with pytest.raises(ServiceError) as e:
        tds_masters.add_certificate(svc_conn, client_id, party, **kw)
    assert e.value.code == "certificate_exists"
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.add_certificate(svc_conn, client_id, party, **{**kw, "certificate_no": "X", "rate": Decimal(101)})
    assert rule_ids(e.value) == ["T-12"]
    with pytest.raises(VoucherRuleError):
        tds_masters.add_certificate(svc_conn, client_id, party, **{**kw, "certificate_no": "Y", "nature_key": "nosuch"})

    # used amount comes from items of POSTED vouchers only
    lines = f.balanced_lines(client_id)
    vid = f.draft(client_id, fy_id, lines)
    svc_conn.connection.driver_connection.execute(
        "INSERT INTO tds_voucher_items (client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
        "financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, "
        "rate_applied, rate_reason, lower_cert_id, tds_amount, tds_line_no, engine_version) "
        "VALUES (%s, %s, 1, 'tds', %s, 'contractor', 'it_act_2025', '393(1)', %s, '2026-05-10', '2026-05-10', 200000.00, 0, "
        "200000.00, 200000.00, 1, 'lower_certificate', %s, 2000.00, 1, 't')",
        (client_id, vid, party, fy_id, cert_id))
    c = tds_masters.list_certificates(svc_conn, client_id, party)[0]
    assert (c.amount_used, c.amount_left) == (Decimal("0.00"), Decimal("500000.00"))   # draft does not count
    f.approve(vid)
    f.post(vid, "PAY/2026-27/0001")
    check_deferred(f.conn)
    c = tds_masters.list_certificates(svc_conn, client_id, party)[0]
    assert (c.amount_used, c.amount_left, c.rate) == (Decimal("200000.00"), Decimal("300000.00"), Decimal("1.0000"))
    eng_cert = tds_masters.load_certificate(svc_conn, client_id, party, cert_id)
    assert (eng_cert.amount_used, eng_cert.max_amount, eng_cert.certificate_no) == (Decimal("200000.00"), Decimal("500000.00"), "LDC/26-27/1")
    assert d.lower_certs == []   # the earlier read was before the certificate

    # update: shorten only; deactivate hides it from the engine loaders
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.update_certificate(svc_conn, client_id, party, cert_id, valid_to=date(2027, 4, 1), actor="clerk")
    assert rule_ids(e.value) == ["T-12"]
    with pytest.raises(VoucherRuleError):
        tds_masters.update_certificate(svc_conn, client_id, party, cert_id, valid_to=date(2026, 3, 31), actor="clerk")
    tds_masters.update_certificate(svc_conn, client_id, party, cert_id, valid_to=date(2026, 12, 31), note="short", actor="clerk")
    assert tds_masters.list_certificates(svc_conn, client_id, party)[0].valid_to == date(2026, 12, 31)
    tds_masters.update_certificate(svc_conn, client_id, party, cert_id, is_active=False, actor="clerk")
    assert tds_masters.load_certificate(svc_conn, client_id, party, cert_id) is None
    assert tds_masters.load_certificates_of(svc_conn, client_id, party) == []
    assert audit_actions(svc_conn, "tds_certificate") == ["create", "update", "update"]


def test_T14_T30_roles_tan_and_194q_flag(svc_conn, f):
    client_id, fy_id = f.setup()
    other_client = f.client()
    payable = f.ledger(client_id, "TDS Payable", "duties_taxes")
    payable_c = f.ledger(client_id, "TDS Payable 194C", "duties_taxes")
    receivable = f.ledger(client_id, "TDS Receivable", "loans_advances_asset")
    interest = f.ledger(client_id, "Interest on TDS", "indirect_expenses")
    foreign = f.ledger(other_client, "Their Payable", "duties_taxes")
    expense = f.ledger(client_id, "Wrong Group", "indirect_expenses")

    for entries, expected in (
        ([("tds_payable", None, expense)], ["T-14"]),
        ([("tds_payable", None, foreign)], ["T-14"]),
        ([("tds_payable", "tcs_scrap", payable)], ["T-14"]),   # TCS nature on a TDS role
        ([("tds_receivable", None, payable)], ["T-14"]),
        ([("tds_payable", None, "not-a-uuid")], ["T-14"]),
    ):
        with pytest.raises(VoucherRuleError) as e:
            tds_masters.set_ledger_roles(svc_conn, client_id, entries, actor="clerk")
        assert rule_ids(e.value) == expected, entries
    assert tds_masters.get_ledger_roles(svc_conn, client_id) == []

    tds_masters.set_ledger_roles(svc_conn, client_id, [
        ("tds_payable", None, payable), ("tds_payable", "contractor", payable_c),
        ("tds_receivable", None, receivable), ("interest_expense", None, interest)], actor="clerk")
    roles = [(r["role"], r["nature_key"], r["ledger_name"]) for r in tds_masters.get_ledger_roles(svc_conn, client_id)]
    assert roles == [("interest_expense", None, "Interest on TDS"), ("tds_payable", None, "TDS Payable"),
                     ("tds_payable", "contractor", "TDS Payable 194C"), ("tds_receivable", None, "TDS Receivable")]
    assert tds_masters.ledger_for_role(svc_conn, client_id, "tds_payable", "contractor") == payable_c
    assert tds_masters.ledger_for_role(svc_conn, client_id, "tds_payable", "professional_fees") == payable   # falls back to the default
    assert tds_masters.ledger_for_role(svc_conn, client_id, "tcs_payable", None) is None                     # unmapped: caller refuses
    tds_masters.set_ledger_roles(svc_conn, client_id, [("tds_payable", None, payable)], actor="clerk")        # replaces all
    assert len(tds_masters.get_ledger_roles(svc_conn, client_id)) == 1
    assert audit_actions(svc_conn, "tds_ledger_roles") == ["update", "update"]

    # TAN (T-30) and the 194Q flag (never guessed: None until entered)
    with pytest.raises(VoucherRuleError) as e:
        tds_masters.set_tan(svc_conn, client_id, "MUMS1234A", actor="clerk")
    assert rule_ids(e.value) == ["T-30"]
    tds_masters.set_tan(svc_conn, client_id, " mums12345a ", actor="clerk")
    assert tds_masters.get_profile(svc_conn, client_id) == {"tan": "MUMS12345A", "fy_flags": []}
    assert tds_masters.fy_flag(svc_conn, client_id, fy_id) is None
    tds_masters.set_fy_flag(svc_conn, client_id, fy_id, True, "turnover above the limit", actor="clerk")
    tds_masters.set_fy_flag(svc_conn, client_id, fy_id, False, None, actor="clerk")
    assert tds_masters.fy_flag(svc_conn, client_id, fy_id) is False
    other_fy = f.fy(other_client)
    with pytest.raises(ServiceError) as e:
        tds_masters.set_fy_flag(svc_conn, client_id, other_fy, True, None, actor="clerk")   # another client's year
    assert e.value.code == "not_found"
    assert audit_actions(svc_conn, "tds_fy_flag") == ["create", "update"]
    assert audit_actions(svc_conn, "tds_profile") == ["update"]


def test_api_masters_end_to_end(api, f):
    client_id, fy_id = f.setup()
    party = f.ledger(client_id, "Sharma Advisors", "sundry_creditors")
    payable = f.ledger(client_id, "TDS Payable", "duties_taxes")
    base = f"/clients/{client_id}/tds"

    assert api.put(f"{base}/profile", json={"tan": "MUMS12345A"}).status_code == 400   # no X-User
    assert api.put(f"{base}/profile", json={"tan": "bad"}, headers=H).status_code == 422
    assert api.put(f"{base}/profile", json={"tan": "MUMS12345A"}, headers=H).json() == {"ok": True}
    assert api.put(f"{base}/fy-flags/{fy_id}", json={"prev_year_turnover_over_threshold": True}, headers=H).status_code == 200
    got = api.get(f"{base}/profile").json()
    assert got["tan"] == "MUMS12345A" and got["fy_flags"][0]["prev_year_turnover_over_threshold"] is True

    r = api.put(f"{base}/deductees/{party}", json={"pan": "ABCPE1234F", "pan_status": "valid", "deductee_type": "company"}, headers=H)
    assert r.status_code == 200 and r.json()["warnings"][0]["rule_id"] == "T-11"
    bad = api.put(f"{base}/deductees/{party}", json={"pan_status": "valid", "deductee_type": "company"}, headers=H)
    assert bad.status_code == 422 and bad.json()["errors"][0]["rule_id"] == "T-10"
    cert = api.post(f"{base}/deductees/{party}/certificates", headers=H, json={
        "certificate_no": "C1", "rate": "0", "max_amount": "100000.00", "valid_from": "2026-04-01", "valid_to": "2027-03-31"})
    assert cert.status_code == 201
    assert api.post(f"{base}/deductees/{party}/certificates", headers=H, json={
        "certificate_no": "C1", "rate": "0", "max_amount": "100000.00", "valid_from": "2026-04-01", "valid_to": "2027-03-31"}).status_code == 409
    listed = api.get(f"{base}/deductees", params={"q": "sharma"}).json()
    assert listed[0]["pan"] == "ABCPE1234F" and listed[0]["lower_certs"][0]["amount_left"] == "100000.00"
    assert listed[0]["lower_certs"][0]["rate"] == "0.0000" and listed[0]["pan_warning"]

    assert api.put(f"{base}/ledger-roles", json={"roles": [{"role": "tds_payable", "nature_key": None, "ledger_id": str(payable)}]},
                   headers=H).json() == {"ok": True}
    assert api.get(f"{base}/ledger-roles").json()["roles"][0]["ledger_name"] == "TDS Payable"

    rates = api.get("/tds/rates", params={"nature_key": "contractor", "on": "2026-04-01"}).json()
    assert rates["status"]["overall"] == "secondary_verified" and len(rates["rows"]) == 2
    assert rates["rule_status"]["worst"] == "secondary_verified"
    sm = api.get("/tds/section-map", params={"on": "2026-04-01"}).json()
    assert next(x for x in sm["rows"] if x["nature_key"] == "contractor")["sec_1961"] == "194C"
    for path in ("natures", "provisions", "due-dates", "interest-rules", "forms"):
        body = api.get(f"/tds/{path}", params={"on": "2026-04-01"}).json()
        assert body["on"] == "2026-04-01" and "overall" in body["status"], path
    look = api.get("/tds/rates/lookup", params={"nature_key": "contractor", "deductee_group": "company", "on": "2026-03-31"}).json()
    assert (look["act"], look["section_ref"], look["rate"], look["no_pan_rate"]) == ("it_act_1961", "194C", "2.0000", "20.0000")
    assert look["thresholds"]["annual"] == "100000.0000" and look["threshold_mode"] == "whole_amount"
    nr = api.get("/tds/rates/lookup", params={"nature_key": "contractor", "deductee_group": "others", "on": "2025-03-31"})
    assert nr.status_code == 422 and nr.json()["code"] == "no_rule"
    assert api.get("/tds/rates/lookup", params={"nature_key": "contractor", "deductee_group": "zzz"}).status_code == 422
