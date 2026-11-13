"""Phase 5 package D against the database: stock journals (transfer, write-off) - S-10, S-11, S-01, S-17, S-19, S-20 through
the services and the API. Every test runs in a rolled-back transaction. Expected values typed literally. Needs migration 0016."""

import uuid
from datetime import date as D
from decimal import Decimal

import pytest
from dbfactory import Factory, rejected
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine.inventory_journals import JournalLineInput
from app.engine.inventory_masters import OpeningInput
from app.main import app
from app.services import inventory_journals as svc
from app.services import inventory_masters as masters
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


class World:
    """Client with FY 2026-27 (one open period for the whole year), godowns Main / Shop, Widget with opening 10 in Main (value 100.00)."""

    def __init__(self, f: Factory, conn, mode: str = "block", with_policy: bool = True, year_period: bool = True):
        self.conn = conn
        self.client_id, self.fy_id = f.setup()
        if year_period:
            f.period(self.client_id, self.fy_id, "2026-04-01", "2027-03-31")
        self.main = masters.create_godown(conn, self.client_id, name="Main", actor="t")
        self.shop = masters.create_godown(conn, self.client_id, name="Shop", actor="t")
        self.widget = uuid.uuid4()
        conn.execute(text("INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (:i, :c, 'Widget', 'goods', '3004', 'NOS')"),
                     {"i": self.widget, "c": self.client_id})
        masters.put_stock_item(conn, self.client_id, self.widget, sku="W-1", default_godown_id=self.main, actor="t")
        if with_policy:
            masters.put_policy(conn, self.client_id, self.fy_id, valuation_method="fifo", negative_stock_mode=mode, actor="t")
        masters.replace_opening(conn, self.client_id, self.fy_id, [OpeningInput(self.widget, self.main, "10", "100.00")], actor="t")

    def line(self, qty, frm=None, to=None):
        return JournalLineInput(str(self.widget), str(frm or self.main), None if to is None else str(to), qty)

    def transfer(self, qty="4", on=D(2026, 4, 10), actor="clerk"):
        return svc.create_journal(self.conn, self.client_id, journal_type="transfer", journal_date=on, narration="Move to shop",
                                  reason_code=None, reason_note=None, lines=[self.line(qty, to=self.shop)], actor=actor)

    def writeoff(self, qty="2", frm=None, on=D(2026, 4, 10)):
        return svc.create_journal(self.conn, self.client_id, journal_type="write_off", journal_date=on, narration="Damaged",
                                  reason_code="damage", reason_note="Water damage", lines=[self.line(qty, frm=frm)], actor="clerk")

    def posted(self, view):
        svc.approve_journal(self.conn, self.client_id, view.row.id, actor="boss")
        return svc.post_journal(self.conn, self.client_id, view.row.id, actor="boss")

    def stock(self) -> dict:
        """Quantity on hand per godown name: opening + movements."""
        rows = self.conn.execute(text(
            "SELECT d.name, sum(q.q) FROM (SELECT godown_id, quantity AS q FROM stock_opening WHERE client_id = :c "
            "UNION ALL SELECT godown_id, CASE direction WHEN 'in' THEN quantity ELSE -quantity END FROM stock_movements WHERE client_id = :c) q "
            "JOIN godowns d ON d.id = q.godown_id GROUP BY d.name"), {"c": self.client_id})
        return {r[0]: r[1].quantize(Decimal("0.001")) for r in rows}

    def kinds(self) -> list[str]:
        return [r[0] for r in self.conn.execute(text("SELECT kind FROM stock_movements WHERE client_id = :c ORDER BY seq"), {"c": self.client_id})]

    def audit(self, action: str) -> int:
        return self.conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = 'stock_journal' AND action = :a"),
                                 {"c": self.client_id, "a": action}).scalar_one()


@pytest.fixture
def w(svc_conn, f) -> World:
    return World(f, svc_conn)


def rule_ids(exc: VoucherRuleError) -> list[str]:
    return [e.rule_id for e in exc.errors]


def test_S11_transfer_lifecycle_number_movements_and_audit(w, f):
    j = w.transfer("4")
    assert (j.row.status, j.row.journal_number, j.row.created_by) == ("draft", None, "clerk")
    assert [(x.line_no, x.item_name, x.quantity) for x in j.lines] == [(1, "Widget", Decimal("4.000"))]
    j = svc.update_journal(w.conn, w.client_id, j.row.id, journal_type="transfer", journal_date=D(2026, 4, 10), narration="Move 3 to shop",
                           reason_code=None, reason_note=None, lines=[w.line("3", to=w.shop)], actor="clerk")
    assert j.lines[0].quantity == Decimal("3.000") and j.row.narration == "Move 3 to shop"
    with pytest.raises(ServiceError) as exc:
        svc.post_journal(w.conn, w.client_id, j.row.id, actor="boss")
    assert exc.value.code == "journal_state" and "this one is draft" in exc.value.message
    assert w.kinds() == []  # a draft moves nothing
    a = svc.approve_journal(w.conn, w.client_id, j.row.id, actor="boss")
    assert (a.row.status, a.row.approved_by) == ("approved", "boss")
    p = svc.post_journal(w.conn, w.client_id, j.row.id, actor="boss")
    assert (p.row.status, p.row.journal_number, p.row.posted_by) == ("posted", "SJ/2026-27/0001", "boss")
    assert w.kinds() == ["transfer_out", "transfer_in"]
    assert w.stock() == {"Main": Decimal("7.000"), "Shop": Decimal("3.000")}
    j2 = w.posted(w.transfer("1"))
    assert j2.row.journal_number == "SJ/2026-27/0002"
    assert [w.audit(a) for a in ("create", "update", "approve", "post")] == [2, 1, 2, 2]
    # posted: immutable in the service and in the database
    with pytest.raises(ServiceError) as exc:
        svc.update_journal(w.conn, w.client_id, j.row.id, journal_type="transfer", journal_date=D(2026, 4, 10), narration="x",
                           reason_code=None, reason_note=None, lines=[w.line("1", to=w.shop)], actor="clerk")
    assert exc.value.code == "journal_state"
    with pytest.raises(ServiceError) as exc:
        svc.delete_journal(w.conn, w.client_id, j.row.id, actor="clerk")
    assert exc.value.code == "journal_state"
    with rejected(f.conn, message="can only be changed while the journal is draft"):
        f.conn.execute("UPDATE stock_journal_lines SET quantity = 9 WHERE journal_id = %s", (j.row.id,))
    with rejected(f.conn):
        f.conn.execute("UPDATE stock_journals SET narration = 'edited' WHERE id = %s", (j.row.id,))


def test_S10_writeoff_needs_reason_and_takes_stock_out_of_one_godown(w):
    with pytest.raises(VoucherRuleError) as exc:
        svc.create_journal(w.conn, w.client_id, journal_type="write_off", journal_date=D(2026, 4, 10), narration="Damaged",
                           reason_code=None, reason_note="  ", lines=[w.line("2")], actor="clerk")
    assert rule_ids(exc.value) == ["S-10", "S-10"]
    with pytest.raises(VoucherRuleError) as exc:
        w.writeoff("1.0005")
    assert [(e.rule_id, e.line_no) for e in exc.value.errors] == [("S-02", 1)]
    j = w.posted(w.writeoff("2"))
    assert (j.row.reason_code, j.row.reason_note, j.row.journal_number) == ("damage", "Water damage", "SJ/2026-27/0001")
    assert w.kinds() == ["write_off"]
    assert w.stock() == {"Main": Decimal("8.000")}


def test_S01_negative_stock_blocks_approve_in_block_mode_and_only_warns_in_warn_mode(w, f, svc_conn):
    j = w.transfer("11")
    with pytest.raises(ServiceError) as exc:
        svc.approve_journal(w.conn, w.client_id, j.row.id, actor="boss")
    assert exc.value.code == "negative_stock" and "-1.000" in exc.value.message and "Main" in exc.value.message
    assert svc.get_journal(w.conn, w.client_id, j.row.id).row.status == "draft"
    w2 = World(f, svc_conn, mode="warn")
    p = w2.posted(w2.transfer("11"))
    assert p.row.status == "posted" and [x.severity for x in p.warnings] == ["warning"]
    assert w2.stock() == {"Main": Decimal("-1.000"), "Shop": Decimal("11.000")}


def test_S19_backdated_transfer_rechecks_the_whole_chain(w):
    w.posted(w.writeoff("8", on=D(2026, 4, 10)))  # 10 - 8 = 2 left on 10-04
    late = w.transfer("5", on=D(2026, 4, 5))      # taking 5 out on 05-04 leaves 5, then the write-off of 8 would go to -3
    with pytest.raises(ServiceError) as exc:
        svc.approve_journal(w.conn, w.client_id, late.row.id, actor="boss")
    assert exc.value.code == "negative_stock" and "10-04-2026" in exc.value.message
    ok = w.transfer("2", on=D(2026, 4, 5))
    assert w.posted(ok).row.status == "posted"


def test_S11_reverse_appends_mirrors_once_and_needs_a_reason(w):
    j = w.posted(w.transfer("4"))
    with pytest.raises(VoucherRuleError) as exc:
        svc.reverse_journal(w.conn, w.client_id, j.row.id, reason=" ", actor="boss")
    assert rule_ids(exc.value) == ["S-11"]
    r = svc.reverse_journal(w.conn, w.client_id, j.row.id, reason="Wrong godown", actor="boss", reversal_date=D(2026, 4, 12))
    assert (r.row.status, r.row.reversed_by, r.row.reverse_reason, r.row.journal_number) == ("reversed", "boss", "Wrong godown", "SJ/2026-27/0001")
    assert w.kinds() == ["transfer_out", "transfer_in", "reversal_in", "reversal_out"]
    assert w.stock() == {"Main": Decimal("10.000"), "Shop": Decimal("0.000")}
    with pytest.raises(ServiceError) as exc2:
        svc.reverse_journal(w.conn, w.client_id, j.row.id, reason="again", actor="boss")
    assert exc2.value.code == "journal_state" and "already been reversed" in exc2.value.message
    assert w.audit("reverse") == 1
    w2 = w.posted(w.writeoff("3"))
    svc.reverse_journal(w.conn, w.client_id, w2.row.id, reason="Found again", actor="boss")
    assert w.stock() == {"Main": Decimal("10.000"), "Shop": Decimal("0.000")}


def test_S17_reversal_blocked_when_mirrors_would_make_stock_negative(w):
    t = w.posted(w.transfer("5"))
    w.posted(w.writeoff("5", frm=w.shop))  # Shop is now empty
    with pytest.raises(ServiceError) as exc:
        svc.reverse_journal(w.conn, w.client_id, t.row.id, reason="Mistake", actor="boss")
    assert exc.value.code == "journal_reversal_blocked" and "Shop" in exc.value.message
    assert svc.get_journal(w.conn, w.client_id, t.row.id).row.status == "posted"
    assert w.kinds() == ["transfer_out", "transfer_in", "write_off"]


def test_S20_date_must_be_in_an_open_period_at_save_approve_and_reversal(svc_conn, f):
    w = World(f, svc_conn, year_period=False)
    f.period(w.client_id, w.fy_id, "2026-04-01", "2026-04-30")
    may = f.period(w.client_id, w.fy_id, "2026-05-01", "2026-05-31")
    with pytest.raises(VoucherRuleError) as exc:
        w.transfer("1", on=D(2026, 6, 1))
    assert rule_ids(exc.value) == ["V-07"] and "No period" in exc.value.errors[0].message
    with pytest.raises(VoucherRuleError) as exc:
        w.transfer("1", on=D(2025, 3, 31))
    assert rule_ids(exc.value) == ["V-06"]
    may_journal = w.transfer("1", on=D(2026, 5, 3))
    posted = w.posted(w.transfer("1", on=D(2026, 4, 3)))
    f.conn.execute("UPDATE periods SET status = 'locked', locked_at = now(), locked_by = 't' WHERE id = %s", (may,))
    with pytest.raises(VoucherRuleError) as exc:
        svc.approve_journal(w.conn, w.client_id, may_journal.row.id, actor="boss")
    assert rule_ids(exc.value) == ["V-07"] and "locked" in exc.value.errors[0].message
    with pytest.raises(VoucherRuleError) as exc:
        svc.reverse_journal(w.conn, w.client_id, posted.row.id, reason="x", actor="boss", reversal_date=D(2026, 5, 10))
    assert rule_ids(exc.value) == ["V-07"]


def test_S04_no_policy_blocks_approve_and_draft_delete_is_audited(svc_conn, f):
    w = World(f, svc_conn, with_policy=False)
    j = w.transfer("1")
    with pytest.raises(ServiceError) as exc:
        svc.approve_journal(w.conn, w.client_id, j.row.id, actor="boss")
    assert exc.value.code == "no_policy"
    svc.delete_journal(w.conn, w.client_id, j.row.id, actor="clerk")
    assert w.audit("delete") == 1
    with pytest.raises(ServiceError) as exc:
        svc.get_journal(w.conn, w.client_id, j.row.id)
    assert exc.value.code == "not_found"


def test_S10_api_lifecycle_and_error_shapes(w, api):
    base = f"/clients/{w.client_id}/stock-journals"
    body = {"journal_type": "transfer", "journal_date": "2026-04-10", "narration": "Move",
            "lines": [{"item_id": str(w.widget), "from_godown_id": str(w.main), "to_godown_id": str(w.shop), "quantity": "4"}]}
    assert api.post(base, json=body).status_code == 400  # X-User is required
    created = api.post(base, json=body, headers=H)
    assert created.status_code == 201
    j = created.json()
    assert (j["status"], j["journal_number"], j["lines"][0]["quantity"], j["lines"][0]["item_name"]) == ("draft", None, "4.000", "Widget")
    bad = api.post(base, json={**body, "journal_type": "write_off"}, headers=H)
    assert bad.status_code == 422 and {e["rule_id"] for e in bad.json()["errors"]} == {"S-10"}
    assert api.post(f"{base}/{j['id']}/post", headers=H).json()["code"] == "journal_state"
    assert api.post(f"{base}/{j['id']}/approve", headers=H).json()["status"] == "approved"
    posted = api.post(f"{base}/{j['id']}/post", headers=H).json()
    assert (posted["status"], posted["journal_number"]) == ("posted", "SJ/2026-27/0001")
    assert api.put(f"{base}/{j['id']}", json=body, headers=H).status_code == 409
    assert api.delete(f"{base}/{j['id']}", headers=H).status_code == 409
    big = api.post(base, json={**body, "lines": [{**body["lines"][0], "quantity": "9"}]}, headers=H).json()
    blocked = api.post(f"{base}/{big['id']}/approve", headers=H)  # 6 left in Main
    assert blocked.status_code == 422 and blocked.json()["code"] == "negative_stock"
    listed = api.get(base, params={"status": "posted", "journal_type": "transfer", "from": "2026-04-01", "to": "2026-04-30"}).json()
    assert [x["journal_number"] for x in listed] == ["SJ/2026-27/0001"]
    rev = api.post(f"{base}/{j['id']}/reverse", json={"reason": "Wrong godown"}, headers=H).json()
    assert (rev["status"], rev["reverse_reason"], rev["reversed_by"]) == ("reversed", "Wrong godown", "clerk")
    assert api.get(f"{base}/{j['id']}").json()["status"] == "reversed"
    assert api.get(f"{base}/not-a-uuid").status_code == 404
