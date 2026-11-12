"""FastAPI dependencies: the engine, one transaction per request, and the actor (X-User header).

Tests override `get_conn` (with a rolled-back connection) or `get_engine`.
"""

import uuid
from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy import Connection, Engine

from app import config
from app.db.connection import DEV_SCHEMA
from app.db.engine import make_engine
from app.services.errors import ServiceError, require_actor


def get_engine(request: Request) -> Engine:
    """The application engine (schema `public`), built on first use so /health works without a database."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        url = config.database_url()
        if not url:
            raise ServiceError("database_unavailable", "DATABASE_URL is not set.")
        engine = make_engine(url, DEV_SCHEMA)
        request.app.state.engine = engine
    return engine


def _transaction(engine: Engine = Depends(get_engine)) -> Iterator[Connection]:
    """One database transaction per request: commit when the handler returns, roll back when it raises."""
    conn = engine.connect()
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def get_conn(conn: Connection = Depends(_transaction, scope="function")) -> Connection:
    """The request's Connection. `scope="function"` on the inner dependency makes the commit happen right after the
    handler and BEFORE the response is sent, so a client never sees "200" for work that is not committed yet."""
    return conn


def get_actor(x_user: str | None = Header(default=None, alias="X-User")) -> str:
    """Who is making the change (no login in Phase 1). Missing or blank -> 400 invalid_actor."""
    return require_actor(x_user)


def parse_id(value: str, what: str) -> uuid.UUID:
    """A path id as a UUID; anything that is not a UUID cannot exist, so it is a plain 'not found'."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ServiceError("not_found", f"{what} not found.") from None
