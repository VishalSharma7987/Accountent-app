"""Step 1.4: client setup service (create client, ledgers, opening balances) against the test schema."""

from datetime import date
from decimal import Decimal

import pytest
from dbfactory import Factory, check_deferred
from sqlalchemy import text

from app.db import connection, migrate
from app.engine.models import Balance
from app.services import audit, client_setup
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

D = Decimal
FY_2026 = date(2026, 4, 1)


def profile(**overrides) -> ClientProfile:
    base = {"name": "ABC Traders", "entity_type": "proprietorship", "business_type": "trading", "gst_type": "regular"}
    base.update(overrides)
    return ClientProfile(**base)


def create(conn, **overrides):
    args = {"fy_start": FY_2026, "actor": "tester", "proprietor_name": "Ramesh Kumar"}
    prof = profile(**{k: overrides.pop(k) for k in list(overrides) if k in ClientProfile.__dataclass_fields__})
    args.update(overrides)
    return client_setup.create_client(conn, prof, **args)


def q(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def raw(conn) -> Factory:
    return Factory(conn.connection.driver_connection)


def count(conn, table):
    return scalar(conn, f"SELECT count(*) FROM {table}")


# ============================================================================================ create_client

PERIODS_2026_27 = [
    (date(2026, 4, 1), date(2026, 4, 30)), (date(2026, 5, 1), date(2026, 5, 31)),
    (date(2026, 6, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 7, 31)),
    (date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30)),
    (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 30)),
    (date(2026, 12, 1), date(2026, 12, 31)), (date(2027, 1, 1), date(2027, 1, 31)),
    (date(2027, 2, 1), date(2027, 2, 28)), (date(2027, 3, 1), date(2027, 3, 31)),
]

PROPRIETOR_TRADING_LEDGERS = {
    "Cash": "Cash-in-hand", "Suspense A/c": "Suspense A/c",
    "Ramesh Kumar Capital A/c": "Capital Account", "Drawings A/c": "Capital Account",
    "Purchases": "Purchase Accounts", "Sales": "Sales Accounts", "Purchase Returns": "Purchase Accounts",
    "Sales Returns": "Sales Accounts", "Opening Stock": "Stock-in-hand",
    "Rent": "Indirect Expenses", "Salary": "Indirect Expenses", "Electricity": "Indirect Expenses",
    "Telephone & Internet": "Indirect Expenses", "Printing & Stationery": "Indirect Expenses",
    "Travelling": "Indirect Expenses", "Repairs & Maintenance": "Indirect Expenses",
    "Bank Charges": "Indirect Expenses", "Office Expenses": "Indirect Expenses",
}


def test_create_client_stores_the_profile_year_periods_and_template_ledgers(svc_conn):
    created = create(svc_conn, pan="ABCDE1234F", state_code="27", legal_name="ABC Traders (Prop.)",
                     books_begin_date=date(2026, 4, 1))

    client = q(svc_conn, "SELECT name, legal_name, entity_type, business_type, pan, state_code, gst_type, "
                         "books_begin_date, is_active FROM clients WHERE id = :id", id=created.client_id)
    assert client == [("ABC Traders", "ABC Traders (Prop.)", "proprietorship", "trading", "ABCDE1234F", "27",
                       "regular", date(2026, 4, 1), True)]

    assert q(svc_conn, "SELECT start_date, end_date FROM financial_years WHERE id = :id", id=created.financial_year_id) == [
        (date(2026, 4, 1), date(2027, 3, 31))
    ]
    periods = q(svc_conn, "SELECT period_start, period_end, status, locked_at FROM periods "
                          "WHERE financial_year_id = :fy ORDER BY period_start", fy=created.financial_year_id)
    assert periods == [(s, e, "open", None) for s, e in PERIODS_2026_27]

    ledgers = dict(q(svc_conn, "SELECT l.name, g.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
                              "WHERE l.client_id = :c", c=created.client_id))
    assert ledgers == PROPRIETOR_TRADING_LEDGERS
    assert set(created.ledger_ids) == set(PROPRIETOR_TRADING_LEDGERS)


def test_create_client_for_a_leap_year_ends_february_on_the_29th(svc_conn):
    created = create(svc_conn, fy_start=date(2027, 4, 1))
    february = q(svc_conn, "SELECT period_end FROM periods WHERE financial_year_id = :fy AND period_start = '2028-02-01'",
                 fy=created.financial_year_id)
    assert february == [(date(2028, 2, 29),)]


def test_create_client_partnership_gets_partner_capital_and_current_accounts(svc_conn):
    created = create(svc_conn, entity_type="partnership", business_type="service", partners=["Anil Shah", "Bina Shah"],
                     proprietor_name=None)
    names = {r[0] for r in q(svc_conn, "SELECT name FROM ledgers WHERE client_id = :c", c=created.client_id)}
    assert {"Anil Shah Capital A/c", "Anil Shah Current A/c", "Bina Shah Capital A/c", "Bina Shah Current A/c",
            "Service Income"} <= names
    assert "Drawings A/c" not in names and "Sales" not in names


def test_create_client_company_gets_share_capital_and_surplus_in_reserves(svc_conn):
    created = create(svc_conn, entity_type="company", business_type="manufacturing", proprietor_name=None)
    groups = dict(q(svc_conn, "SELECT l.name, g.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
                              "WHERE l.client_id = :c", c=created.client_id))
    assert groups["Share Capital"] == "Capital Account"
    assert groups["Surplus in Profit & Loss"] == "Reserves & Surplus"
    assert groups["Raw Material Purchases"] == "Purchase Accounts"


def test_create_client_writes_an_audit_row_for_everything_it_creates(svc_conn):
    created = create(svc_conn)
    rows = q(svc_conn, "SELECT entity, action, actor, count(*) FROM audit_log WHERE client_id = :c "
                       "GROUP BY entity, action, actor ORDER BY entity", c=created.client_id)
    assert rows == [
        ("client", "create", "tester", 1),
        ("financial_year", "create", "tester", 1),
        ("ledger", "create", "tester", 18),
        ("period", "create", "tester", 12),
    ]
    new_data = scalar(svc_conn, "SELECT new_data FROM audit_log WHERE entity = 'client' AND client_id = :c", c=created.client_id)
    assert new_data["name"] == "ABC Traders" and new_data["entity_type"] == "proprietorship"
    assert scalar(svc_conn, "SELECT old_data IS NULL FROM audit_log WHERE entity = 'client' AND client_id = :c", c=created.client_id)


def test_create_client_is_all_or_nothing(svc_conn, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(audit, "log_many", boom)
    with pytest.raises(RuntimeError, match="audit failed"):
        create(svc_conn)
    # the client, year, periods and ledgers inserted before the failure are gone again
    assert [count(svc_conn, t) for t in ("clients", "financial_years", "periods", "ledgers", "audit_log")] == [0] * 5
    monkeypatch.undo()
    create(svc_conn)  # and the connection is still usable
    assert count(svc_conn, "clients") == 1


@pytest.mark.parametrize(
    ("overrides", "code", "message"),
    [
        ({"name": "  "}, "invalid_profile", "client name is required"),
        ({"entity_type": "trust"}, "invalid_profile", "Unknown entity type 'trust'"),
        ({"business_type": "farming"}, "invalid_profile", "Unknown business type 'farming'"),
        ({"gst_type": "exempt"}, "invalid_profile", "Unknown GST type 'exempt'"),
        ({"fy_start": date(2026, 5, 1)}, "invalid_profile", "A financial year must start on 1 April (got 01-05-2026)."),
        ({"proprietor_name": " "}, "invalid_profile", "needs the proprietor's name"),
        ({"entity_type": "partnership", "proprietor_name": None, "partners": []}, "invalid_profile", "at least one partner"),
        ({"actor": " "}, "invalid_actor", "who is making this change"),
    ],
)
def test_create_client_rejects_bad_input_and_saves_nothing(svc_conn, overrides, code, message):
    with pytest.raises(ServiceError) as info:
        create(svc_conn, **overrides)
    assert info.value.code == code
    assert message in info.value.message
    assert [count(svc_conn, t) for t in ("clients", "financial_years", "periods", "ledgers", "audit_log")] == [0] * 5


@pytest.fixture(scope="module")
def shared_clients(test_engine, test_conn):
    """Two committed clients built ONCE for the module (the create_client tests above build their own). The tests
    below run in rolled-back transactions. Cleaned (guarded) when the module ends."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        first = create(conn)
        second = create(conn, name="Other Client")
    yield first, second
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


@pytest.fixture
def client_a(shared_clients):
    return shared_clients[0]


@pytest.fixture
def client_b(shared_clients):
    return shared_clients[1]


# ================================================================================================ add_ledger


def test_add_ledger_creates_it_in_a_system_group_and_logs_it(svc_conn, client_a, client_b):
    created = client_a
    ledger_id = client_setup.add_ledger(svc_conn, created.client_id, "  HDFC Bank  ", "bank_accounts", actor="tester")
    assert q(svc_conn, "SELECT l.name, g.name, l.is_active FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
                       "WHERE l.id = :id", id=ledger_id) == [("HDFC Bank", "Bank Accounts", True)]
    log = q(svc_conn, "SELECT action, entity, new_data->>'name' FROM audit_log WHERE entity_id = :id", id=ledger_id)
    assert log == [("create", "ledger", "HDFC Bank")]


def test_add_ledger_in_the_clients_own_sub_group(svc_conn, client_a, client_b):
    created = client_a
    svc_conn.execute(text("INSERT INTO account_groups (client_id, code, name, parent_id, nature, report) "
                          "SELECT :c, 'petty_bank', 'Petty Bank', id, nature, report FROM account_groups "
                          "WHERE code = 'bank_accounts' AND client_id IS NULL"), {"c": created.client_id})
    ledger_id = client_setup.add_ledger(svc_conn, created.client_id, "Petty Bank A/c", "petty_bank", actor="tester")
    assert scalar(svc_conn, "SELECT g.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id WHERE l.id = :id",
                  id=ledger_id) == "Petty Bank"


def test_add_ledger_with_a_name_already_used_is_refused_ignoring_case(svc_conn, client_a, client_b):
    created = client_a
    with pytest.raises(ServiceError) as info:
        client_setup.add_ledger(svc_conn, created.client_id, "cash", "cash_in_hand", actor="tester")
    assert (info.value.code, info.value.message) == ("duplicate_ledger", "A ledger named 'cash' already exists for this client.")


def test_add_ledger_with_an_unknown_group_or_another_clients_group_is_refused(svc_conn, client_a, client_b):
    a, b = client_a, client_b
    svc_conn.execute(text("INSERT INTO account_groups (client_id, code, name, parent_id, nature, report) "
                          "SELECT :c, 'mine', 'Mine', id, nature, report FROM account_groups "
                          "WHERE code = 'bank_accounts' AND client_id IS NULL"), {"c": a.client_id})
    for bad in ("no_such_group", "mine"):
        with pytest.raises(ServiceError) as info:
            client_setup.add_ledger(svc_conn, b.client_id, "X Ledger", bad, actor="tester")
        assert (info.value.code, info.value.message) == ("not_found", f"Account group '{bad}' does not exist for this client.")


def test_add_ledger_needs_a_name_a_known_client_and_an_actor(svc_conn, client_a, client_b):
    created = client_a
    for args, code in (
        (("  ", "bank_accounts"), "invalid_ledger"),
    ):
        with pytest.raises(ServiceError) as info:
            client_setup.add_ledger(svc_conn, created.client_id, *args, actor="tester")
        assert info.value.code == code
    with pytest.raises(ServiceError) as info:
        client_setup.add_ledger(svc_conn, "00000000-0000-0000-0000-000000000000", "X", "bank_accounts", actor="tester")
    assert info.value.code == "not_found"
    with pytest.raises(ServiceError) as info:
        client_setup.add_ledger(svc_conn, created.client_id, "X", "bank_accounts", actor="")
    assert info.value.code == "invalid_actor"


# ========================================================================================= deactivate_ledger


def ids(created):
    return created.ledger_ids


def post_payment(conn, created, amount="5000"):
    """Rent Dr / Cash Cr, posted, in the client's first year."""
    f = raw(conn)
    voucher = f.draft(created.client_id, created.financial_year_id,
                      [(ids(created)["Rent"], amount, "0"), (ids(created)["Cash"], "0", amount)], vtype="payment")
    f.approve(voucher)
    f.post(voucher)
    check_deferred(f.conn)
    return f, voucher


def test_deactivate_a_ledger_with_nothing_on_it(svc_conn, client_a, client_b):
    created = client_a
    client_setup.deactivate_ledger(svc_conn, created.client_id, ids(created)["Bank Charges"], actor="tester")
    assert scalar(svc_conn, "SELECT is_active FROM ledgers WHERE id = :id", id=ids(created)["Bank Charges"]) is False
    log = q(svc_conn, "SELECT old_data->>'is_active', new_data->>'is_active' FROM audit_log "
                      "WHERE entity_id = :id AND action = 'deactivate'", id=ids(created)["Bank Charges"])
    assert log == [("true", "false")]


def test_deactivate_is_blocked_by_a_posted_balance(svc_conn, client_a, client_b):
    created = client_a
    post_payment(svc_conn, created)
    with pytest.raises(ServiceError) as info:
        client_setup.deactivate_ledger(svc_conn, created.client_id, ids(created)["Cash"], actor="tester")
    assert (info.value.code, info.value.message) == (
        "ledger_in_use", "Ledger 'Cash' cannot be deactivated: it has a closing balance of 5,000.00 Cr.")
    assert scalar(svc_conn, "SELECT is_active FROM ledgers WHERE id = :id", id=ids(created)["Cash"]) is True


def test_deactivate_is_blocked_by_an_opening_balance(svc_conn, client_a, client_b):
    created = client_a
    client_setup.set_opening_balance(svc_conn, created.client_id, created.financial_year_id, ids(created)["Salary"],
                                     "100000", None, actor="tester")
    with pytest.raises(ServiceError) as info:
        client_setup.deactivate_ledger(svc_conn, created.client_id, ids(created)["Salary"], actor="tester")
    assert info.value.message == "Ledger 'Salary' cannot be deactivated: it has a closing balance of 1,00,000.00 Dr."


@pytest.mark.parametrize("approve", [False, True])
def test_deactivate_is_blocked_by_draft_and_approved_vouchers(svc_conn, client_a, client_b, approve):
    created = client_a
    f = raw(svc_conn)
    voucher = f.draft(created.client_id, created.financial_year_id,
                      [(ids(created)["Rent"], "100", "0"), (ids(created)["Cash"], "0", "100")], vtype="payment")
    if approve:
        f.approve(voucher)
    with pytest.raises(ServiceError) as info:
        client_setup.deactivate_ledger(svc_conn, created.client_id, ids(created)["Rent"], actor="tester")
    assert info.value.message == "Ledger 'Rent' cannot be deactivated: it is used in 1 draft or approved voucher(s)."


def test_deactivate_is_allowed_when_a_voucher_and_its_reversal_cancel_out(svc_conn, client_a, client_b):
    created = client_a
    f, voucher = post_payment(svc_conn, created)
    f.reverse(created.client_id, created.financial_year_id, voucher,
              [(ids(created)["Rent"], "5000", "0"), (ids(created)["Cash"], "0", "5000")])
    client_setup.deactivate_ledger(svc_conn, created.client_id, ids(created)["Cash"], actor="tester")
    assert scalar(svc_conn, "SELECT is_active FROM ledgers WHERE id = :id", id=ids(created)["Cash"]) is False


def test_deactivate_twice_and_foreign_ledgers_are_refused(svc_conn, client_a, client_b):
    a, b = client_a, client_b
    client_setup.deactivate_ledger(svc_conn, a.client_id, ids(a)["Bank Charges"], actor="tester")
    with pytest.raises(ServiceError) as info:
        client_setup.deactivate_ledger(svc_conn, a.client_id, ids(a)["Bank Charges"], actor="tester")
    assert (info.value.code, info.value.message) == ("ledger_inactive", "Ledger 'Bank Charges' is already inactive.")
    with pytest.raises(ServiceError) as info:
        client_setup.deactivate_ledger(svc_conn, b.client_id, ids(a)["Rent"], actor="tester")
    assert info.value.code == "not_found"


# ====================================================================================== set_opening_balance


def set_opening(conn, created, ledger, debit=None, credit=None, **kw):
    return client_setup.set_opening_balance(conn, created.client_id, kw.pop("fy", created.financial_year_id),
                                            ids(created)[ledger], debit, credit, actor="tester", **kw)


def opening_rows(conn, created):
    return q(conn, "SELECT l.name, o.debit, o.credit FROM opening_balances o JOIN ledgers l ON l.id = o.ledger_id "
                   "WHERE o.client_id = :c ORDER BY l.name", c=created.client_id)


def test_set_opening_balance_stores_it_and_logs_it(svc_conn, client_a, client_b):
    created = client_a
    set_opening(svc_conn, created, "Cash", "50000")
    set_opening(svc_conn, created, "Ramesh Kumar Capital A/c", None, "50000.00")
    assert opening_rows(svc_conn, created) == [
        ("Cash", D("50000"), D("0")), ("Ramesh Kumar Capital A/c", D("0"), D("50000")),
    ]
    log = q(svc_conn, "SELECT action, old_data IS NULL, new_data->>'debit', new_data->>'credit' FROM audit_log "
                      "WHERE entity = 'opening_balance' ORDER BY id")
    assert log == [("set_opening_balance", True, "50000.00", "0.00"), ("set_opening_balance", True, "0.00", "50000.00")]


def test_set_opening_balance_again_replaces_the_value_and_logs_the_old_one(svc_conn, client_a, client_b):
    created = client_a
    set_opening(svc_conn, created, "Cash", "50000")
    set_opening(svc_conn, created, "Cash", None, "700.5")
    assert opening_rows(svc_conn, created) == [("Cash", D("0"), D("700.50"))]
    old, new = q(svc_conn, "SELECT old_data, new_data FROM audit_log WHERE entity = 'opening_balance' ORDER BY id DESC LIMIT 1")[0]
    assert (old["debit"], old["credit"], new["debit"], new["credit"]) == ("50000.00", "0.00", "0.00", "700.50")
    assert count(svc_conn, "opening_balances") == 1


def test_set_opening_balance_to_nothing_removes_the_row(svc_conn, client_a, client_b):
    created = client_a
    set_opening(svc_conn, created, "Cash", "50000")
    set_opening(svc_conn, created, "Cash", "0", "")
    assert opening_rows(svc_conn, created) == []


@pytest.mark.parametrize(
    ("debit", "credit", "code", "message"),
    [
        ("10", "5", "invalid_amount", "Enter either a Debit or a Credit opening balance, not both."),
        ("10.005", None, "invalid_amount", "amount 10.005 has more than 2 decimal places"),
        (None, "-1", "invalid_amount", "amount -1 is negative"),
        ("1,000", None, "invalid_amount", "not a valid number"),
        (12.5, None, "invalid_amount", "floating-point"),
    ],
)
def test_set_opening_balance_rejects_bad_amounts(svc_conn, client_a, client_b, debit, credit, code, message):
    created = client_a
    with pytest.raises(ServiceError) as info:
        set_opening(svc_conn, created, "Cash", debit, credit)
    assert info.value.code == code and message in info.value.message
    assert opening_rows(svc_conn, created) == []


def test_set_opening_balance_is_allowed_while_vouchers_are_only_drafts(svc_conn, client_a, client_b):
    created = client_a
    f = raw(svc_conn)
    f.draft(created.client_id, created.financial_year_id,
            [(ids(created)["Rent"], "100", "0"), (ids(created)["Cash"], "0", "100")], vtype="payment")
    set_opening(svc_conn, created, "Cash", "50000")
    assert opening_rows(svc_conn, created) == [("Cash", D("50000"), D("0"))]


@pytest.mark.parametrize("reverse_it", [False, True])
def test_set_opening_balance_is_blocked_once_a_voucher_is_posted_or_reversed(svc_conn, client_a, client_b, reverse_it):
    created = client_a
    f, voucher = post_payment(svc_conn, created)
    if reverse_it:
        f.reverse(created.client_id, created.financial_year_id, voucher,
                  [(ids(created)["Rent"], "5000", "0"), (ids(created)["Cash"], "0", "5000")])
    with pytest.raises(ServiceError) as info:
        set_opening(svc_conn, created, "Cash", "50000")
    assert (info.value.code, info.value.message) == (
        "opening_locked", "Opening balances cannot be changed after vouchers have been posted for this financial year.")
    assert opening_rows(svc_conn, created) == []


def test_set_opening_balance_only_locks_the_financial_year_that_has_posted_vouchers(svc_conn, client_a, client_b):
    created = client_a
    post_payment(svc_conn, created)
    second_year = raw(svc_conn).fy(created.client_id, 2027)
    client_setup.set_opening_balance(svc_conn, created.client_id, second_year, ids(created)["Cash"], "10", None, actor="tester")
    assert count(svc_conn, "opening_balances") == 1


def test_set_opening_balance_refuses_foreign_ledgers_and_years(svc_conn, client_a, client_b):
    a, b = client_a, client_b
    with pytest.raises(ServiceError) as info:
        client_setup.set_opening_balance(svc_conn, b.client_id, b.financial_year_id, ids(a)["Cash"], "1", None, actor="tester")
    assert (info.value.code, info.value.message) == ("not_found", "Ledger not found for this client.")
    with pytest.raises(ServiceError) as info:
        client_setup.set_opening_balance(svc_conn, b.client_id, a.financial_year_id, ids(b)["Cash"], "1", None, actor="tester")
    assert (info.value.code, info.value.message) == ("not_found", "Financial year not found for this client.")


# ================================================================================ opening_balance_difference


def test_opening_balance_difference_shows_what_is_missing_and_clears_when_equal(svc_conn, client_a, client_b):
    created = client_a
    check = client_setup.opening_balance_difference(svc_conn, created.client_id, created.financial_year_id)
    assert (check.total_debit, check.total_credit, check.is_balanced) == (D("0.00"), D("0.00"), True)

    set_opening(svc_conn, created, "Cash", "50000")
    set_opening(svc_conn, created, "Opening Stock", "100000")
    set_opening(svc_conn, created, "Ramesh Kumar Capital A/c", None, "140000.50")
    check = client_setup.opening_balance_difference(svc_conn, created.client_id, created.financial_year_id)
    assert (check.total_debit, check.total_credit) == (D("150000.00"), D("140000.50"))
    assert check.difference == Balance(D("9999.50"), "Dr") and check.is_balanced is False

    set_opening(svc_conn, created, "Ramesh Kumar Capital A/c", None, "150000")
    check = client_setup.opening_balance_difference(svc_conn, created.client_id, created.financial_year_id)
    assert check.is_balanced is True


def test_opening_balance_difference_counts_only_the_given_client_and_year(svc_conn, client_a, client_b):
    a, b = client_a, client_b
    set_opening(svc_conn, a, "Cash", "500")
    second_year = raw(svc_conn).fy(a.client_id, 2027)
    client_setup.set_opening_balance(svc_conn, a.client_id, second_year, ids(a)["Cash"], "70", None, actor="tester")
    one = client_setup.opening_balance_difference(svc_conn, a.client_id, a.financial_year_id)
    two = client_setup.opening_balance_difference(svc_conn, a.client_id, second_year)
    other = client_setup.opening_balance_difference(svc_conn, b.client_id, b.financial_year_id)
    assert (one.total_debit, two.total_debit, other.total_debit) == (D("500.00"), D("70.00"), D("0.00"))
