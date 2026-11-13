"""Step 5.0: the inventory tables of migration 0016 (database guards hold). NOT run by the planner: the main agent applies the
migration and runs `scripts/dbrun.sh pytest -m integration tests/integration/test_inventory_schema.py`.

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import uuid

import pytest
from dbfactory import Factory, rejected

pytestmark = pytest.mark.integration

GSTIN = "27AAPFU0939F1ZV"


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


class World:
    """client, FY 2026-27, two godowns, one goods item with a stock_items row, one registration."""

    def __init__(self, f: Factory):
        self.f = f
        self.conn = f.conn
        self.client_id, self.fy_id = f.setup()
        self.g1 = self.godown("Main")
        self.g2 = self.godown("Shop")
        self.item_id = self.item("Widget", "W-001")
        self.reg = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
            "VALUES (%s, %s, %s, '27', 'regular', '2026-04-01')", (self.reg, self.client_id, GSTIN))

    def godown(self, name):
        gid = uuid.uuid4()
        self.conn.execute("INSERT INTO godowns (id, client_id, name) VALUES (%s, %s, %s)", (gid, self.client_id, name))
        return gid

    def item(self, name, sku, kind="goods", stock=True):
        iid = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (%s, %s, %s, %s, %s, %s)",
            (iid, self.client_id, name, kind, "9983" if kind == "service" else "3004", None if kind == "service" else "NOS"))
        if stock:
            self.conn.execute(
                "INSERT INTO stock_items (item_id, client_id, sku, default_godown_id) VALUES (%s, %s, %s, %s)",
                (iid, self.client_id, sku, self.g1))
        return iid

    def invoice(self, vtype="purchase", qty="10", rate="12.00", tax_in_cost=False, post=True):
        """A voucher with one item line (exempt, 10 x 12.00 = 120.00) for the stock item; returns (voucher_id, item_line_no=1)."""
        lines = self.f.balanced_lines(self.client_id)
        vid = self.f.draft(self.client_id, self.fy_id, lines, vtype=vtype)
        self.conn.execute(
            "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, place_of_supply, "
            "invoice_date, invoice_value, engine_version) VALUES (%s, %s, %s, 'tax_invoice', 'b2b', '27', '2026-04-05', 120.00, 't')",
            (vid, self.client_id, self.reg))
        self.conn.execute(
            "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, item_id, description, hsn_sac, uqc, quantity, "
            "unit_rate, gross_amount, taxable_value, ledger_id, treatment, tax_in_cost, itc_category_key) "
            "VALUES (%s, %s, 1, %s, 'Widget', '3004', 'NOS', %s, %s, %s, %s, %s, 'exempt', %s, %s)",
            (self.client_id, vid, self.item_id, qty, rate, "120.00", "120.00", lines[0][0], tax_in_cost,
             "motor_vehicle" if tax_in_cost else None))
        if post:
            self.f.approve(vid)
            self.f.post(vid)
        return vid

    def movement(self, kind, direction, qty="10", value=None, vid=None, line=1, on="2026-04-05", ref=None, journal=None, jline=None,
                 godown=None):
        mid = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO stock_movements (id, client_id, financial_year_id, item_id, godown_id, movement_date, kind, direction, "
            "quantity, value, voucher_id, item_line_no, journal_id, journal_line_no, ref_movement_id, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'tester')",
            (mid, self.client_id, self.fy_id, self.item_id, godown or self.g1, on, kind, direction, qty, value, vid,
             line if vid and kind not in ("reversal_in", "reversal_out") else None, journal, jline, ref))
        return mid

    def journal(self, jtype="transfer", reason=None):
        jid = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO stock_journals (id, client_id, financial_year_id, journal_type, journal_date, narration, reason_code, "
            "reason_note, created_by) VALUES (%s, %s, %s, %s, '2026-04-10', 'test', %s, %s, 'tester')",
            (jid, self.client_id, self.fy_id, jtype, reason, "broken in transit" if reason else None))
        self.conn.execute(
            "INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, to_godown_id, quantity) "
            "VALUES (%s, %s, 1, %s, %s, %s, 4)",
            (jid, self.client_id, self.item_id, self.g1, self.g2 if jtype == "transfer" else None))
        return jid


@pytest.fixture
def w(f) -> World:
    return World(f)


def test_S02_quantity_with_a_fourth_decimal_is_rejected_not_rounded(w):
    with rejected(w.conn, constraint="stock_opening_qty_three_decimals"):
        w.conn.execute(
            "INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
            "VALUES (%s, %s, %s, %s, 1.0005, 10.00, 't')", (w.client_id, w.fy_id, w.item_id, w.g1))
    w.conn.execute(
        "INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
        "VALUES (%s, %s, %s, %s, 1.005, 10.00, 't')", (w.client_id, w.fy_id, w.item_id, w.g1))
    stored = w.conn.execute("SELECT quantity FROM stock_opening WHERE item_id = %s", (w.item_id,)).fetchone()[0]
    assert str(stored) == "1.0050"


def test_S08_opening_value_needs_quantity_and_is_two_decimals_and_unique_per_item_godown_year(w):
    insert = ("INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
              "VALUES (%s, %s, %s, %s, %s, %s, 't')")
    with rejected(w.conn, constraint="stock_opening_value_needs_qty"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, w.g1, "0", "5.00"))
    with rejected(w.conn, constraint="stock_opening_value_two_decimals"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, w.g1, "1", "10.005"))
    w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, w.g1, "100", "1000.00"))
    with rejected(w.conn, constraint="stock_opening_key"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, w.g1, "5", "50.00"))


def test_S03_only_goods_can_be_stock_items_and_sku_is_unique_per_client_ignoring_case(w):
    service = w.item("Consulting", "SVC", kind="service", stock=False)
    with rejected(w.conn, message="only a goods item can be a stock item"):
        w.conn.execute("INSERT INTO stock_items (item_id, client_id, sku, default_godown_id) VALUES (%s, %s, 'SVC', %s)",
                       (service, w.client_id, w.g1))
    other = w.item("Gadget", "G-1", stock=False)
    with rejected(w.conn, constraint="stock_items_client_sku_key"):
        w.conn.execute("INSERT INTO stock_items (item_id, client_id, sku, default_godown_id) VALUES (%s, %s, ' w-001 ', %s)",
                       (other, w.client_id, w.g1))


def test_S05_a_movement_needs_a_posted_voucher_and_matches_its_item_line(w):
    draft = w.invoice(post=False)
    with rejected(w.conn, message="stock moves only from an approved or posted voucher"):
        w.movement("purchase", "in", value="120.00", vid=draft)
    posted = w.invoice()
    with rejected(w.conn, message="does not match its invoice item line"):
        w.movement("purchase", "in", qty="9", value="120.00", vid=posted)
    with rejected(w.conn, message="the purchase cost must equal the taxable value"):
        w.movement("purchase", "in", value="130.00", vid=posted)
    with rejected(w.conn, message="cannot come from a purchase voucher"):
        w.movement("sale", "out", vid=posted)
    mid = w.movement("purchase", "in", value="120.00", vid=posted)
    assert mid is not None


def test_S14_purchase_cost_includes_tax_only_when_tax_is_part_of_the_cost(w):
    posted = w.invoice(tax_in_cost=True)  # no tax amounts on the line (exempt), so cost = taxable value
    w.movement("purchase", "in", value="120.00", vid=posted)


def test_S05_posted_movements_cannot_be_changed_or_deleted(w):
    posted = w.invoice()
    mid = w.movement("purchase", "in", value="120.00", vid=posted)
    with rejected(w.conn, message="stock movements cannot be changed or deleted"):
        w.conn.execute("UPDATE stock_movements SET quantity = 11 WHERE id = %s", (mid,))
    with rejected(w.conn, message="stock movements cannot be changed or deleted"):
        w.conn.execute("DELETE FROM stock_movements WHERE id = %s", (mid,))


def test_S13_the_cost_of_an_outward_movement_is_never_stored_and_kind_decides_direction(w):
    sale = w.invoice(vtype="sales", rate="15.00")
    with rejected(w.conn, constraint="stock_movements_value_only_for_purchase"):
        w.movement("sale", "out", value="100.00", vid=sale)
    with rejected(w.conn, constraint="stock_movements_direction_matches_kind"):
        w.movement("sale", "in", vid=sale)


def test_S12_returns_and_reversals_need_a_reference_to_a_movement_of_the_right_kind(w):
    purchase = w.invoice()
    p = w.movement("purchase", "in", value="120.00", vid=purchase)
    note = w.invoice(vtype="credit_note")
    with rejected(w.conn, constraint="stock_movements_ref_rule"):
        w.movement("sales_return", "in", vid=note)
    with rejected(w.conn, message="cannot refer to a purchase movement"):
        w.movement("sales_return", "in", vid=note, ref=p)
    debit = w.invoice(vtype="debit_note")
    w.movement("purchase_return", "out", vid=debit, ref=p)


def test_S17_a_movement_can_be_reversed_once_and_the_mirror_repeats_godown_and_quantity(w):
    purchase = w.invoice()
    p = w.movement("purchase", "in", value="120.00", vid=purchase)
    reversal = w.f.reverse(w.client_id, w.fy_id, purchase, w.f.balanced_lines(w.client_id))
    with rejected(w.conn, message="must repeat the godown and quantity"):
        w.movement("reversal_out", "out", qty="4", vid=reversal, ref=p)
    w.movement("reversal_out", "out", vid=reversal, ref=p)
    with rejected(w.conn, constraint="stock_movements_reversed_once_key"):
        w.movement("reversal_out", "out", vid=reversal, ref=p)


def test_S04_the_valuation_method_cannot_change_once_the_year_has_movements(w):
    w.conn.execute(
        "INSERT INTO inventory_settings (client_id, financial_year_id, valuation_method, set_by) VALUES (%s, %s, 'fifo', 't')",
        (w.client_id, w.fy_id))
    mode = w.conn.execute("SELECT negative_stock_mode FROM inventory_settings WHERE client_id = %s", (w.client_id,)).fetchone()[0]
    assert mode == "block"
    w.conn.execute("UPDATE inventory_settings SET negative_stock_mode = 'warn' WHERE client_id = %s", (w.client_id,))
    w.conn.execute("UPDATE inventory_settings SET valuation_method = 'wa_moving' WHERE client_id = %s", (w.client_id,))
    w.movement("purchase", "in", value="120.00", vid=w.invoice())
    with rejected(w.conn, message="cannot be changed once the year has stock movements"):
        w.conn.execute("UPDATE inventory_settings SET valuation_method = 'fifo' WHERE client_id = %s", (w.client_id,))
    with rejected(w.conn, message="cannot be deleted"):
        w.conn.execute("DELETE FROM inventory_settings WHERE client_id = %s", (w.client_id,))


def test_S18_the_unit_of_an_item_with_stock_cannot_change(w):
    w.conn.execute("UPDATE gst_items SET uqc = 'KGS' WHERE id = %s", (w.item_id,))  # no stock entries yet: allowed
    w.conn.execute(
        "INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
        "VALUES (%s, %s, %s, %s, 5, 50.00, 't')", (w.client_id, w.fy_id, w.item_id, w.g1))
    with rejected(w.conn, message="the unit or kind of an item with stock entries cannot be changed"):
        w.conn.execute("UPDATE gst_items SET uqc = 'NOS' WHERE id = %s", (w.item_id,))
    w.conn.execute("UPDATE gst_items SET name = 'Widget Large' WHERE id = %s", (w.item_id,))   # other fields stay editable


def test_S10_a_write_off_needs_a_reason_and_a_transfer_needs_two_different_godowns(w):
    with rejected(w.conn, constraint="stock_journals_writeoff_reason"):
        w.conn.execute(
            "INSERT INTO stock_journals (client_id, financial_year_id, journal_type, journal_date, narration, created_by) "
            "VALUES (%s, %s, 'write_off', '2026-04-10', 'x', 't')", (w.client_id, w.fy_id))
    with rejected(w.conn, constraint="stock_journals_writeoff_reason"):  # a transfer has no reason code
        w.conn.execute(
            "INSERT INTO stock_journals (client_id, financial_year_id, journal_type, journal_date, narration, reason_code, "
            "reason_note, created_by) VALUES (%s, %s, 'transfer', '2026-04-10', 'x', 'damage', 'n', 't')", (w.client_id, w.fy_id))
    jid = w.journal("transfer")
    with rejected(w.conn, constraint="stock_journal_lines_godowns_differ"):
        w.conn.execute(
            "INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, to_godown_id, quantity) "
            "VALUES (%s, %s, 2, %s, %s, %s, 1)", (jid, w.client_id, w.item_id, w.g1, w.g1))
    with rejected(w.conn, message="a transfer line needs a destination godown"):
        w.conn.execute(
            "INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, quantity) "
            "VALUES (%s, %s, 2, %s, %s, 1)", (jid, w.client_id, w.item_id, w.g1))
    wo = w.journal("write_off", reason="damage")
    with rejected(w.conn, message="a write-off line has no destination godown"):
        w.conn.execute(
            "INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, to_godown_id, quantity) "
            "VALUES (%s, %s, 2, %s, %s, %s, 1)", (wo, w.client_id, w.item_id, w.g1, w.g2))


def test_S11_stock_journal_lifecycle_numbers_and_freeze_after_posting(w):
    jid = w.journal("transfer")
    with rejected(w.conn, message="must be approved before posting"):
        w.conn.execute("UPDATE stock_journals SET status = 'posted', journal_number = 'SJ/2026-27/0001', approved_by = 'a', "
                       "posted_by = 'a' WHERE id = %s", (jid,))
    w.conn.execute("UPDATE stock_journals SET status = 'approved', approved_by = 'a', approved_at = now() WHERE id = %s", (jid,))
    with rejected(w.conn, constraint="stock_journals_number_when_posted"):
        w.conn.execute("UPDATE stock_journals SET status = 'posted', posted_by = 'a', posted_at = now() WHERE id = %s", (jid,))
    w.conn.execute("UPDATE stock_journals SET status = 'posted', journal_number = 'SJ/2026-27/0001', posted_by = 'a', "
                   "posted_at = now() WHERE id = %s", (jid,))
    with rejected(w.conn, message="can only be changed while the journal is draft"):
        w.conn.execute("UPDATE stock_journal_lines SET quantity = 5 WHERE journal_id = %s", (jid,))
    with rejected(w.conn, message="can only be changed while the journal is draft"):
        w.conn.execute("DELETE FROM stock_journal_lines WHERE journal_id = %s", (jid,))
    with rejected(w.conn, message="a posted stock journal can only be reversed"):
        w.conn.execute("UPDATE stock_journals SET status = 'approved' WHERE id = %s", (jid,))
    with rejected(w.conn, message="cannot be deleted"):
        w.conn.execute("DELETE FROM stock_journals WHERE id = %s", (jid,))
    with rejected(w.conn, constraint="stock_journals_reversed_fields"):  # a reason is compulsory
        w.conn.execute("UPDATE stock_journals SET status = 'reversed', reversed_by = 'a', reversed_at = now() WHERE id = %s", (jid,))
    w.conn.execute("UPDATE stock_journals SET status = 'reversed', reversed_by = 'a', reversed_at = now(), "
                   "reverse_reason = 'wrong godown' WHERE id = %s", (jid,))
    with rejected(w.conn, message="a reversed stock journal cannot be changed"):
        w.conn.execute("UPDATE stock_journals SET narration = 'x' WHERE id = %s", (jid,))


def test_S11_journal_numbers_are_issued_one_at_a_time(w):
    w.conn.execute("INSERT INTO stock_journal_sequences (client_id, financial_year_id, last_number) VALUES (%s, %s, 1)",
                   (w.client_id, w.fy_id))
    with rejected(w.conn, message="issued one at a time"):
        w.conn.execute("UPDATE stock_journal_sequences SET last_number = 3 WHERE client_id = %s", (w.client_id,))
    w.conn.execute("UPDATE stock_journal_sequences SET last_number = 2 WHERE client_id = %s", (w.client_id,))
    with rejected(w.conn, message="cannot be deleted"):
        w.conn.execute("DELETE FROM stock_journal_sequences WHERE client_id = %s", (w.client_id,))


def test_S10_journal_movements_follow_their_line_and_type(w):
    jid = w.journal("transfer")
    with rejected(w.conn, message="stock moves only from an approved or posted stock journal"):
        w.movement("transfer_out", "out", qty="4", journal=jid, jline=1)
    w.conn.execute("UPDATE stock_journals SET status = 'approved', approved_by = 'a' WHERE id = %s", (jid,))
    with rejected(w.conn, message="does not match its stock journal line"):
        w.movement("transfer_out", "out", qty="5", journal=jid, jline=1)
    with rejected(w.conn, message="does not match its stock journal line"):
        w.movement("transfer_in", "in", qty="4", journal=jid, jline=1, godown=w.g1)   # destination must be the line's to-godown
    with rejected(w.conn, message="does not fit this journal type"):
        w.movement("write_off", "out", qty="4", journal=jid, jline=1)
    w.movement("transfer_out", "out", qty="4", journal=jid, jline=1)
    w.movement("transfer_in", "in", qty="4", journal=jid, jline=1, godown=w.g2)


def test_S12_voucher_stock_lines_are_draft_only_and_belong_to_the_clients_godown(w):
    vid = w.invoice(vtype="credit_note", post=False)
    w.conn.execute("INSERT INTO voucher_stock_lines (voucher_id, client_id, item_line_no, godown_id) VALUES (%s, %s, 1, %s)",
                   (vid, w.client_id, w.g2))
    other_client, _ = w.f.setup()
    foreign = uuid.uuid4()
    w.conn.execute("INSERT INTO godowns (id, client_id, name) VALUES (%s, %s, 'Foreign')", (foreign, other_client))
    with rejected(w.conn, constraint="voucher_stock_lines_godown_fk"):
        w.conn.execute("UPDATE voucher_stock_lines SET godown_id = %s WHERE voucher_id = %s", (foreign, vid))
    w.f.approve(vid)
    with rejected(w.conn, message="can only be changed while the voucher is draft"):
        w.conn.execute("UPDATE voucher_stock_lines SET godown_id = %s WHERE voucher_id = %s", (w.g1, vid))


def test_S15_nrv_is_two_decimals_not_negative_and_needs_a_basis(w):
    insert = ("INSERT INTO stock_nrv_entries (client_id, financial_year_id, item_id, as_on_date, nrv_per_unit, basis_note, entered_by) "
              "VALUES (%s, %s, %s, '2027-03-31', %s, %s, 't')")
    with rejected(w.conn, constraint="stock_nrv_entries_two_decimals"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, "13.505", "price list"))
    with rejected(w.conn, constraint="stock_nrv_entries_nrv_nonneg"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, "-1", "price list"))
    with rejected(w.conn, constraint="stock_nrv_entries_basis_not_blank"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, "13.50", "  "))
    w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, "13.50", "dealer price list Mar-2027"))
    with rejected(w.conn, constraint="stock_nrv_entries_key"):
        w.conn.execute(insert, (w.client_id, w.fy_id, w.item_id, "14.00", "again"))


def test_the_inventory_tables_are_closed_to_the_api_roles_by_rls(w):
    tables = ["godowns", "inventory_settings", "stock_items", "stock_opening", "stock_journals", "stock_journal_lines",
              "stock_journal_sequences", "stock_movements", "voucher_stock_lines", "stock_nrv_entries"]
    rows = w.conn.execute(
        "SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relname = ANY(%s)",
        (tables,)).fetchall()
    assert set(rows) == {(t, True) for t in tables}
