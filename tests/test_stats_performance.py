from fastapi.testclient import TestClient

from app.security.auth import create_access_token
from app.services.performance_tracker import PerformanceTracker
from main import app

client = TestClient(app)


def _auth_headers():
    token = create_access_token(data={"sub": "test-user", "id": 1, "role": "user"})
    return {"Authorization": f"Bearer {token}"}


def test_stats_includes_performance_fields():
    response = client.get("/api/stats", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert "avg_detection_latency_ms" in data
    assert "detection_fps" in data
    assert data["avg_detection_latency_ms"] >= 0
    assert data["detection_fps"] >= 0


def test_performance_tracker_empty_state():
    tracker = PerformanceTracker()
    metrics = tracker.get_metrics()
    assert metrics == {"avg_detection_latency_ms": 0.0, "detection_fps": 0.0}


def test_performance_tracker_averages_latency():
    tracker = PerformanceTracker()
    tracker.record(10.0)
    tracker.record(20.0)
    tracker.record(30.0)
    metrics = tracker.get_metrics()
    assert metrics["avg_detection_latency_ms"] == 20.0
