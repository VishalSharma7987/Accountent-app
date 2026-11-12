"""Excel import endpoints. NEEDS the step 1.7 API (app.api.deps) and the router registered in app/main.py:
run this file AFTER merging steps 1.7 and 1.8. Until then the module is skipped.

Pattern: FastAPI TestClient; `get_conn` is overridden by the rolled-back `svc_conn` fixture, so nothing is saved.
"""

import io
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from xlsx_helpers import GOOD_ROWS, make_xlsx

deps = pytest.importorskip("app.api.deps", reason="step 1.7 (app/api/deps.py) is not merged yet")
from fastapi.testclient import TestClient

from app.db import connection, migrate
from app.main import app
from app.services import client_setup
from app.services.client_setup import ClientProfile

pytestmark = pytest.mark.integration
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(scope="module")
def client_id(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("ABC Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
        )
        client_setup.add_ledger(conn, created.client_id, "Rahul Enterprises", "sundry_debtors", actor="setup")
    yield str(created.client_id)
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[deps.get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(data: bytes):
    return {"file": ("vouchers.xlsx", data, XLSX)}


def test_template_download_is_an_xlsx_with_the_import_columns(api, client_id):
    response = api.get(f"/clients/{client_id}/imports/vouchers/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(XLSX)
    assert "voucher_import_template.xlsx" in response.headers["content-disposition"]
    header = [c.value for c in load_workbook(io.BytesIO(response.content))["Vouchers"][1]]
    assert header[:3] == ["ref_id", "date", "voucher_type"] and len(header) == 9


def test_dry_run_returns_each_voucher_with_status_and_row_numbered_errors(api, client_id):
    rows = GOOD_ROWS[:2] + [["V9", "2026-04-07", "payment", "Rent", 10, None, "Bad", None, None],
                            ["V9", "2026-04-07", "payment", "Cash", None, 9, "Bad", None, None]]
    response = api.post(f"/clients/{client_id}/imports/vouchers/dry-run", files=upload(make_xlsx(rows)))
    assert response.status_code == 200
    assert response.json() == {
        "vouchers": [
            {"ref_id": "V1", "first_row": 2, "status": "ok", "errors": []},
            {"ref_id": "V9", "first_row": 4, "status": "error", "errors": [{
                "rule_id": "V-04", "line_no": None, "row": 4,
                "message": "Debit 10.00 and Credit 9.00 are not equal (difference 1.00)"}]},
        ],
        "ok_count": 1, "error_count": 1,
    }


def test_commit_creates_drafts_and_needs_the_x_user_header(api, svc_conn, client_id):
    url = f"/clients/{client_id}/imports/vouchers/commit"
    assert api.post(url, files=upload(make_xlsx(GOOD_ROWS))).status_code == 400
    response = api.post(url, files=upload(make_xlsx(GOOD_ROWS)), data={"ref_ids": "V1"}, headers={"X-User": "clerk"})
    assert response.status_code == 200
    body = response.json()
    assert [c["ref_id"] for c in body["created"]] == ["V1"]
    assert body["skipped"] == [{"ref_id": "V2", "reason": "not selected"}]
    assert svc_conn.execute(text("SELECT status, created_by FROM vouchers")).all() == [("draft", "clerk")]


def test_commit_with_no_ref_ids_imports_every_ok_voucher(api, client_id):
    response = api.post(f"/clients/{client_id}/imports/vouchers/commit", files=upload(make_xlsx(GOOD_ROWS)),
                        data={"ref_ids": ""}, headers={"X-User": "clerk"})
    assert [c["ref_id"] for c in response.json()["created"]] == ["V1", "V2"]


def test_an_unreadable_file_is_a_422_with_the_service_error_shape(api, client_id):
    response = api.post(f"/clients/{client_id}/imports/vouchers/dry-run", files=upload(b"junk"))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_file"
    assert response.json()["message"] == "The upload is not a valid Excel (.xlsx) file."
