import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_endpoint_returns_200():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ok", "degraded"]
    assert "database" in data
    assert "orchestrator" in data
    assert "uptime_seconds" in data
    assert "version" in data

def test_health_orchestrator_metrics():
    response = client.get("/api/health")
    data = response.json()
    orchestrator = data["orchestrator"]
    assert "cache_size" in orchestrator
    assert "buckets_size" in orchestrator

def test_health_degraded_on_db_failure(monkeypatch):
    from app.api.routes import db_manager
    
    def mock_session_local(*args, **kwargs):
        raise Exception("Database connection failure simulator")
        
    monkeypatch.setattr(db_manager, "SessionLocal", mock_session_local)
    
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"] == "error"

