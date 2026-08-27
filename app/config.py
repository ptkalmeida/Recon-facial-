import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field, validator
from pydantic_settings import BaseSettings

# Load .env file first
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


class Settings(BaseSettings):
    """Application settings with secure defaults."""
    
    # App Info
    app_name: str = "Face Recognition Pro 3.0"
    version: str = "3.0.0"
    environment: str = Field(default="development", pattern="^(development|production|testing)$")
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = False
    
    # Security - Critical: These MUST be set via environment variables in production!
    jwt_secret_key: str = Field(default_factory=lambda: os.getenv("JWT_SECRET_KEY", ""))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    
    admin_username: str = Field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin"))
    admin_password: str = Field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    
    embedding_encryption_key: str = Field(default_factory=lambda: os.getenv("EMBEDDING_ENCRYPTION_KEY", ""))
    
    # CORS
    allowed_origins: str = Field(default="http://localhost:8001,http://127.0.0.1:8001")
    
    # Rate Limiting
    rate_limit_max_requests: int = 100
    rate_limit_window_seconds: int = 60
    auth_max_attempts: int = 5
    auth_block_duration: int = 900
    
    # Database
    database_path: str = "data/face_recognition.db"
    
    # Face Recognition
    face_model: str = "Facenet512"
    face_detector: str = "retinaface"
    face_distance_metric: str = "cosine"
    face_threshold: float = 0.4
    face_enforce_detection: bool = True
    face_detector_threshold: float = 0.7
    face_align: bool = True
    face_normalization: str = "base"
    face_recognition_log_cooldown_seconds: int = 5
    face_recognition_confirmation_window_seconds: float = 2.5
    face_recognition_confirmation_min_frames: int = 3
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/face_recognition.log"

    # Email alerts (unknown face detected)
    alerts_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = Field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = ""
    alert_email_to: str = ""
    alert_cooldown_seconds: int = 600

    # Optional server-side camera capture (local webcam index or RTSP/file URL)
    server_camera_enabled: bool = False
    server_camera_source: str = ""
    server_camera_id: str = "server-cam"
    server_camera_interval_seconds: float = 1.0
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"
        case_sensitive = False
    
    @validator("jwt_secret_key")
    def validate_jwt_secret(cls, v):
        if not v and os.getenv("ENVIRONMENT") == "production":
            raise ValueError("JWT_SECRET_KEY must be set in production environment")
        if v and len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return v
    
    @validator("admin_password")
    def validate_admin_password(cls, v):
        if not v:
            return v
        if len(v) < 8:
            raise ValueError("Admin password must be at least 8 characters long")
        return v


def load_yaml_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Load YAML configuration (non-sensitive settings only)."""
    config_file = Path(__file__).parent.parent / config_path
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# Load YAML config (non-sensitive settings)
yaml_config = load_yaml_config()

# Merge with environment variables (env vars take precedence)
settings = Settings()

def get_cors_origins() -> list[str]:
    """Parse CORS origins from comma-separated string."""
    origins = settings.allowed_origins
    if not origins:
        return ["http://localhost:8001", "http://127.0.0.1:8001"]
    return [o.strip() for o in origins.split(",") if o.strip()]


# Export config dict for backward compatibility
settings_dict = {
    "app_name": settings.app_name,
    "version": settings.version,
    "environment": settings.environment,
    "server": {
        "host": settings.host,
        "port": settings.port,
        "reload": settings.reload
    },
    "database": {
        "path": settings.database_path
    },
    "face_recognition": {
        "model": settings.face_model,
        "detector": settings.face_detector,
        "distance_metric": settings.face_distance_metric,
        "threshold": settings.face_threshold,
        "enforce_detection": settings.face_enforce_detection,
        "detector_threshold": settings.face_detector_threshold,
        "align": settings.face_align,
        "normalization": settings.face_normalization,
        "log_cooldown_seconds": settings.face_recognition_log_cooldown_seconds,
        "confirmation_window_seconds": settings.face_recognition_confirmation_window_seconds,
        "confirmation_min_frames": settings.face_recognition_confirmation_min_frames
    },
    "security": {
        "jwt_algorithm": settings.jwt_algorithm,
        "access_token_expire_minutes": settings.access_token_expire_minutes,
        "rate_limit_max_requests": settings.rate_limit_max_requests,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
        "auth_max_attempts": settings.auth_max_attempts,
        "auth_block_duration": settings.auth_block_duration,
        "cors_origins": get_cors_origins()
    },
    "logging": {
        "level": settings.log_level,
        "log_file": settings.log_file
    },
    "alerts": {
        "enabled": settings.alerts_enabled,
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "smtp_user": settings.smtp_user,
        "smtp_password": settings.smtp_password,
        "smtp_from": settings.smtp_from,
        "alert_email_to": settings.alert_email_to,
        "cooldown_seconds": settings.alert_cooldown_seconds
    },
    "server_camera": {
        "enabled": settings.server_camera_enabled,
        "source": settings.server_camera_source,
        "camera_id": settings.server_camera_id,
        "interval_seconds": settings.server_camera_interval_seconds
    }
}


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Backward compatibility function."""
    return settings_dict


# Validation helper
def validate_security_settings() -> tuple[bool, list[str]]:
    """Validate that critical security settings are configured."""
    warnings = []
    
    if not settings.jwt_secret_key:
        warnings.append("JWT_SECRET_KEY not set - using default (INSECURE for production)")
    elif len(settings.jwt_secret_key) < 32:
        warnings.append("JWT_SECRET_KEY too short - should be at least 32 characters")
    
    if not settings.admin_password:
        warnings.append("ADMIN_PASSWORD not set")
    else:
        # Deferred import: app.security.auth imports `settings` from this module,
        # so importing it at module load time here would create a circular import.
        from app.security.auth import validate_password_strength
        is_strong, error = validate_password_strength(settings.admin_password)
        if not is_strong:
            warnings.append(f"ADMIN_PASSWORD does not meet strength requirements: {error}")

    if settings.environment == "production":
        if settings.reload:
            warnings.append("Server reload enabled in production")
        cors_origins = get_cors_origins()
        if any("*" in o for o in cors_origins) or len(cors_origins) == 0:
            warnings.append("CORS origins not properly restricted in production")
    
    return len(warnings) == 0, warnings
