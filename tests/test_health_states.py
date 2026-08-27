from fastapi.testclient import TestClient

from app.api import routes as api_routes
from main import app

client = TestClient(app)


def test_health_reports_model_ready_when_initialized(monkeypatch):
    monkeypatch.setitem(api_routes.service_status, "model_ready", True)
    monkeypatch.setitem(api_routes.service_status, "model_error", None)

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["model_ready"] is True
    assert data["model_error"] is None


def test_health_degrades_when_model_not_ready(monkeypatch):
    monkeypatch.setitem(api_routes.service_status, "model_ready", False)
    monkeypatch.setitem(api_routes.service_status, "model_error", "modelo indisponível")

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["model_ready"] is False
    assert data["model_error"] == "modelo indisponível"
