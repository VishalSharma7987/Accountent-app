"""Step 1.5: concurrent posting needs real commits and separate connections (guarded test schema, cleaned around)."""

import threading

import pytest
from test_vouchers import make_world, payment

from app.db import connection, migrate
from app.services import vouchers

pytestmark = pytest.mark.integration


@pytest.fixture
def committed(test_engine, test_conn):
    """Real commits: concurrency needs separate connections. Cleans the schema before and after."""
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    yield test_engine
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def test_two_or_more_concurrent_posts_never_get_the_same_number(committed):
    engine = committed
    with engine.begin() as conn:
        w = make_world(conn)
        ids = []
        for amount in ("101", "102", "103", "104", "105", "106"):
            vid = vouchers.create_draft(conn, payment(w, amount=amount), actor="clerk").voucher_id
            vouchers.approve(conn, vid, actor="partner")
            ids.append(vid)

    numbers, failures = [], []

    def worker(voucher_id):
        try:
            with engine.begin() as conn:
                numbers.append(vouchers.post(conn, voucher_id, actor="partner"))
        except Exception as problem:  # noqa: BLE001 - collected and asserted below
            failures.append(problem)

    threads = [threading.Thread(target=worker, args=(v,)) for v in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert failures == []
    assert sorted(numbers) == [f"PAY/2026-27/{n:04d}" for n in range(1, 7)]


def test_a_rolled_back_post_does_not_use_up_a_number(committed):
    engine = committed
    with engine.begin() as conn:
        w = make_world(conn)
        first = vouchers.create_draft(conn, payment(w, amount="1"), actor="clerk").voucher_id
        second = vouchers.create_draft(conn, payment(w, amount="2"), actor="clerk").voucher_id
        for vid in (first, second):
            vouchers.approve(conn, vid, actor="partner")
    with pytest.raises(RuntimeError, match="crash"), engine.begin() as conn:
        assert vouchers.post(conn, first, actor="partner") == "PAY/2026-27/0001"
        raise RuntimeError("crash after numbering")
    with engine.begin() as conn:
        assert vouchers.post(conn, second, actor="partner") == "PAY/2026-27/0001"
