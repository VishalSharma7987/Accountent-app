"""Raw-SQL builders for reconciliation tests (they do not depend on the statement importer)."""

import uuid
from datetime import date

from sqlalchemy import text


def add_statement(conn, client_id, bank_ledger_id, opening: str, closing: str, lines, *,
                  period=(date(2026, 4, 1), date(2026, 4, 30))):
    """lines = [(txn_date, description, reference, debit, credit)] with '0.00' on the unused side.
    Returns (statement_id, [line_id, ...]) in the order given."""
    statement_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO bank_statements (id, client_id, bank_ledger_id, file_name, file_sha256, period_from, period_to, "
            "opening_balance, closing_balance, imported_by) "
            "VALUES (:id, :c, :b, 'test.xlsx', :sha, :f, :t, :o, :cl, 'tester')"
        ),
        {"id": statement_id, "c": client_id, "b": bank_ledger_id, "sha": uuid.uuid4().hex, "f": period[0],
         "t": period[1], "o": opening, "cl": closing},
    )
    ids = [uuid.uuid4() for _ in lines]
    conn.execute(
        text(
            "INSERT INTO bank_statement_lines (id, client_id, statement_id, line_no, txn_date, description, reference, "
            "debit, credit) VALUES (:id, :c, :s, :n, :d, :desc, :ref, :dr, :cr)"
        ),
        [
            {"id": ids[n], "c": client_id, "s": statement_id, "n": n + 1, "d": d, "desc": desc, "ref": ref,
             "dr": dr, "cr": cr}
            for n, (d, desc, ref, dr, cr) in enumerate(lines)
        ],
    )
    return statement_id, ids
