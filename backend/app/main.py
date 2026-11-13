from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app import config
from app.api import (
    audit,
    bank,
    bills,
    cashbook,
    clients,
    groups,
    gst_invoices,
    gst_itc,
    gst_masters,
    gst_recon,
    gst_returns,
    imports,
    ledgers,
    msme,
    parties,
    periods,
    reconciliation,
    reports,
    tds_challans,
    tds_deduction,
    tds_masters,
    tds_recon,
    tds_returns,
    vouchers,
)
from app.api.errors import register_error_handlers

app = FastAPI(title="LedgerMind AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],  # includes X-User
)

# One entry per router; a later router (e.g. the Excel import) is one more entry here.
ROUTERS = [
    clients.router, groups.router, ledgers.router, vouchers.router, periods.router, reports.router, audit.router,
    imports.router,
    bank.router,
    cashbook.router,
    msme.router,
    parties.router,
    bills.router,
    reconciliation.router,
    gst_masters.router,
    gst_invoices.router,
    gst_itc.router,
    gst_recon.router,
    gst_returns.router,
    tds_masters.router,
    tds_deduction.router,
    tds_challans.router,
    tds_returns.router,
    tds_recon.router,
]
for _router in ROUTERS:
    app.include_router(_router)
register_error_handlers(app)


def _db_status() -> str:
    url = config.database_url()
    if not url:
        return "error"
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return "ok"
    except SQLAlchemyError:
        return "error"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": _db_status()}
