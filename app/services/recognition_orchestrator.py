from datetime import datetime, timedelta
import threading
from enum import Enum
from typing import List, Dict, Optional, Tuple

class RecognitionAction(Enum):
    LOG_ACCESS = "log_access"
    OPEN_DOOR = "open_door"

class RecognitionOrchestrator:
    """Filtra falso positivo antes dos efeitos (log, presença, porta, alerta).

    - Confirmação multi-frame: só age depois de `min_frames` observações na
      janela de `window_seconds`, POR CÂMERA. Antes a contagem era só por
      pessoa, e frames da mesma pessoa em câmeras diferentes somavam juntos.
    - Cooldown de log por pessoa (`cooldown_seconds`).
    - Desconhecidos passam pelo mesmo filtro, por câmera. Antes, cada frame com
      um rosto desconhecido gravava uma linha de log e abria uma thread de
      e-mail: um frame ruim de uma pessoa cadastrada já virava "desconhecido
      detectado", e um visitante parado diante da câmera gerava uma linha por
      segundo.
    """

    def __init__(self, cooldown_seconds: int = 5, min_frames: int = 3, window_seconds: float = 2.5):
        self.cooldown_seconds = cooldown_seconds
        self.min_frames = min_frames
        self.window_seconds = window_seconds
        self._last_recognition: Dict[int, datetime] = {}
        self._frame_buckets: Dict[Tuple[str, int], Dict] = {}
        self._unknown_buckets: Dict[str, Dict] = {}
        self._last_unknown_log: Dict[str, datetime] = {}
        self._lock = threading.Lock() # Lock para proteger o estado compartilhado

    def _confirmar(self, buckets: Dict, chave, now: datetime) -> bool:
        """Conta uma observação e diz se a janela já tem frames suficientes."""
        bucket = buckets.get(chave)
        if bucket is None or (now - bucket["first_seen"]).total_seconds() > self.window_seconds:
            bucket = {"first_seen": now, "frames": 0}
        bucket["frames"] += 1
        buckets[chave] = bucket
        return bucket["frames"] >= self.min_frames

    def handle_recognition(self, user_id: int, camera_id: str) -> List[RecognitionAction]:
        now = datetime.now()
        actions = []

        with self._lock: # Escopo mínimo de lock para proteger os dicionários de estado
            # 1. Confirmação multi-frame (por câmera)
            if not self._confirmar(self._frame_buckets, (camera_id, user_id), now):
                return actions

            # 2. Cooldown de log
            last_time = self._last_recognition.get(user_id)
            if last_time is None or (now - last_time).total_seconds() >= self.cooldown_seconds:
                self._last_recognition[user_id] = now
                actions.append(RecognitionAction.LOG_ACCESS)

        return actions

    def handle_unknown(self, camera_id: Optional[str]) -> List[RecognitionAction]:
        """Um frame com rosto desconhecido nesta câmera.

        Chamado uma vez por frame (não por rosto): três desconhecidos no mesmo
        frame são uma observação, não três. Devolve LOG_ACCESS quando o
        desconhecido se confirmou por `min_frames` frames na janela e o
        cooldown da câmera já passou.
        """
        camera = camera_id or "webcam"
        now = datetime.now()
        with self._lock:
            if not self._confirmar(self._unknown_buckets, camera, now):
                return []
            ultimo = self._last_unknown_log.get(camera)
            if ultimo is not None and (now - ultimo).total_seconds() < self.cooldown_seconds:
                return []
            self._last_unknown_log[camera] = now
            return [RecognitionAction.LOG_ACCESS]

    def cleanup(self):
        """Remove entries older than 1 hour to prevent memory leaks."""
        now = datetime.now()
        expired = now - timedelta(hours=1)

        with self._lock: # Garante que a limpeza não conflite com novos reconhecimentos
            for registro in (self._last_recognition, self._last_unknown_log):
                for k in [k for k, v in registro.items() if v < expired]:
                    del registro[k]

            for buckets in (self._frame_buckets, self._unknown_buckets):
                for k in [k for k, v in buckets.items() if v["first_seen"] < expired]:
                    del buckets[k]

    def get_metrics(self) -> Dict[str, int]:
        """Return cache and bucket sizes in a thread-safe manner."""
        with self._lock:
            return {
                "cache_size": len(self._last_recognition) + len(self._last_unknown_log),
                "buckets_size": len(self._frame_buckets) + len(self._unknown_buckets),
            }
