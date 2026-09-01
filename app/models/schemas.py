import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# Nome de pessoa: letras (com acento), espaço, hífen, apóstrofo e ponto.
# Rejeita `<`, `>`, `&`, `"`, `=` e caracteres de controle - o nome é renderizado
# no dashboard/monitor e exportado para planilha, então metacaracteres de HTML e
# de fórmula não têm por que ser aceitos na entrada (o escape na saída continua
# valendo; esta é a segunda camada).
# Espaço é literal (não `\s`): `\s` casaria \n/\r/\t, que não têm lugar num nome.
PERSON_NAME_PATTERN = re.compile(r"^[\w '\.\-]+$", re.UNICODE)


def validate_person_name(value: str) -> str:
    """Normaliza e valida um nome de pessoa. Levanta ValueError se inválido."""
    name = (value or "").strip()
    if not name:
        raise ValueError("Nome não pode ser vazio")
    if len(name) > 255:
        raise ValueError("Nome não pode ter mais de 255 caracteres")
    if not PERSON_NAME_PATTERN.match(name):
        raise ValueError(
            "Nome contém caracteres não permitidos "
            "(use apenas letras, números, espaço, hífen, apóstrofo e ponto)"
        )
    return name


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: str = Field(default="user")


class UserCreate(UserBase):
    # A validação vive só nos schemas de entrada: `UserResponse` também herda de
    # `UserBase` e não pode falhar ao serializar um nome legado gravado antes
    # desta regra existir.
    @field_validator("name")
    @classmethod
    def _check_name(cls, v):
        return validate_person_name(v)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v):
        return v if v is None else validate_person_name(v)


class UserResponse(UserBase):
    # `str`, não `EmailStr`: validar e-mail na SAÍDA quebra o endpoint inteiro se
    # o banco tiver uma linha com e-mail malformado (possível em cadastros feitos
    # antes da validação de entrada existir). Nesse caso `GET /api/users` devolvia
    # 500 e a aba Usuários ficava vazia. A validação de formato continua nos
    # schemas de entrada, onde é útil.
    email: Optional[str] = None
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EmbeddingData(BaseModel):
    embedding: List[float]
    model: str = "Facenet512"


class RegisterUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    images: List[str] = Field(..., min_length=1)
    role: str = "user"


class RecognitionResult(BaseModel):
    user_id: Optional[int] = None
    name: str
    confidence: float
    is_known: bool
    is_live: bool = True
    anti_spoofing_details: Optional[Dict[str, Any]] = None


class AccessLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    status: str
    camera_source: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PresenceResponse(BaseModel):
    user: Dict[str, Any]
    status: str
    check_in: Optional[datetime] = None


class PresenceHistoryResponse(BaseModel):
    user_id: int
    user_name: str
    date: str
    records: List[Dict[str, Any]]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class SystemStats(BaseModel):
    total_users: int
    active_users: int
    present_today: int
    access_today: int
    unknown_detections_today: int
    avg_detection_latency_ms: float = 0.0
    detection_fps: float = 0.0


class ExportRequest(BaseModel):
    start_date: str
    end_date: str
    format: str = Field(default="xlsx")
    export_type: str = Field(default="access_logs")
    user_id: Optional[int] = None


class CameraInfo(BaseModel):
    id: Optional[int] = None
    name: str
    source: str
    source_type: str = "webcam"
    is_active: bool = True
    location: Optional[str] = None


class FrameProcessRequest(BaseModel):
    frame_data: str
    camera_id: Optional[int] = None
    check_liveness: bool = True