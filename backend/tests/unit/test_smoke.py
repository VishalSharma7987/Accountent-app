from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_answers_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "error"}
