from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app import config
from app.api import (
    audit,
    bank,
    cashbook,
    clients,
    groups,
    imports,
    ledgers,
    msme,
    periods,
    reports,
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
