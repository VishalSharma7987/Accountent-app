"""Small helpers that build rows for schema-guard tests. They only run on the guarded test connection.

Tests run inside one open transaction that the fixture rolls back; deferred constraints (the posting check)
are fired on demand with check_deferred().
"""

import uuid
from contextlib import contextmanager
from datetime import date

import psycopg
import pytest


@contextmanager
def rejected(conn, *, message: str | None = None, constraint: str | None = None):
    """The body must make the database raise. The failed statement is rolled back (savepoint)."""
    with pytest.raises(psycopg.Error) as info, conn.transaction():
        yield
    diag = info.value.diag
    if message is not None:
        assert message in (diag.message_primary or ""), diag.message_primary
    if constraint is not None:
        assert diag.constraint_name == constraint, (diag.constraint_name, diag.message_primary)


def check_deferred(conn) -> None:
    """Fire the deferred posting check now (normally it runs at COMMIT)."""
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


def swapped(lines):
    """The same lines with debit and credit exchanged (what a reversal voucher carries)."""
    return [(ledger_id, credit, debit) for ledger_id, debit, credit in lines]


class Factory:
    def __init__(self, conn):
        self.conn = conn
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    # Ids are generated here (not RETURNING id) so several statements can go to the database in ONE round
    # trip with conn.pipeline(): the tests' time is dominated by network latency, not by the database.

    # ---- masters -------------------------------------------------------------------------------
    def client(self, name: str | None = None) -> uuid.UUID:
        client_id = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO clients (id, name, entity_type, business_type, gst_type) "
            "VALUES (%s, %s, 'proprietorship', 'trading', 'regular')",
            (client_id, name or f"Client {self._next()}"),
        )
        return client_id

    def fy(self, client_id, year: int = 2026) -> uuid.UUID:
        fy_id = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (%s, %s, %s, %s)",
            (fy_id, client_id, date(year, 4, 1), date(year + 1, 3, 31)),
        )
        return fy_id

    def group(self, code: str) -> str:
        return self.conn.execute(
            "SELECT id FROM account_groups WHERE code = %s AND client_id IS NULL", (code,)
        ).fetchone()[0]

    def ledger(self, client_id, name: str, group_code: str = "indirect_expenses") -> uuid.UUID:
        ledger_id = uuid.uuid4()
        self.conn.execute(
            "INSERT INTO ledgers (id, client_id, group_id, name) VALUES (%s, %s, "
            "(SELECT id FROM account_groups WHERE code = %s AND client_id IS NULL), %s)",
            (ledger_id, client_id, group_code, name),
        )
        return ledger_id

    def period(self, client_id, fy_id, start: str, end: str) -> str:
        return self.conn.execute(
            "INSERT INTO periods (client_id, financial_year_id, period_start, period_end) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (client_id, fy_id, start, end),
        ).fetchone()[0]

    # ---- vouchers ------------------------------------------------------------------------------
    def draft(
        self, client_id, fy_id, lines, *, vtype="journal", on="2026-04-05", narration="test", reverses=None
    ) -> str:
        """A draft voucher; lines = [(ledger_id, debit, credit), ...] as strings like '100.00'."""
        vid = uuid.uuid4()
        with self.conn.pipeline():  # the voucher and all its lines in one round trip
            self.conn.execute(
                "INSERT INTO vouchers (id, client_id, financial_year_id, voucher_type, voucher_date, narration, "
                "created_by, reverses_voucher_id) VALUES (%s, %s, %s, %s, %s, %s, 'tester', %s)",
                (vid, client_id, fy_id, vtype, on, narration, reverses),
            )
            for number, (ledger_id, debit, credit) in enumerate(lines, start=1):
                self.conn.execute(
                    "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit, credit) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (client_id, vid, number, ledger_id, debit, credit),
                )
        return vid

    def approve(self, voucher_id) -> None:
        self.conn.execute(
            "UPDATE vouchers SET status = 'approved', approved_by = 'tester', approved_at = now() WHERE id = %s",
            (voucher_id,),
        )

    def post(self, voucher_id, number: str | None = None) -> None:
        self.conn.execute(
            "UPDATE vouchers SET status = 'posted', voucher_number = %s, posted_by = 'tester', posted_at = now() "
            "WHERE id = %s",
            (number or f"JRN/2026-27/{self._next():04d}", voucher_id),
        )

    def balanced_lines(self, client_id) -> list[tuple]:
        """Two fresh ledgers and a balanced pair of lines: Dr 100.00 / Cr 100.00."""
        with self.conn.pipeline():
            a = self.ledger(client_id, f"Expense {self._next()}")
            b = self.ledger(client_id, f"Cash {self._next()}", "cash_in_hand")
        return [(a, "100.00", "0.00"), (b, "0.00", "100.00")]

    def posted(self, client_id, fy_id) -> str:
        """A fully posted, balanced voucher."""
        vid = self.draft(client_id, fy_id, self.balanced_lines(client_id))
        self.approve(vid)
        self.post(vid)
        check_deferred(self.conn)
        return vid

    def reverse(self, client_id, fy_id, original_id, lines) -> str:
        """Post a reversal of `original_id` (lines swapped) and mark the original reversed. Returns the reversal id."""
        reversal_id = self.draft(client_id, fy_id, swapped(lines), narration="Reversal", reverses=original_id)
        self.approve(reversal_id)
        self.post(reversal_id)
        check_deferred(self.conn)
        self.conn.execute(
            "UPDATE vouchers SET status = 'reversed', reversed_by_voucher_id = %s WHERE id = %s",
            (reversal_id, original_id),
        )
        return reversal_id

    def status(self, voucher_id) -> str:
        return self.conn.execute("SELECT status FROM vouchers WHERE id = %s", (voucher_id,)).fetchone()[0]

    def setup(self):
        """(client_id, fy_id) for a fresh client with FY 2026-27 (one round trip)."""
        with self.conn.pipeline():
            client_id = self.client()
            fy_id = self.fy(client_id)
        return client_id, fy_id
