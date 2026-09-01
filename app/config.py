import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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

    # Proxies reversos confiáveis (lista separada por vírgula), cujos cabeçalhos
    # X-Forwarded-For / X-Real-IP podem ser levados a sério para identificar o
    # cliente. VAZIO por padrão de propósito: confiar nesses cabeçalhos vindos de
    # qualquer origem permite furar o rate limit de login trocando o cabeçalho a
    # cada tentativa — brute force sem limite. Só preencha com o IP do seu
    # nginx/Traefik/load balancer.
    trusted_proxies: str = ""
    
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
    # Fallback de "embedding" por histograma de intensidade: não identifica
    # pessoa. Desligado por padrão para o sistema recusar o rosto em vez de
    # arriscar liberar acesso para quem não é. Ver extract_embedding().
    allow_insecure_hog_embeddings: bool = False
    # Nitidez mínima (variância do Laplaciano) para aceitar um rosto. Calibrado
    # com fotos reais - ver FaceRecognitionService.min_sharpness.
    face_min_sharpness: float = 40.0
    face_recognition_log_cooldown_seconds: int = 5
    face_recognition_confirmation_window_seconds: float = 2.5
    face_recognition_confirmation_min_frames: int = 3
    
    # Porta física (controle de acesso)
    door_min_confidence: float = 0.8
    # Exige sinal de vivacidade para acionar a porta. A checagem é modesta (barra
    # imagem estática, não ataque de apresentação elaborado - ver SECURITY.md),
    # mas antes o resultado dela era simplesmente descartado.
    door_require_liveness: bool = True

    # Logging. Os quatro campos eram configuração morta: main.py chamava
    # logging.basicConfig() com nível fixo e sem handler de arquivo, então
    # LOG_LEVEL não tinha efeito e a aplicação nunca escrevia log em disco.
    log_level: str = "INFO"
    log_file: str = "logs/face_recognition.log"
    log_max_size_mb: int = 10
    log_backup_count: int = 5

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
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings,
        dotenv_settings, file_secret_settings,
    ):
        """Ordem de precedência: o primeiro da tupla ganha.

        config.yaml entra ABAIXO do ambiente: quem publica define o segredo e os
        ajustes de produção por variável, e o YAML serve de base versionada.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v):
        if not v and os.getenv("ENVIRONMENT") == "production":
            raise ValueError("JWT_SECRET_KEY must be set in production environment")
        if v and len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return v
    
    @field_validator("admin_password")
    @classmethod
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


# ---------------------------------------------------------------------------
# config.yaml como fonte de configuração de verdade
# ---------------------------------------------------------------------------
# Antes: o YAML era carregado em `yaml_config` e nunca usado, e `settings_dict`
# saía só de `Settings` (defaults do código + .env). Editar config.yaml não tinha
# efeito nenhum — o arquivo dizia `threshold: 0.3` enquanto o valor em uso era
# 0.4. Agora ele é uma fonte real, com precedência abaixo do ambiente:
#
#     init > variável de ambiente > .env > config.yaml > default do código
#
# O YAML é aninhado e `Settings` é plano, então o mapeamento é explícito. Um
# mapeamento gerado por convenção esconderia justamente o tipo de divergência
# que causou o problema original.
YAML_TO_FIELD: dict[tuple[str, ...], str] = {
    ("app_name",): "app_name",
    ("version",): "version",
    ("server", "host"): "host",
    ("server", "port"): "port",
    ("server", "reload"): "reload",
    ("database", "path"): "database_path",
    ("face_recognition", "model"): "face_model",
    ("face_recognition", "detector"): "face_detector",
    ("face_recognition", "distance_metric"): "face_distance_metric",
    ("face_recognition", "threshold"): "face_threshold",
    ("face_recognition", "enforce_detection"): "face_enforce_detection",
    ("face_recognition", "detector_threshold"): "face_detector_threshold",
    ("face_recognition", "align"): "face_align",
    ("face_recognition", "normalization"): "face_normalization",
    ("face_recognition", "min_sharpness"): "face_min_sharpness",
    ("face_recognition", "log_cooldown_seconds"): "face_recognition_log_cooldown_seconds",
    ("face_recognition", "confirmation_window_seconds"): "face_recognition_confirmation_window_seconds",
    ("face_recognition", "confirmation_min_frames"): "face_recognition_confirmation_min_frames",
    ("face_recognition", "allow_insecure_hog_embeddings"): "allow_insecure_hog_embeddings",
    ("door", "min_confidence"): "door_min_confidence",
    ("door", "require_liveness"): "door_require_liveness",
    ("logging", "level"): "log_level",
    ("logging", "log_file"): "log_file",
    ("logging", "max_size_mb"): "log_max_size_mb",
    ("logging", "backup_count"): "log_backup_count",
    ("security", "jwt_algorithm"): "jwt_algorithm",
    ("security", "access_token_expire_minutes"): "access_token_expire_minutes",
    ("security", "rate_limit_max_requests"): "rate_limit_max_requests",
    ("security", "rate_limit_window_seconds"): "rate_limit_window_seconds",
    ("security", "auth_max_attempts"): "auth_max_attempts",
    ("security", "auth_block_duration"): "auth_block_duration",
    ("security", "trusted_proxies"): "trusted_proxies",
    ("server_camera", "enabled"): "server_camera_enabled",
    ("server_camera", "source"): "server_camera_source",
    ("server_camera", "camera_id"): "server_camera_id",
    ("server_camera", "interval_seconds"): "server_camera_interval_seconds",
}

#: Seções que o código lê direto do dicionário e que não têm campo em `Settings`
#: (ajuste fino, nada sensível). Passam do YAML para `settings_dict` como estão.
YAML_PASSTHROUGH_SECTIONS = ("anti_spoofing", "presence", "video", "export", "cameras")

#: Chaves do YAML deliberadamente ignoradas, para o aviso de chave desconhecida
#: não gritar sobre elas.
YAML_IGNORED = {("database", "type"), ("database", "echo")}


def _flatten_yaml(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Traduz o YAML aninhado para os nomes planos de `Settings`.

    Devolve também a lista de chaves não reconhecidas, para avisar em vez de
    ignorar em silêncio — foi o silêncio que deixou a divergência passar.
    """
    plano: dict[str, Any] = {}
    desconhecidas: list[str] = []

    def caminhar(prefixo: tuple[str, ...], no: Any) -> None:
        if not isinstance(no, dict):
            return
        for chave, valor in no.items():
            atual = prefixo + (chave,)
            if atual in YAML_IGNORED or atual[0] in YAML_PASSTHROUGH_SECTIONS:
                continue
            campo = YAML_TO_FIELD.get(atual)
            if campo:
                plano[campo] = valor
            elif isinstance(valor, dict):
                caminhar(atual, valor)
            elif atual == ("security", "cors_origins"):
                # Lista no YAML, string separada por vírgula em Settings.
                plano["allowed_origins"] = ",".join(str(o) for o in valor or [])
            else:
                desconhecidas.append(".".join(atual))

    caminhar((), data)
    return plano, desconhecidas


class YamlConfigSource(PydanticBaseSettingsSource):
    """Fonte de configuração lendo config.yaml, abaixo do ambiente na precedência."""

    def __init__(self, settings_cls):
        super().__init__(settings_cls)
        self._valores, self.chaves_desconhecidas = _flatten_yaml(load_yaml_config())

    def get_field_value(self, field, field_name):  # pragma: no cover - exigido pela ABC
        return self._valores.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._valores)


settings = Settings()

def get_trusted_proxies() -> set[str]:
    """Peers cujos cabeçalhos de IP encaminhado podem ser confiados."""
    raw = settings.trusted_proxies or ""
    return {p.strip() for p in raw.split(",") if p.strip()}


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
        "confirmation_min_frames": settings.face_recognition_confirmation_min_frames,
        "allow_insecure_hog_embeddings": settings.allow_insecure_hog_embeddings,
        "min_sharpness": settings.face_min_sharpness
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
    "door": {
        "min_confidence": settings.door_min_confidence,
        "require_liveness": settings.door_require_liveness
    },
    "logging": {
        "level": settings.log_level,
        "max_size_mb": settings.log_max_size_mb,
        "backup_count": settings.log_backup_count,
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

# Seções de ajuste fino que existem só no config.yaml (sem campo em `Settings`) e
# que o código lê direto deste dicionário: `presence.timeout_seconds` em
# app/database/db.py e `anti_spoofing` em app/services/face_recognition.py.
# Ficavam de fora, então essas leituras sempre caíam no default e editar o YAML
# não surtia efeito.
_yaml_bruto = load_yaml_config()
for _secao in YAML_PASSTHROUGH_SECTIONS:
    if _secao in _yaml_bruto:
        settings_dict[_secao] = _yaml_bruto[_secao]


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

    if not settings.embedding_encryption_key:
        warnings.append(
            "EMBEDDING_ENCRYPTION_KEY not set - face embeddings (biometric data) "
            "will be stored in plaintext"
        )
    elif len(settings.embedding_encryption_key) < 16:
        warnings.append("EMBEDDING_ENCRYPTION_KEY too short - should be at least 16 characters")

    if settings.environment == "production":
        if settings.reload:
            warnings.append("Server reload enabled in production")
        cors_origins = get_cors_origins()
        if any("*" in o for o in cors_origins) or len(cors_origins) == 0:
            warnings.append("CORS origins not properly restricted in production")
    
    return len(warnings) == 0, warnings
