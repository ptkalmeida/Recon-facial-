from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: str = Field(default="user")


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EmbeddingData(BaseModel):
    embedding: List[float]
    model: str = "Facenet512"


class RegisterUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    images: List[str] = Field(..., min_items=1)
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

    class Config:
        from_attributes = True


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