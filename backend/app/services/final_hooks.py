"""Hook points between the voucher / setup services and the Phase 6 year-end close (docs/PHASE6_PLAN.md, package F).

`services/vouchers.py` and `services/client_setup.py` call these functions; they carry no accounting knowledge of their own.
  year_is_closed       - True when the financial year has a 'closed' year_end_closes row (inputs of that year are frozen)
  guard_reverse        - refuse a DIRECT reversal of a year-end closing voucher (F-64): closing entries are undone only by the
                         year-end reopen, which reverses all three in the right order and records why
The bodies below are final (two small reads, no writes); package F wires the calls into vouchers.reverse and the opening-balance
service. Until then nothing calls them, so Phase 1-5 behaviour is unchanged.
"""

from typing import Any

from sqlalchemy import Connection, text

from app.services.errors import ServiceError


def year_is_closed(conn: Connection, client_id: Any, financial_year_id: Any) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM year_end_closes WHERE client_id = :c AND financial_year_id = :fy AND status = 'closed'"),
        {"c": client_id, "fy": financial_year_id},
    ).first()
    return row is not None


def guard_reverse(conn: Connection, client_id: Any, voucher_id: Any) -> None:
    """Raise ServiceError('year_end_voucher') if the voucher is a closing voucher of a year that is still closed."""
    row = conn.execute(
        text(
            "SELECT 1 FROM year_end_close_vouchers cv JOIN year_end_closes c ON c.id = cv.close_id "
            "WHERE cv.client_id = :c AND cv.voucher_id = :v AND cv.kind = 'closing' AND c.status = 'closed'"
        ),
        {"c": client_id, "v": voucher_id},
    ).first()
    if row is not None:
        raise ServiceError(
            "year_end_voucher",
            "This voucher is a year-end closing entry (F-64). It cannot be reversed on its own: reopen the financial year, "
            "which reverses all closing entries together and records the reason.",
        )
