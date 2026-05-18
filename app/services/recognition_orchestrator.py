from datetime import datetime, timedelta
import threading
from enum import Enum
from typing import List, Dict

class RecognitionAction(Enum):
    LOG_ACCESS = "log_access"
    OPEN_DOOR = "open_door"

class RecognitionOrchestrator:
    def __init__(self, cooldown_seconds: int = 5, min_frames: int = 3, window_seconds: float = 2.5):
        self.cooldown_seconds = cooldown_seconds
        self.min_frames = min_frames
        self.window_seconds = window_seconds
        self._last_recognition: Dict[int, datetime] = {}
        self._frame_buckets: Dict[int, Dict] = {}
        self._lock = threading.Lock() # Lock para proteger o estado compartilhado

    def handle_recognition(self, user_id: int, camera_id: str) -> List[RecognitionAction]:
        now = datetime.now()
        actions = []
        
        with self._lock: # Escopo mínimo de lock para proteger os dicionários de estado
            # 1. Confirmação multi-frame
            bucket = self._frame_buckets.get(user_id)
            if bucket is None or (now - bucket["first_seen"]).total_seconds() > self.window_seconds:
                bucket = {"first_seen": now, "frames": 0}
            
            bucket["frames"] += 1
            self._frame_buckets[user_id] = bucket
            
            if bucket["frames"] < self.min_frames:
                return actions

            # 2. Cooldown de log
            last_time = self._last_recognition.get(user_id)
            if last_time is None or (now - last_time).total_seconds() >= self.cooldown_seconds:
                self._last_recognition[user_id] = now
                actions.append(RecognitionAction.LOG_ACCESS)
            
        return actions

    def cleanup(self):
        """Remove entries older than 1 hour to prevent memory leaks."""
        now = datetime.now()
        expired = now - timedelta(hours=1)
        
        with self._lock: # Garante que a limpeza não conflite com novos reconhecimentos
            keys_to_remove = [k for k, v in self._last_recognition.items() if v < expired]
            for k in keys_to_remove:
                del self._last_recognition[k]
                
            keys_to_remove = [k for k, v in self._frame_buckets.items() if v["first_seen"] < expired]
            for k in keys_to_remove:
                del self._frame_buckets[k]

    def get_metrics(self) -> Dict[str, int]:
        """Return cache and bucket sizes in a thread-safe manner."""
        with self._lock:
            return {
                "cache_size": len(self._last_recognition),
                "buckets_size": len(self._frame_buckets)
            }

