"""SQLAlchemy engine factory. Every pooled connection is pinned to one schema and checked (schema guard).

The application engine uses the dev schema `public`; tests use `ledgermind_test`. Services receive a Connection
from the caller, who owns the transaction (see app/services).
"""

from sqlalchemy import Engine, create_engine, event

from app.db.connection import require_schema


def make_engine(url: str, schema: str) -> Engine:
    """An engine whose connections all have search_path = `schema` (verified with current_schema())."""
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},  # also works through Supabase's pooler
    )

    @event.listens_for(engine, "connect")
    def _pin_schema(dbapi_connection, _record):
        dbapi_connection.execute("SELECT set_config('search_path', %s, false)", (schema,))
        dbapi_connection.commit()
        current = dbapi_connection.execute("SELECT current_schema()").fetchone()[0]
        dbapi_connection.commit()
        require_schema(current, schema)

    return engine
