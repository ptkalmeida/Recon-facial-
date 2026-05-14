import io
import numpy as np
import cv2
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse

from app.database.db import db_manager
from app.models.schemas import (
    UserCreate, UserResponse, UserUpdate,
    SystemStats, LoginRequest, LoginResponse, ExportRequest
)
from app.services.face_recognition import FaceRecognitionService
from app.security.auth import (
    auth_manager, create_access_token, decode_token,
    authenticate_user
)
from app.security.rate_limiter import (
    auth_rate_limiter, recognition_rate_limiter, 
    get_client_ip, create_rate_limit_key
)
from app.utils.export import generate_excel_report, generate_pdf_report
from app.services.hardware import door_manager
from app.config import settings_dict
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()

face_service = FaceRecognitionService(settings_dict)
last_recognition_log: dict[int, datetime] = {}
RECOGNITION_LOG_COOLDOWN_SECONDS = settings_dict.get("face_recognition", {}).get("log_cooldown_seconds", 5)
multi_frame_confirmation: dict[int, dict] = {}
CONFIRMATION_WINDOW_SECONDS = settings_dict.get("face_recognition", {}).get("confirmation_window_seconds", 2.5)
CONFIRMATION_MIN_FRAMES = settings_dict.get("face_recognition", {}).get("confirmation_min_frames", 3)


def cleanup_internal_states():
    """Clean up expired entries from internal tracking dictionaries to prevent memory leaks."""
    now = datetime.now()
    
    # 1. Cleanup last_recognition_log
    # Remove entries older than 1 hour (much longer than cooldown to be safe)
    expired_cooldown = now - timedelta(hours=1)
    keys_to_remove = [k for k, v in last_recognition_log.items() if v < expired_cooldown]
    for k in keys_to_remove:
        del last_recognition_log[k]
        
    # 2. Cleanup multi_frame_confirmation
    # Remove entries older than 2x confirmation window
    keys_to_remove = []
    for user_id, data in multi_frame_confirmation.items():
        if "last_seen" in data:
            if (now - data["last_seen"]).total_seconds() > (CONFIRMATION_WINDOW_SECONDS * 2):
                keys_to_remove.append(user_id)
    for k in keys_to_remove:
        del multi_frame_confirmation[k]
        
    if keys_to_remove:
        logger.debug(f"Cleaned up {len(keys_to_remove)} expired confirmation states")



def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invÃ¡lido ou expirado"
        )
    
    return payload


def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores"
        )
    return current_user


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, request_obj: Request):
    """Login with rate limiting protection."""
    # Check rate limit
    client_ip = get_client_ip(request_obj)
    rate_key = create_rate_limit_key("login", client_ip)
    allowed, metadata = auth_rate_limiter.is_allowed(rate_key)
    
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Muitas tentativas de login. Tente novamente em {metadata['retry_after']} segundos."
        )
    
    user = authenticate_user(request.username, request.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais invÃ¡lidas"
        )
    
    access_token = create_access_token(
        data={"sub": user["username"], "id": user["id"], "role": user["role"]}
    )
    
    return LoginResponse(
        access_token=access_token,
        user=UserResponse(
            id=user["id"],
            name=user["name"],
            role=user["role"],
            is_active=True
        )
    )


@router.post("/auth/change-password")
async def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Change admin password with strength validation."""
    if not auth_manager.verify_password(old_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha atual incorreta"
        )
    
    success, error = auth_manager.change_password(new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Erro ao alterar senha"
        )
    
    return {"message": "Senha alterada com sucesso"}


@router.get("/users", response_model=List[UserResponse])
async def get_users(
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    users = db_manager.get_all_users(active_only=active_only)
    return [UserResponse(**user.to_dict()) for user in users]


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: dict = Depends(require_admin)
):
    existing = db_manager.get_user_by_name(user_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UsuÃ¡rio jÃ¡ existe"
        )
    
    user = db_manager.create_user(
        name=user_data.name,
        email=user_data.email,
        role=user_data.role
    )
    
    db_manager.log_access(
        user_id=user.id,
        action="user_created",
        status="success",
        ip_address="system"
    )
    
    return UserResponse(**user.to_dict())


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    user = db_manager.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="UsuÃ¡rio nÃ£o encontrado"
        )
    return UserResponse(**user.to_dict())


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: dict = Depends(require_admin)
):
    user = db_manager.update_user(user_id, **user_data.dict(exclude_unset=True))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="UsuÃ¡rio nÃ£o encontrado"
        )
    return UserResponse(**user.to_dict())


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(require_admin)
):
    if not db_manager.delete_user(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="UsuÃ¡rio nÃ£o encontrado"
        )
    return {"message": "UsuÃ¡rio deletado com sucesso"}


@router.post("/users_register")
async def register_user_with_face_alias(
    name: str = Form(...),
    email: Optional[str] = Form(None),
    images: List[UploadFile] = File(...),
    current_user: dict = Depends(require_admin)
):
    return await register_user_with_face(name, email, images, current_user)


async def register_user_with_face(
    name: str = Form(...),
    email: Optional[str] = Form(None),
    images: List[UploadFile] = File(...),
    current_user: dict = Depends(require_admin)
):
    user = db_manager.get_user_by_name(name)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UsuÃ¡rio jÃ¡ existe"
        )
    
    user = db_manager.create_user(name=name, email=email, role="user")
    
    embeddings = []
    for img_file in images:
        contents = await img_file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            continue
            
        detections = face_service.detect_faces(img)
        if not detections:
            continue
            
        embedding = face_service.extract_embedding(img, detections[0])
        if embedding is not None:
            embeddings.append(embedding.tolist())
    
    if not embeddings:
        db_manager.delete_user(user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum rosto vÃ¡lido encontrado nas imagens"
        )
    
    avg_embedding = np.mean(embeddings, axis=0).tolist()
    calibrated_threshold = face_service.calibrate_threshold([np.array(e, dtype=np.float32) for e in embeddings])
    
    db_manager.add_embedding(
        user_id=user.id,
        embedding_data=avg_embedding,
        model_used=settings_dict.get("face_recognition", {}).get("model", "Facenet512"),
        is_primary=True
    )
    
    face_service.load_known_faces(db_manager.get_all_embeddings_data())
    
    db_manager.log_access(
        user_id=user.id,
        action="register",
        status="success",
        ip_address="system"
    )
    
    response = {
        "message": "UsuÃ¡rio registrado com sucesso",
        "user": user.to_dict()
    }
    if calibrated_threshold is not None:
        response["calibrated_threshold"] = calibrated_threshold
    return response


@router.get("/presence/current")
async def get_current_presence(current_user: dict = Depends(get_current_user)):
    return db_manager.get_current_presence()


@router.get("/presence/history")
async def get_presence_history(
    user_id: Optional[int] = None,
    date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    records = db_manager.get_presence_records(user_id=user_id, date=date)
    return [r.to_dict() for r in records]


@router.get("/access-logs")
async def get_access_logs(
    user_id: Optional[int] = None,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    logs = db_manager.get_access_logs(user_id=user_id, limit=limit)
    return [log.to_dict() for log in logs]


@router.post("/recognition/detect")
async def detect_faces(
    request: Request,
    image: UploadFile = File(...),
    camera_id: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Detect and recognize faces with rate limiting."""
    # Check rate limit
    client_ip = get_client_ip(request)
    user_id = current_user.get("id")
    rate_key = create_rate_limit_key("recognition", client_ip, str(user_id))
    allowed, metadata = recognition_rate_limiter.is_allowed(rate_key)
    
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas requisiÃ§Ãµes de reconhecimento. Tente novamente mais tarde."
        )
    
    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Imagem invÃ¡lida"
        )
    
    results = face_service.process_frame(frame, camera_id or "webcam")
    
    for detection in results.get("detections", []):
        if detection.get("user_id"):
            detected_user_id = detection["user_id"]
            now = datetime.now()
            bucket = multi_frame_confirmation.get(detected_user_id)
            if bucket is None or (now - bucket["first_seen"]).total_seconds() > CONFIRMATION_WINDOW_SECONDS:
                bucket = {"first_seen": now, "frames": 0}
            bucket["frames"] += 1
            multi_frame_confirmation[detected_user_id] = bucket

            if bucket["frames"] < CONFIRMATION_MIN_FRAMES:
                continue

            should_log = True
            last_log_time = last_recognition_log.get(detected_user_id)
            if last_log_time and (now - last_log_time).total_seconds() < RECOGNITION_LOG_COOLDOWN_SECONDS:
                should_log = False

            if should_log:
                db_manager.log_access(
                    user_id=detected_user_id,
                    action="recognition",
                    status="success",
                    camera_source=camera_id,
                    confidence=detection.get("match_confidence")
                )
                last_recognition_log[detected_user_id] = now
            
            current_presence = db_manager.get_current_presence()
            user_present = any(
                p.get("user", {}).get("id") == detection["user_id"] and p.get("status") == "presente"
                for p in current_presence
            )
            
            if not user_present:
                db_manager.log_presence(
                    user_id=detection["user_id"],
                    status="entrada",
                    camera_source=camera_id
                )
            
            # --- INTEGRAÃ‡ÃƒO COM A PORTA ---
            # Abre a porta se a confianÃ§a for maior que o definido (ex: 80%)
            if detection.get("match_confidence", 0) > 0.8:
                logger.info(f"UsuÃ¡rio {detection['user_name']} reconhecido. Abrindo porta...")
                door_manager.open_door(duration=5)
            # ------------------------------
        else:
            db_manager.log_access(
                user_id=None,
                action="unknown_detected",
                status="unknown",
                camera_source=camera_id,
                confidence=detection.get("match_confidence")
            )
    
    return results


@router.get("/stats")
async def get_system_stats(current_user: dict = Depends(get_current_user)):
    stats = db_manager.get_dashboard_stats()
    
    return SystemStats(
        total_users=stats["total_users"],
        active_users=stats["active_users"],
        present_today=stats["present_today"],
        access_today=stats["access_today"],
        unknown_detections_today=stats["unknown_today"]
    )



@router.post("/export")
async def export_data(
    request: ExportRequest,
    current_user: dict = Depends(get_current_user)
):
    start = datetime.strptime(request.start_date, "%Y-%m-%d")
    end = datetime.strptime(request.end_date, "%Y-%m-%d")
    end = end + timedelta(days=1)
    
    if request.export_type == "access_logs":
        logs = db_manager.get_access_logs(
            user_id=request.user_id,
            start_date=start,
            end_date=end,
            limit=10000
        )
        data = [{"Data": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                 "UsuÃ¡rio": log.user.name if log.user else "Desconhecido",
                 "AÃ§Ã£o": log.action,
                 "Status": log.status,
                 "ConfianÃ§a": f"{log.confidence:.2f}" if log.confidence else "N/A",
                 "Fonte": log.camera_source or "N/A"} 
                for log in logs]
    elif request.export_type == "presence":
        records = db_manager.get_presence_records(
            user_id=request.user_id,
            date=request.start_date
        )
        data = [{"Data": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                 "UsuÃ¡rio": r.user.name if r.user else "N/A",
                 "Status": r.status,
                 "Entrada": r.check_in.strftime("%H:%M:%S") if r.check_in else "N/A",
                 "SaÃ­da": r.check_out.strftime("%H:%M:%S") if r.check_out else "N/A"}
                for r in records]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de exportaÃ§Ã£o invÃ¡lido"
        )
    
    if request.format == "xlsx":
        file_bytes = generate_excel_report(data, request.export_type)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"relatorio_{request.export_type}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    elif request.format == "pdf":
        file_bytes = generate_pdf_report(data, request.export_type)
        media_type = "application/pdf"
        filename = f"relatorio_{request.export_type}_{datetime.now().strftime('%Y%m%d')}.pdf"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato invÃ¡lido"
        )
    
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/hardware/open-door")
async def manual_open_door(current_user: dict = Depends(get_current_user)):
    door_manager.open_door(duration=5)
    db_manager.log_access(
        user_id=current_user.get("id"),
        action="manual_door_open",
        status="success",
        ip_address="web_dashboard"
    )
    return {"message": "Comando enviado para a porta"}


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Face Recognition Pro 2.0"}

