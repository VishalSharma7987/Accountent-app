"""Settings read from the environment / the repo-root .env file (never committed)."""

import os
from pathlib import Path

from dotenv import load_dotenv

# <repo>/.env  (this file is <repo>/backend/app/config.py)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _sqlalchemy_url(url: str | None) -> str | None:
    """Supabase gives 'postgresql://...'; SQLAlchemy needs the psycopg 3 driver name."""
    if not url:
        return None
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def database_url() -> str | None:
    return _sqlalchemy_url(os.environ.get("DATABASE_URL"))


def cors_origins() -> list[str]:
    """Browser origins allowed to call the API: local dev + the deployed Netlify frontend.
    Extra origins can be added with CORS_ORIGINS (comma-separated)."""
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://amind-ai.netlify.app",
    ]
    extra = os.environ.get("CORS_ORIGINS", "")
    origins += [o.strip().rstrip("/") for o in extra.split(",") if o.strip()]
    return origins


def test_database_url() -> str | None:
    return _sqlalchemy_url(os.environ.get("TEST_DATABASE_URL"))
