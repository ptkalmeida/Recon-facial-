import os
import json
import logging
import threading
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    create_engine, event, inspect, text, Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Enum, JSON, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, joinedload
from sqlalchemy.sql import func
from contextlib import contextmanager
import yaml

logger = logging.getLogger(__name__)


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
    #: Última vez em que a pessoa foi vista nesta visita. Nulo em registros
    #: anteriores à coluna (ver `_migrar_schema`).
    last_seen = Column(DateTime, nullable=True)
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
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "camera_source": self.camera_source,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AlertEvent(Base):
    """Outbox de alertas: uma linha por (evento, canal).

    O alerta é gravado ANTES de qualquer tentativa de envio, e um dispatcher
    separado entrega com nova tentativa (ver app/services/alerts.py). Antes, o
    e-mail era disparado numa thread sem retorno: SMTP fora do ar = alerta
    perdido, sem rastro.
    """
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False)
    channel = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False)
    #: pending (aguardando 1ª tentativa) | sent | failed (nova tentativa em
    #: next_attempt_at, ou definitivo quando next_attempt_at é nulo)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    delivered_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_alert_due", "status", "next_attempt_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "channel": self.channel,
            "payload": self.payload,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "next_attempt_at": self.next_attempt_at.isoformat() if self.next_attempt_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
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


#: Colunas acrescentadas depois da criação original das tabelas. `create_all`
#: cria tabela nova mas não altera tabela existente, então um banco já instalado
#: precisa do ADD COLUMN. Só acréscimo de coluna anulável: é idempotente e não
#: toca em dado existente. (Alembic seria exagero para isso - e exigiria marcar o
#: banco atual como baseline antes do primeiro upgrade.)
MIGRACOES_DE_COLUNA = [
    ("presence_records", "last_seen", "DATETIME"),
]


def _migrar_schema(engine) -> None:
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())
    with engine.begin() as conn:
        for tabela, coluna, tipo in MIGRACOES_DE_COLUNA:
            if tabela not in tabelas:
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela)}
            if coluna not in existentes:
                logger.info("Migração: adicionando %s.%s", tabela, coluna)
                conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"))


#: Espera por um lock de escrita antes de desistir com "database is locked".
SQLITE_BUSY_TIMEOUT_MS = 30000


def _configurar_conexao_sqlite(dbapi_conn, _registro, wal: bool) -> None:
    """PRAGMAs por conexão (o SQLite não guarda busy_timeout no arquivo).

    Escrevem no banco ao mesmo tempo as requisições HTTP (threads do pool), a
    câmera do servidor e as threads de alerta. No modo de journal padrão
    (DELETE) uma escrita bloqueia até as leituras, e o SQLite desiste na hora
    com "database is locked".

    - WAL: leitores não bloqueiam o escritor, nem o contrário.
    - synchronous=NORMAL: seguro com WAL (perde no máximo a última transação
      numa queda de energia, sem corromper) e bem mais rápido que FULL.
    - busy_timeout: espera o lock em vez de falhar de imediato.

    `foreign_keys` fica DESLIGADO de propósito: o log de abertura manual da
    porta grava o id do admin (0), que não é linha de `users`, e o banco real já
    tem registros assim - ligar a checagem faria esse botão responder 500. As
    remoções já são feitas em cascata pelo ORM.
    """
    cursor = dbapi_conn.cursor()
    try:
        if wal:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


class DatabaseManager:
    def __init__(self, db_path: str = "data/face_recognition.db", wal: bool = True):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={
                "check_same_thread": False,
                "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000,
            }
        )
        # WAL não se aplica a banco em memória; também pode ser desligado
        # (DATABASE_WAL=false) para banco em pasta de rede, onde WAL não é
        # suportado pelo SQLite.
        usar_wal = wal and db_path != ":memory:"
        event.listen(
            self.engine, "connect",
            lambda conn, reg: _configurar_conexao_sqlite(conn, reg, usar_wal),
        )
        Base.metadata.create_all(self.engine)
        _migrar_schema(self.engine)
        # Serializa mark_seen: duas detecções simultâneas da mesma pessoa não
        # podem abrir duas visitas.
        self._presence_lock = threading.Lock()
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
            # Flush to assign the primary key; commit happens automatically via context manager
            session.flush()
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
                session.flush()
                # `updated_at` é gerado pelo banco no UPDATE (onupdate=now) e
                # fica expirado após o flush. Sem carregá-lo aqui, o to_dict()
                # da resposta tentava buscá-lo com a sessão já fechada e o PUT
                # respondia 500 - depois de a alteração já ter sido gravada.
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
        from app.security.crypto import get_embedding_cipher

        with self.session() as session:
            embedding = Embedding(
                user_id=user_id,
                # Dado biométrico criptografado em repouso quando
                # EMBEDDING_ENCRYPTION_KEY está definida.
                embedding_data=get_embedding_cipher().encrypt(embedding_data),
                model_used=model_used,
                image_path=image_path,
                is_primary=is_primary
            )
            session.add(embedding)
            session.flush()
            return embedding

    def get_embeddings(self, user_id: int) -> List[Embedding]:
        with self.session() as session:
            return session.query(Embedding).filter(Embedding.user_id == user_id).all()

    def get_all_embeddings(self) -> List[Embedding]:
        """Embeddings das pessoas que podem ser reconhecidas.

        Só usuários ATIVOS: sem o filtro, desativar alguém (is_active=False) não
        revogava nada - a pessoa continuava sendo reconhecida e abrindo a porta,
        inclusive depois de reiniciar o servidor.
        """
        with self.session() as session:
            return (
                session.query(Embedding)
                .join(User, Embedding.user_id == User.id)
                .options(joinedload(Embedding.user))
                .filter(Embedding.is_primary == True, User.is_active == True)
                .all()
            )

    def get_all_embeddings_data(self) -> List[Dict[str, Any]]:
        from app.security.crypto import EmbeddingCipherError, get_embedding_cipher

        cipher = get_embedding_cipher()
        data = []
        for embedding in self.get_all_embeddings():
            try:
                embedding_data = cipher.decrypt(embedding.embedding_data)
            except EmbeddingCipherError as exc:
                # Um embedding ilegível não pode derrubar o carregamento dos
                # outros - o rosto correspondente deixa de ser reconhecido até
                # que a chave/salt correta seja restaurada.
                logger.error(
                    "Embedding %s (user_id=%s) ignorado: %s",
                    embedding.id, embedding.user_id, exc
                )
                continue
            data.append({
                "user_id": embedding.user_id,
                "user_name": embedding.user.name if embedding.user else "Unknown",
                "embedding_data": embedding_data,
                "model_used": embedding.model_used,
            })
        return data

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
            session.flush()
            return log

    def get_access_logs(self, user_id: Optional[int] = None,
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       after_id: Optional[int] = None,
                       limit: int = 100) -> List[AccessLog]:
        with self.session() as session:
            query = session.query(AccessLog).options(joinedload(AccessLog.user))
            if user_id:
                query = query.filter(AccessLog.user_id == user_id)
            if start_date:
                query = query.filter(AccessLog.created_at >= start_date)
            if end_date:
                query = query.filter(AccessLog.created_at <= end_date)
            if after_id:
                query = query.filter(AccessLog.id > after_id)
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
            session.flush()
            return record

    @staticmethod
    def _presence_timeout() -> float:
        return settings_dict.get("presence", {}).get("timeout_seconds", 60)

    def mark_seen(self, user_id: int, camera_source: Optional[str] = None) -> PresenceRecord:
        """Registra que a pessoa foi vista agora.

        Uma visita é um registro só: a entrada cria o registro, e cada nova
        detecção atualiza `last_seen`. Antes, a presença dependia da idade do
        registro de entrada - quem ficava parado diante da câmera virava
        "ausente" depois do timeout e ganhava uma "entrada" nova a cada minuto,
        e nunca se gravava saída.

        Se a última visita já passou do timeout, ela é encerrada (status
        "saida", `check_out` = última vez visto) e uma nova começa.
        """
        timeout = self._presence_timeout()
        with self._presence_lock, self.session() as session:
            agora = datetime.now()
            ultimo = (
                session.query(PresenceRecord)
                .filter(PresenceRecord.user_id == user_id)
                .order_by(PresenceRecord.id.desc())
                .first()
            )
            if ultimo is not None and ultimo.status == "entrada":
                visto = ultimo.last_seen or ultimo.created_at
                if visto and (agora - visto).total_seconds() < timeout:
                    ultimo.last_seen = agora
                    session.flush()
                    return ultimo
                if ultimo.last_seen is not None:
                    self._encerrar_visita(ultimo)

            visita = PresenceRecord(
                user_id=user_id,
                status="entrada",
                check_in=agora,
                last_seen=agora,
                camera_source=camera_source,
            )
            session.add(visita)
            session.flush()
            return visita

    @staticmethod
    def _encerrar_visita(registro: PresenceRecord) -> None:
        registro.status = "saida"
        registro.check_out = registro.last_seen

    def close_stale_presence(self) -> int:
        """Encerra visitas sem detecção há mais que o timeout. Devolve quantas.

        Só mexe em registros com `last_seen` (criados por mark_seen). Registros
        antigos, anteriores à coluna, ficam como estão: eram eventos avulsos de
        entrada, e reescrevê-los como visitas encerradas inventaria uma saída.
        """
        limite = datetime.now() - timedelta(seconds=self._presence_timeout())
        with self._presence_lock, self.session() as session:
            abertas = (
                session.query(PresenceRecord)
                .filter(
                    PresenceRecord.status == "entrada",
                    PresenceRecord.last_seen.isnot(None),
                    PresenceRecord.last_seen < limite,
                )
                .all()
            )
            for registro in abertas:
                self._encerrar_visita(registro)
            return len(abertas)

    # --- Retenção -----------------------------------------------------------

    #: Linhas apagadas por transação: uma transação gigante trava o banco para
    #: as outras escritas durante todo o DELETE.
    RETENTION_BATCH = 5000

    def _apagar_em_lotes(self, modelo, filtros) -> int:
        total = 0
        while True:
            with self.session() as session:
                ids = [
                    linha[0] for linha in
                    session.query(modelo.id).filter(*filtros).limit(self.RETENTION_BATCH).all()
                ]
                if not ids:
                    return total
                session.query(modelo).filter(modelo.id.in_(ids)).delete(synchronize_session=False)
                total += len(ids)

    def purge_expired(self, access_log_days: int = 0, presence_days: int = 0,
                      alert_days: int = 0) -> Dict[str, int]:
        """Apaga registros mais velhos que o prazo de cada tabela (0 = nunca).

        Alertas: só os resolvidos (entregues, ou desistidos sem nova tentativa
        agendada) - um alerta pendente nunca é apagado por idade.
        """
        agora = datetime.now()
        apagados = {"access_logs": 0, "presence_records": 0, "alert_events": 0}
        if access_log_days > 0:
            limite = agora - timedelta(days=access_log_days)
            apagados["access_logs"] = self._apagar_em_lotes(
                AccessLog, [AccessLog.created_at < limite])
        if presence_days > 0:
            limite = agora - timedelta(days=presence_days)
            apagados["presence_records"] = self._apagar_em_lotes(
                PresenceRecord, [PresenceRecord.created_at < limite])
        if alert_days > 0:
            limite = agora - timedelta(days=alert_days)
            apagados["alert_events"] = self._apagar_em_lotes(AlertEvent, [
                AlertEvent.created_at < limite,
                AlertEvent.next_attempt_at.is_(None),
                AlertEvent.status.in_(("sent", "failed")),
            ])
        return apagados

    # --- Outbox de alertas ------------------------------------------------

    def enqueue_alert(self, event_type: str, payload: Dict[str, Any],
                      channels: List[str]) -> List[int]:
        """Grava o alerta para cada canal; devolve os ids criados."""
        agora = datetime.now()
        with self.session() as session:
            eventos = [
                AlertEvent(event_type=event_type, channel=canal, payload=payload,
                           status="pending", attempts=0, next_attempt_at=agora)
                for canal in channels
            ]
            session.add_all(eventos)
            session.flush()
            return [e.id for e in eventos]

    def claim_due_alerts(self, max_attempts: int, limit: int = 20) -> List[AlertEvent]:
        """Alertas prontos para (nova) tentativa, mais antigos primeiro.

        Não é um claim atômico: vale para UM dispatcher por banco, que é o caso
        (um processo). Com vários processos, trocar por UPDATE ... RETURNING.
        """
        agora = datetime.now()
        with self.session() as session:
            return (
                session.query(AlertEvent)
                .filter(
                    AlertEvent.status.in_(("pending", "failed")),
                    AlertEvent.next_attempt_at.isnot(None),
                    AlertEvent.next_attempt_at <= agora,
                    AlertEvent.attempts < max_attempts,
                )
                .order_by(AlertEvent.id.asc())
                .limit(limit)
                .all()
            )

    def record_alert_attempt(self, alert_id: int, error: Optional[str],
                             next_attempt_at: Optional[datetime]) -> None:
        """Resultado de uma tentativa: `error=None` significa entregue."""
        with self.session() as session:
            evento = session.get(AlertEvent, alert_id)
            if evento is None:
                return
            evento.attempts = (evento.attempts or 0) + 1
            if error is None:
                evento.status = "sent"
                evento.delivered_at = datetime.now()
                evento.last_error = None
                evento.next_attempt_at = None
            else:
                evento.status = "failed"
                evento.last_error = error
                evento.next_attempt_at = next_attempt_at

    def get_alert_events(self, limit: int = 100) -> List[AlertEvent]:
        with self.session() as session:
            return (
                session.query(AlertEvent)
                .order_by(AlertEvent.id.desc())
                .limit(limit)
                .all()
            )

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
                
                timeout = self._presence_timeout()
                now = datetime.now()
                processed_results = []

                for user, last_record in results:
                    status = "ausente"
                    check_in = None
                    # Registros novos têm last_seen; os antigos só created_at.
                    visto = None
                    if last_record:
                        visto = last_record.last_seen or last_record.created_at

                    if last_record and last_record.status == "entrada" and visto:
                        if (now - visto).total_seconds() < timeout:
                            status = "presente"
                            entrada = last_record.check_in or last_record.created_at
                            check_in = entrada.strftime("%H:%M:%S")

                    processed_results.append({
                        "user": user.to_dict(),
                        "status": status,
                        "check_in": check_in,
                        "last_seen": visto.isoformat() if visto else None
                    })
                    
                return processed_results
            except Exception:
                raise



# Fonte única de configuração: este módulo carregava config.yaml por conta
# própria, em paralelo a app/config.py, e as duas leituras discordavam (o YAML
# ignorava DATABASE_PATH do ambiente). Agora tudo vem de app.config, onde a
# precedência é ambiente > .env > config.yaml > default.
from app.config import settings, settings_dict  # noqa: E402

db_manager = DatabaseManager(settings.database_path, wal=settings.database_wal)
