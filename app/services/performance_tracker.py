import threading
import time
from collections import deque


class PerformanceTracker:
    """Tracks recent frame-processing latencies to expose avg latency and detection FPS."""

    def __init__(self, window_size: int = 200):
        self.window_size = window_size
        self._samples: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def record(self, processing_time_ms: float) -> None:
        with self._lock:
            self._samples.append((time.time(), processing_time_ms))

    def get_metrics(self) -> dict[str, float]:
        with self._lock:
            if not self._samples:
                return {"avg_detection_latency_ms": 0.0, "detection_fps": 0.0}

            avg_latency_ms = sum(t for _, t in self._samples) / len(self._samples)

            oldest_ts = self._samples[0][0]
            newest_ts = self._samples[-1][0]
            elapsed = newest_ts - oldest_ts
            if elapsed > 0 and len(self._samples) > 1:
                detection_fps = (len(self._samples) - 1) / elapsed
            else:
                detection_fps = 0.0

            return {
                "avg_detection_latency_ms": round(avg_latency_ms, 2),
                "detection_fps": round(detection_fps, 2),
            }
