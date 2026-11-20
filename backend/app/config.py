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


# ---- Phase 7 (documents and AI). None of these has a silent default that could expose data or spend money. ----


def document_store_dir() -> Path | None:
    """Folder for uploaded files (DOCUMENT_STORE_DIR). Must be an absolute path OUTSIDE the repository and outside any web root;
    None = uploads are refused with a clear message. Files are only ever served through the API, never by a public URL."""
    value = os.environ.get("DOCUMENT_STORE_DIR", "").strip()
    return Path(value) if value else None


def max_upload_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))


def openrouter_api_key() -> str | None:
    """OPENROUTER_API_KEY. Never logged, never stored, never put in an error message."""
    return os.environ.get("OPENROUTER_API_KEY", "").strip() or None


def llm_model() -> str | None:
    """LLM_MODEL (an OpenRouter model name). None = no model configured, so no call can be made."""
    return os.environ.get("LLM_MODEL", "").strip() or None


def ai_min_confidence() -> str:
    """Fields read with a confidence below this are flagged (D-05). Text, parsed to Decimal by the engine."""
    return os.environ.get("AI_MIN_CONFIDENCE", "0.85").strip()
