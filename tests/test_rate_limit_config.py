from app.config import settings
from app.security.rate_limiter import auth_rate_limiter


def test_auth_rate_limiter_honors_env_settings():
    assert auth_rate_limiter.max_requests == settings.auth_max_attempts
    assert auth_rate_limiter.block_duration == settings.auth_block_duration
