"""Alertas confiáveis: outbox no banco + dispatcher com nova tentativa.

Antes, o alerta de desconhecido era um e-mail disparado numa thread sem
retorno: SMTP fora do ar, credencial trocada ou rede instável = alerta perdido,
sem rastro. Agora:

1. `emit()` só GRAVA o alerta em `alert_events`, uma linha por canal
   configurado - rápido, e nada se perde se o destino estiver fora do ar;
2. o dispatcher (uma thread) entrega o que está pendente e, na falha, agenda
   nova tentativa: 60 s, 5 min, 30 min - até 4 tentativas. Cada tentativa fica
   registrada (attempts, last_error, delivered_at).

Um dispatcher por banco: o claim não é atômico entre processos (ver
DatabaseManager.claim_due_alerts).
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from app.security.redaction import redact_url_credentials

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
#: Espera antes da 2ª, 3ª e 4ª tentativas.
BACKOFF_SECONDS = (60, 300, 1800)
DISPATCH_INTERVAL_SECONDS = 2.0
LAST_ERROR_MAX_CHARS = 500


class AlertService:
    def __init__(self, db, channels: list, enabled: bool,
                 cooldown_seconds: float = 600, clock: Callable[[], float] = time.monotonic):
        self._db = db
        self._channels = {c.name: c for c in channels}
        self.enabled = enabled
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._ultimo_por_chave: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        #: Funções chamadas a cada volta do dispatcher (monitor de câmera).
        self._tick_hooks: list[Callable[[], None]] = []

    @property
    def channel_names(self) -> list[str]:
        return list(self._channels)

    def emit(self, event_type: str, payload: dict, cooldown_key: Optional[str] = None) -> bool:
        """Grava o alerta no outbox. Devolve True se algo foi enfileirado.

        `cooldown_key` (ex.: a câmera) limita a repetição: o mesmo tipo de
        evento com a mesma chave não é enfileirado de novo antes de
        `cooldown_seconds`. Sem chave, não há cooldown.
        """
        if not self.enabled:
            return False
        if not self._channels:
            logger.warning("Alertas habilitados, mas nenhum canal configurado (SMTP ou webhook)")
            return False

        if cooldown_key is not None:
            chave = (event_type, cooldown_key)
            agora = self._clock()
            with self._lock:
                ultimo = self._ultimo_por_chave.get(chave)
                if ultimo is not None and agora - ultimo < self.cooldown_seconds:
                    return False
                self._ultimo_por_chave[chave] = agora

        dados = {"occurred_at": datetime.now().isoformat(timespec="seconds"), **payload}
        self._db.enqueue_alert(event_type, dados, self.channel_names)
        return True

    def dispatch_due(self) -> int:
        """Tenta entregar os alertas vencidos. Devolve quantos foram entregues."""
        entregues = 0
        for evento in self._db.claim_due_alerts(MAX_ATTEMPTS):
            canal = self._channels.get(evento.channel)
            erro = None
            if canal is None:
                erro = f"canal '{evento.channel}' não está mais configurado"
            else:
                try:
                    canal.deliver({
                        "event_id": evento.id,
                        "event_type": evento.event_type,
                        "payload": evento.payload,
                    })
                except Exception as exc:  # qualquer falha de canal vira nova tentativa
                    erro = redact_url_credentials(f"{type(exc).__name__}: {exc}")[:LAST_ERROR_MAX_CHARS]

            tentativa = (evento.attempts or 0) + 1
            proxima = None
            if erro is not None and tentativa < MAX_ATTEMPTS:
                proxima = datetime.now() + timedelta(seconds=BACKOFF_SECONDS[tentativa - 1])
            self._db.record_alert_attempt(evento.id, erro, proxima)

            if erro is None:
                entregues += 1
            elif proxima is None:
                logger.error("Alerta %s via %s desistido após %d tentativas: %s",
                             evento.id, evento.channel, tentativa, erro)
            else:
                logger.warning("Alerta %s via %s falhou (tentativa %d): %s",
                               evento.id, evento.channel, tentativa, erro)
        return entregues

    def add_tick_hook(self, hook: Callable[[], None]) -> None:
        self._tick_hooks.append(hook)

    def _loop(self) -> None:
        while not self._stop.is_set():
            for hook in list(self._tick_hooks):
                try:
                    hook()
                except Exception as e:
                    logger.error(f"Erro no monitor de alertas: {e}")
            try:
                self.dispatch_due()
            except Exception as e:
                logger.error(f"Erro no dispatcher de alertas: {e}")
            self._stop.wait(DISPATCH_INTERVAL_SECONDS)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AlertDispatcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def cleanup(self) -> None:
        """Esquece cooldowns vencidos (evita crescer sem limite)."""
        agora = self._clock()
        with self._lock:
            for chave in [k for k, v in self._ultimo_por_chave.items()
                          if agora - v >= self.cooldown_seconds]:
                del self._ultimo_por_chave[chave]


class CameraOfflineMonitor:
    """Alerta de câmera fora do ar, com aviso de volta.

    Recebe as mudanças de conexão do CameraWorker (`on_status`) e, a cada
    `check()`, dispara "camera_offline" se a câmera está desconectada há mais
    de `threshold_seconds` - quedas curtas (uma reconexão) não alertam - e
    "camera_online" quando ela volta depois de ter sido dada como offline.
    Cobre de uma vez rede caída, câmera desligada, senha trocada e stream
    travado (o watchdog do worker derruba a conexão).
    """

    def __init__(self, alert_service: AlertService, threshold_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self._alerts = alert_service
        self.threshold_seconds = threshold_seconds
        self._clock = clock
        self._desconectada_desde: dict[str, float] = {}
        self._alertada: set[str] = set()
        self._lock = threading.Lock()

    def register(self, camera_id: str) -> None:
        """Câmera recém-iniciada conta como desconectada até o primeiro frame."""
        with self._lock:
            self._desconectada_desde.setdefault(camera_id, self._clock())

    def on_status(self, camera_id: str, conectada: bool) -> None:
        with self._lock:
            if conectada:
                inicio = self._desconectada_desde.pop(camera_id, None)
                if camera_id in self._alertada:
                    self._alertada.discard(camera_id)
                    fora = self._clock() - inicio if inicio is not None else None
                    self._alerts.emit("camera_online", {
                        "camera_id": camera_id,
                        "offline_seconds": round(fora) if fora is not None else None,
                    })
            else:
                self._desconectada_desde.setdefault(camera_id, self._clock())

    def check(self) -> None:
        agora = self._clock()
        with self._lock:
            for camera_id, desde in self._desconectada_desde.items():
                if camera_id in self._alertada or agora - desde < self.threshold_seconds:
                    continue
                self._alertada.add(camera_id)
                self._alerts.emit("camera_offline", {
                    "camera_id": camera_id,
                    "offline_seconds": round(agora - desde),
                })
