import os
import json
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Boolean,
    Text, ForeignKey, Enum, JSON, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, joinedload
from sqlalchemy.sql import func
from contextlib import contextmanager
import yaml


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), unique=True, nullable=True)
    role = Column(String(50), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    embeddings = relationship("Embedding", back_populates="user", cascade="all, delete-orphan")
    access_logs = relationship("AccessLog", back_populates="user", cascade="all, delete-orphan")
    presence_records = relationship("PresenceRecord", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    embedding_data = Column(JSON, nullable=False)
    model_used = Column(String(100), default="Facenet512")
    face_quality_score = Column(Float, nullable=True)
    image_path = Column(String(500), nullable=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="embeddings")

    __table_args__ = (
        Index("idx_user_id", "user_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "embedding_data": self.embedding_data,
            "model_used": self.model_used,
            "face_quality_score": self.face_quality_score,
            "image_path": self.image_path,
            "is_primary": self.is_primary,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    status = Column(String(50), default="success")
    camera_source = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="access_logs")

    __table_args__ = (
        Index("idx_created_at", "created_at"),
        Index("idx_user_action", "user_id", "action"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "action": self.action,
            "status": self.status,
            "camera_source": self.camera_source,
            "confidence": self.confidence,
            "ip_address": self.ip_address,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class PresenceRecord(Base):
    __tablename__ = "presence_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(50), nullable=False)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    camera_source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="presence_records")

    __table_args__ = (
        Index("idx_user_date", "user_id", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "status": self.status,
            "check_in": self.check_in.isoformat() if self.check_in else None,
            "check_out": self.check_out.isoformat() if self.check_out else None,
            "camera_source": self.camera_source,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    source = Column(String(500), nullable=False)
    source_type = Column(String(50), default="webcam")
    is_active = Column(Boolean, default=True)
    location = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "source_type": self.source_type,
            "is_active": self.is_active,
            "location": self.location,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class DatabaseManager:
    def __init__(self, db_path: str = "data/face_recognition.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False
        )

    def get_session(self):
        return self.SessionLocal()

    @contextmanager
    def session(self):
        """Provide a transactional scope around a series of operations."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_user(self, name: str, email: Optional[str] = None, role: str = "user") -> User:
        with self.session() as session:
            user = User(name=name, email=email, role=role)
            session.add(user)
            # Commit happens automatically via context manager
            session.refresh(user)
            return user

    def get_user(self, user_id: int) -> Optional[User]:
        with self.session() as session:
            return session.query(User).filter(User.id == user_id).first()

    def get_user_by_name(self, name: str) -> Optional[User]:
        with self.session() as session:
            return session.query(User).filter(User.name == name).first()

    def get_all_users(self, active_only: bool = True) -> List[User]:
        with self.session() as session:
            query = session.query(User)
            if active_only:
                query = query.filter(User.is_active == True)
            return query.all()

    def update_user(self, user_id: int, **kwargs) -> Optional[User]:
        with self.session() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if user:
                for key, value in kwargs.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
                session.refresh(user)
            return user

    def delete_user(self, user_id: int) -> bool:
        with self.session() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if user:
                session.delete(user)
                return True
            return False

    def add_embedding(self, user_id: int, embedding_data: List[float], 
                      model_used: str = "Facenet512", image_path: Optional[str] = None,
                      is_primary: bool = False) -> Embedding:
        with self.session() as session:
            embedding = Embedding(
                user_id=user_id,
                embedding_data=embedding_data,
                model_used=model_used,
                image_path=image_path,
                is_primary=is_primary
            )
            session.add(embedding)
            session.refresh(embedding)
            return embedding

    def get_embeddings(self, user_id: int) -> List[Embedding]:
        with self.session() as session:
            return session.query(Embedding).filter(Embedding.user_id == user_id).all()

    def get_all_embeddings(self) -> List[Embedding]:
        with self.session() as session:
            return (
                session.query(Embedding)
                .options(joinedload(Embedding.user))
                .filter(Embedding.is_primary == True)
                .all()
            )

    def get_all_embeddings_data(self) -> List[Dict[str, Any]]:
        embeddings = self.get_all_embeddings()
        return [
            {
                "user_id": embedding.user_id,
                "user_name": embedding.user.name if embedding.user else "Unknown",
                "embedding_data": embedding.embedding_data
            }
            for embedding in embeddings
        ]

    def log_access(self, user_id: Optional[int], action: str, status: str = "success",
                   camera_source: Optional[str] = None, confidence: Optional[float] = None,
                   **kwargs) -> AccessLog:
        with self.session() as session:
            log = AccessLog(
                user_id=user_id,
                action=action,
                status=status,
                camera_source=camera_source,
                confidence=confidence,
                **kwargs
            )
            session.add(log)
            session.refresh(log)
            return log

    def get_access_logs(self, user_id: Optional[int] = None, 
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       limit: int = 100) -> List[AccessLog]:
        with self.session() as session:
            query = session.query(AccessLog).options(joinedload(AccessLog.user))
            if user_id:
                query = query.filter(AccessLog.user_id == user_id)
            if start_date:
                query = query.filter(AccessLog.created_at >= start_date)
            if end_date:
                query = query.filter(AccessLog.created_at <= end_date)
            return query.order_by(AccessLog.created_at.desc()).limit(limit).all()

    def log_presence(self, user_id: int, status: str, camera_source: Optional[str] = None) -> PresenceRecord:
        with self.session() as session:
            record = PresenceRecord(
                user_id=user_id,
                status=status,
                camera_source=camera_source
            )
            if status == "entrada":
                record.check_in = datetime.now()
            elif status == "saida":
                record.check_out = datetime.now()
            session.add(record)
            session.refresh(record)
            return record

    def get_presence_records(self, user_id: Optional[int] = None,
                            date: Optional[str] = None) -> List[PresenceRecord]:
        with self.session() as session:
            query = session.query(PresenceRecord).options(joinedload(PresenceRecord.user))
            if user_id:
                query = query.filter(PresenceRecord.user_id == user_id)
            if date:
                from sqlalchemy import func
                query = query.filter(
                    func.date(PresenceRecord.created_at) == date
                )
            return query.order_by(PresenceRecord.created_at.desc()).all()

    def get_dashboard_stats(self) -> Dict[str, int]:
        """Get optimized system statistics using SQL aggregates."""
        with self.session() as session:
            try:
                from sqlalchemy import func
                today = datetime.now().date()
                
                total_users = session.query(func.count(User.id)).scalar()
                active_users = session.query(func.count(User.id)).filter(User.is_active == True).scalar()
                
                # Count access logs today
                access_today = session.query(func.count(AccessLog.id)).filter(
                    func.date(AccessLog.created_at) == today
                ).scalar()
                
                # Count unknown detections today
                unknown_today = session.query(func.count(AccessLog.id)).filter(
                    func.date(AccessLog.created_at) == today,
                    AccessLog.action == "unknown_detected"
                ).scalar()
                
                # Count people currently present (optimized)
                # This is slightly more complex as it depends on the latest record
                # We'll use a simpler approximation here: count unique users who entered today and didn't leave
                # For exact "present_today" from the dashboard's perspective:
                current_presence = self.get_current_presence()
                present_count = sum(1 for p in current_presence if p.get("status") == "presente")
    
                return {
                    "total_users": total_users,
                    "active_users": active_users,
                    "access_today": access_today,
                    "unknown_today": unknown_today,
                    "present_today": present_count
                }
            except Exception:
                raise

    def get_current_presence(self) -> List[Dict[str, Any]]:
        """Optimized: Get current presence of all active users in ONE query."""
        with self.session() as session:
            try:
                from sqlalchemy import func
                
                # Subquery to find the ID of the latest record per user
                latest_id_subquery = session.query(
                    PresenceRecord.user_id,
                    func.max(PresenceRecord.id).label("max_id")
                ).group_by(PresenceRecord.user_id).subquery()
                
                # Join users with their latest presence record
                results = session.query(User, PresenceRecord).outerjoin(
                    latest_id_subquery, User.id == latest_id_subquery.c.user_id
                ).outerjoin(
                    PresenceRecord, PresenceRecord.id == latest_id_subquery.c.max_id
                ).filter(User.is_active == True).all()
                
                timeout = settings_dict.get("presence", {}).get("timeout_seconds", 60)
                now = datetime.now()
                processed_results = []
                
                for user, last_record in results:
                    status = "ausente"
                    check_in = None
                    
                    if last_record and last_record.status == "entrada":
                        if (now - last_record.created_at).total_seconds() < timeout:
                            status = "presente"
                            check_in = last_record.created_at.strftime("%H:%M:%S")
                    
                    processed_results.append({
                        "user": user.to_dict(),
                        "status": status,
                        "check_in": check_in,
                        "last_seen": last_record.created_at.isoformat() if last_record else None
                    })
                    
                return processed_results
            except Exception:
                raise



def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), config_path)
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


settings_dict = load_config()
db_manager = DatabaseManager(settings_dict.get("database", {}).get("path", "data/face_recognition.db"))
