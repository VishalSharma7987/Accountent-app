"""Step 2.6: bank statement import, formats, listing, delete (service + API) against the test schema."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.db import connection, migrate
from app.main import app
from app.services import bank, client_setup
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration
D = Decimal

MAPPING = {
    "header_row": 1, "date_col": "Date", "date_format": "%d/%m/%Y", "description_col": "Narration",
    "reference_col": "Chq/Ref No", "debit_col": "Withdrawal", "credit_col": "Deposit", "balance_col": "Balance",
}
APRIL = (
    "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
    "05/04/2026,Rent paid,000123,10000.00,,90000.00\n"
    "06/04/2026,Sale receipt,UTR998,,5000.50,95000.50\n"
)
LATER = (  # starts after APRIL ends, opening = APRIL's closing
    "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
    "07/04/2026,Bank charges,,118.00,,94882.50\n"
)
OVERLAP = (
    "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
    "06/04/2026,Other,,1.00,,99999.00\n"
)


class World:
    def __init__(self, client_id, ids, other_ledger):
        self.client_id, self.ids, self.other_ledger = client_id, ids, other_ledger


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("ABC Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
        )
        ids = dict(created.ledger_ids)
        ids["HDFC Bank"] = client_setup.add_ledger(conn, created.client_id, "HDFC Bank", "bank_accounts", actor="setup")
        ids["Axis Bank"] = client_setup.add_ledger(conn, created.client_id, "Axis Bank", "bank_accounts", actor="setup")
        other = client_setup.create_client(
            conn, ClientProfile("Other Client", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
        )
        other_bank = client_setup.add_ledger(conn, other.client_id, "SBI", "bank_accounts", actor="setup")
    yield World(created.client_id, ids, other_bank)
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def code_of(info):
    return info.value.code


def new_format(conn, w, name="HDFC csv"):
    return bank.save_format(conn, w.client_id, name, MAPPING, actor="clerk")


def do_import(conn, w, content, *, fmt, ledger="HDFC Bank", name="april.csv", opening="100000.00", closing=None):
    return bank.import_statement(
        conn, w.client_id, w.ids[ledger], fmt, name, content.encode(), opening, closing, actor="clerk"
    )


# ===================================================================================================== formats


def test_formats_saved_listed_and_name_unique_per_client_ignoring_case(svc_conn, world):
    fmt = new_format(svc_conn, world)
    listed = bank.list_formats(svc_conn, world.client_id)
    assert [(f.id, f.name, f.mapping["debit_col"]) for f in listed] == [(fmt, "HDFC csv", "Withdrawal")]
    with pytest.raises(ServiceError) as info:
        bank.save_format(svc_conn, world.client_id, "  hdfc CSV ", MAPPING, actor="clerk")
    assert code_of(info) == "format_exists"
    with pytest.raises(ServiceError) as info:
        bank.save_format(svc_conn, world.client_id, "Bad", {**MAPPING, "header_row": 0}, actor="clerk")
    assert code_of(info) == "invalid_mapping"
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity = 'bank_format'") == 1


# ===================================================================================================== import


def test_R01_import_stores_statement_and_lines_and_audit(svc_conn, world):
    fmt = new_format(svc_conn, world)
    result = do_import(svc_conn, world, APRIL, fmt=fmt)
    assert (result.lines, result.opening_balance, result.closing_balance) == (2, D("100000.00"), D("95000.50"))
    rows = svc_conn.execute(text(
        "SELECT line_no, txn_date, description, reference, debit, credit, balance FROM bank_statement_lines "
        "WHERE statement_id = :s ORDER BY line_no"), {"s": result.statement_id}).all()
    assert [tuple(r) for r in rows] == [
        (1, date(2026, 4, 5), "Rent paid", "000123", D("10000.0000"), D("0.0000"), D("90000.0000")),
        (2, date(2026, 4, 6), "Sale receipt", "UTR998", D("0.0000"), D("5000.5000"), D("95000.5000")),
    ]
    st = bank.list_statements(svc_conn, world.client_id, world.ids["HDFC Bank"])
    assert [(s.file_name, s.period_from, s.period_to, s.opening_balance, s.closing_balance, s.line_count,
             s.matched_count) for s in st] == [
        ("april.csv", date(2026, 4, 5), date(2026, 4, 6), D("100000.00"), D("95000.50"), 2, 0)]
    assert bank.list_statements(svc_conn, world.client_id, world.ids["Axis Bank"]) == []
    audit = svc_conn.execute(text(
        "SELECT actor, action FROM audit_log WHERE entity = 'bank_statement' AND entity_id = :s"),
        {"s": result.statement_id}).all()
    assert [tuple(a) for a in audit] == [("clerk", "create")]


def test_R02_same_file_refused_overlap_refused_adjacent_period_accepted(svc_conn, world):
    fmt = new_format(svc_conn, world)
    do_import(svc_conn, world, APRIL, fmt=fmt)
    with pytest.raises(ServiceError) as info:
        do_import(svc_conn, world, APRIL, fmt=fmt, name="again.csv")
    assert code_of(info) == "statement_duplicate"
    assert "april.csv" in info.value.message and "05-04-2026 to 06-04-2026" in info.value.message
    with pytest.raises(ServiceError) as info:
        do_import(svc_conn, world, OVERLAP, fmt=fmt, name="overlap.csv", opening="100000.00")
    assert code_of(info) == "statement_overlap"
    assert "05-04-2026 to 06-04-2026" in info.value.message and "april.csv" in info.value.message
    # the next day onwards is fine, and another bank ledger may carry the very same dates and file
    do_import(svc_conn, world, LATER, fmt=fmt, name="later.csv", opening="95000.50")
    do_import(svc_conn, world, APRIL, fmt=fmt, ledger="Axis Bank", name="axis.csv")
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statements") == 3


def test_ledger_must_be_a_bank_ledger_of_this_client(svc_conn, world):
    fmt = new_format(svc_conn, world)
    for ledger_id, expected in (
        (world.ids["Cash"], "not under Bank Accounts"),
        (world.other_ledger, "does not exist for this client"),
    ):
        with pytest.raises(ServiceError) as info:
            bank.import_statement(svc_conn, world.client_id, ledger_id, fmt, "x.csv", APRIL.encode(), "100000",
                                  actor="clerk")
        assert code_of(info) == "invalid_bank_ledger" and expected in info.value.message
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statements") == 0


def test_R01_bad_file_rejected_whole_with_rows_and_nothing_stored(svc_conn, world):
    fmt = new_format(svc_conn, world)
    bad = APRIL.replace("95000.50", "95000.00")
    with pytest.raises(ServiceError) as info:
        do_import(svc_conn, world, bad, fmt=fmt)
    assert code_of(info) == "statement_invalid"
    assert info.value.details == [{"row": 3, "message": (
        "Row 3: running balance 95,000.00 does not agree with the previous balance 90,000.00 + credit 5,000.50 - "
        "debit 0.00 = 95,000.50")}]
    with pytest.raises(ServiceError) as info:  # opening balance not in file or format: required, never guessed
        do_import(svc_conn, world, APRIL, fmt=fmt, opening=None)
    assert code_of(info) == "statement_invalid" and "opening balance" in info.value.message
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statements") == 0
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statement_lines") == 0


def test_preview_writes_nothing_and_reports_problems(svc_conn, world):
    fmt = new_format(svc_conn, world)
    ok = bank.preview_statement(svc_conn, world.client_id, APRIL.encode(), format_id=fmt, opening_balance="100000")
    assert (len(ok.lines), ok.closing_balance, ok.problems) == (2, D("95000.50"), [])
    bad = bank.preview_statement(svc_conn, world.client_id, APRIL.encode(), mapping=MAPPING)
    assert [p.row for p in bad.problems] == [0]
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statements") == 0


# ===================================================================================================== delete


def test_delete_refused_while_a_line_is_matched_then_allowed(svc_conn, world):
    fmt = new_format(svc_conn, world)
    result = do_import(svc_conn, world, APRIL, fmt=fmt)
    first_line = scalar(svc_conn, "SELECT id FROM bank_statement_lines WHERE statement_id = :s AND line_no = 1",
                        s=result.statement_id)
    match_id = scalar(svc_conn, (
        "INSERT INTO recon_matches (client_id, bank_ledger_id, method, created_by) "
        "VALUES (:c, :l, 'manual', 'tester') RETURNING id"), c=world.client_id, l=world.ids["HDFC Bank"])
    svc_conn.execute(text("INSERT INTO recon_match_items (client_id, match_id, bank_line_id) VALUES (:c, :m, :b)"),
                     {"c": world.client_id, "m": match_id, "b": first_line})
    listed = bank.list_statements(svc_conn, world.client_id)
    assert (listed[0].line_count, listed[0].matched_count) == (2, 1)
    lines = bank.statement_lines(svc_conn, result.statement_id)
    assert [(x.line_no, x.match_id) for x in lines] == [(1, match_id), (2, None)]
    with pytest.raises(ServiceError) as info:
        bank.delete_statement(svc_conn, result.statement_id, actor="clerk")
    assert code_of(info) == "statement_in_use" and "1 line(s)" in info.value.message
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statement_lines") == 2

    svc_conn.execute(text("DELETE FROM recon_matches WHERE id = :m"), {"m": match_id})
    bank.delete_statement(svc_conn, result.statement_id, actor="clerk")
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statements") == 0
    assert scalar(svc_conn, "SELECT count(*) FROM bank_statement_lines") == 0
    audit = svc_conn.execute(text(
        "SELECT action, old_data->>'lines' FROM audit_log WHERE entity = 'bank_statement' ORDER BY created_at, action"
    )).all()
    assert sorted(tuple(a) for a in audit) == [("create", None), ("delete", "2")]
    with pytest.raises(ServiceError) as info:
        bank.delete_statement(svc_conn, result.statement_id, actor="clerk")
    assert code_of(info) == "not_found"


# ===================================================================================================== API


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[deps.get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


H = {"X-User": "clerk"}


def test_api_formats_preview_import_list_lines_delete(api, world):
    c = world.client_id
    assert api.post(f"/clients/{c}/bank-formats", json={"name": "HDFC csv", "mapping": MAPPING}).status_code == 400
    r = api.post(f"/clients/{c}/bank-formats", json={"name": "HDFC csv", "mapping": MAPPING}, headers=H)
    assert r.status_code == 201
    fmt = r.json()["format_id"]
    dup = api.post(f"/clients/{c}/bank-formats", json={"name": "hdfc csv", "mapping": MAPPING}, headers=H)
    assert (dup.status_code, dup.json()["code"]) == (409, "format_exists")
    bad_map = api.post(f"/clients/{c}/bank-formats", json={"name": "B", "mapping": {"header_row": 1}}, headers=H)
    assert (bad_map.status_code, bad_map.json()["code"]) == (422, "invalid_mapping")
    assert api.get(f"/clients/{c}/bank-formats").json() == [{"id": fmt, "name": "HDFC csv", "mapping": MAPPING}]

    files = {"file": ("april.csv", APRIL.encode(), "text/csv")}
    p = api.post(f"/clients/{c}/bank-statements/preview", files=files,
                 data={"format_id": fmt, "opening_balance": "100000"})
    assert p.status_code == 200
    assert p.json() == {
        "rows": [
            {"row": 2, "txn_date": "2026-04-05", "description": "Rent paid", "reference": "000123",
             "debit": "10000.00", "credit": "0.00", "balance": "90000.00"},
            {"row": 3, "txn_date": "2026-04-06", "description": "Sale receipt", "reference": "UTR998",
             "debit": "0.00", "credit": "5000.50", "balance": "95000.50"},
        ],
        "count": 2, "opening_balance": "100000.00", "closing_balance": "95000.50", "problems": [],
    }
    assert api.get(f"/clients/{c}/bank-statements").json() == []

    data = {"bank_ledger_id": str(world.ids["HDFC Bank"]), "format_id": fmt, "opening_balance": "100000"}
    assert api.post(f"/clients/{c}/bank-statements", files=files, data=data).status_code == 400
    r = api.post(f"/clients/{c}/bank-statements", files=files, data=data, headers=H)
    assert r.status_code == 201
    sid = r.json()["statement_id"]
    assert r.json() == {"statement_id": sid, "lines": 2, "opening_balance": "100000.00",
                        "closing_balance": "95000.50"}
    again = api.post(f"/clients/{c}/bank-statements", files=files, data=data, headers=H)
    assert (again.status_code, again.json()["code"]) == (409, "statement_duplicate")
    invalid = api.post(f"/clients/{c}/bank-statements", headers=H, data=data,
                       files={"file": ("x.csv", APRIL.replace("90000.00", "1.00").encode(), "text/csv")})
    assert invalid.status_code == 422 and invalid.json()["code"] == "statement_invalid"
    assert invalid.json()["details"][0]["row"] == 2

    listed = api.get(f"/clients/{c}/bank-statements", params={"bank_ledger_id": str(world.ids["HDFC Bank"])})
    assert listed.json() == [{
        "id": sid, "bank_ledger_id": str(world.ids["HDFC Bank"]), "file_name": "april.csv",
        "period_from": "2026-04-05", "period_to": "2026-04-06", "opening_balance": "100000.00",
        "closing_balance": "95000.50", "line_count": 2, "matched_count": 0}]
    lines = api.get(f"/bank-statements/{sid}/lines").json()
    assert [(x["line_no"], x["debit"], x["credit"], x["balance"], x["match_id"]) for x in lines] == [
        (1, "10000.00", "0.00", "90000.00", None), (2, "0.00", "5000.50", "95000.50", None)]
    assert api.delete(f"/bank-statements/{sid}").status_code == 400
    assert api.delete(f"/bank-statements/{sid}", headers=H).status_code == 204
    assert api.get(f"/bank-statements/{sid}/lines").status_code == 404
    assert api.get("/bank-statements/not-a-uuid/lines").status_code == 404
