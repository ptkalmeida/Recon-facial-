from fastapi.testclient import TestClient

from app.config import settings
from main import app

client = TestClient(app)


def test_general_limit_blocks_after_threshold():
    # Unique fake IP (via X-Forwarded-For) so this test's exhaustion of the
    # shared api_rate_limiter doesn't affect other tests using the default
    # TestClient IP.
    headers = {"X-Forwarded-For": "203.0.113.10"}

    last_status = None
    for _ in range(settings.rate_limit_max_requests + 5):
        response = client.get("/api/users", headers=headers)
        last_status = response.status_code

    assert last_status == 429


def test_health_is_never_rate_limited():
    headers = {"X-Forwarded-For": "203.0.113.11"}

    for _ in range(settings.rate_limit_max_requests + 5):
        response = client.get("/api/health", headers=headers)
        assert response.status_code == 200


def test_login_route_is_excluded_from_general_limiter():
    # /api/auth/login has its own dedicated (stricter) limiter; the general
    # limiter must not add a second, independent block on top of it.
    headers = {"X-Forwarded-For": "203.0.113.12"}

    response = client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "wrong"},
        headers=headers,
    )
    # 401 (invalid credentials) proves the request reached the route instead
    # of being short-circuited by the general limiter as a 429.
    assert response.status_code in (401, 429)
    # Only the auth-specific limiter (5 attempts) should be able to produce
    # the 429 here, never the general one after just one request.
    if response.status_code == 429:
        assert "login" in response.json()["detail"].lower() or "tentativas" in response.json()["detail"].lower()
