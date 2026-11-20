"""The groups list exposes each group's id (needed as target_group_id when a Tally group or ledger is mapped). No database."""

from fastapi.testclient import TestClient

from app.api import groups as groups_api
from app.api.deps import get_conn
from app.main import app

CLIENT = "11111111-1111-1111-1111-111111111111"
SALES = "22222222-2222-2222-2222-222222222222"
CHILD = "33333333-3333-3333-3333-333333333333"


def test_groups_list_returns_group_ids_for_pickers(monkeypatch):
    tree = [{"id": SALES, "code": "sales_accounts", "name": "Sales Accounts", "nature": "income", "report": "trading",
             "is_system": True, "children": [
                 {"id": CHILD, "code": "x", "name": "X", "nature": "income", "report": "trading", "is_system": False, "children": []}]}]
    monkeypatch.setattr(groups_api.queries, "groups_tree", lambda conn, client_id: tree)
    app.dependency_overrides[get_conn] = lambda: None
    try:
        body = TestClient(app).get(f"/clients/{CLIENT}/groups").json()
    finally:
        app.dependency_overrides.pop(get_conn, None)
    assert body[0]["id"] == SALES
    assert body[0]["children"][0]["id"] == CHILD
