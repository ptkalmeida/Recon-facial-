import json

import pytest

from app.config import settings, validate_security_settings
from app.security import auth as auth_module


def test_validate_security_settings_warns_on_weak_admin_password(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "weak")
    is_secure, warnings = validate_security_settings()

    assert is_secure is False
    assert any("ADMIN_PASSWORD does not meet strength requirements" in w for w in warnings)


def test_validate_security_settings_ok_with_strong_admin_password(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "Str0ng!Passw0rd")
    _, warnings = validate_security_settings()

    assert not any("ADMIN_PASSWORD does not meet strength" in w for w in warnings)


def test_ensure_auth_file_refuses_weak_password_in_production(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "weak")
    monkeypatch.setattr(settings, "environment", "production")

    manager = auth_module.SimpleAuthManager.__new__(auth_module.SimpleAuthManager)
    manager.auth_file = tmp_path / "admin_auth.json"
    manager._lock = __import__("threading").RLock()
    manager._initialized = False
    manager._RATE_KEY = "test_admin_auth_attempts"

    with pytest.raises(RuntimeError, match="does not meet strength requirements"):
        manager._ensure_auth_file()


def test_ensure_auth_file_allows_weak_password_outside_production(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "weak")
    monkeypatch.setattr(settings, "environment", "development")

    manager = auth_module.SimpleAuthManager.__new__(auth_module.SimpleAuthManager)
    manager.auth_file = tmp_path / "admin_auth.json"
    manager._lock = __import__("threading").RLock()
    manager._initialized = False
    manager._RATE_KEY = "test_admin_auth_attempts"

    manager._ensure_auth_file()

    assert manager.auth_file.exists()
    data = json.loads(manager.auth_file.read_text())
    assert data["username"] == auth_module.ADMIN_USERNAME
