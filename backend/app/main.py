from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app import config

app = FastAPI(title="LedgerMind AI")


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
