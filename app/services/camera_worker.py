"""Optional server-side camera capture (local webcam index or RTSP/file URL).

Adapted from EPI-Detect-main/core/capture.py + server.py's threaded capture pattern.
Disabled by default (SERVER_CAMERA_ENABLED=false) — the browser-based capture flow in
app/templates/dashboard.html keeps working unchanged whether this is enabled or not.
"""

import logging
import threading
import time
from datetime import datetime
from sys import platform

import cv2

logger = logging.getLogger(__name__)


def resolve_camera_source(value: str) -> int | str | None:
    """Turn SERVER_CAMERA_SOURCE into a cv2-friendly source.

    Empty/unset -> None (disabled). A plain integer string -> local webcam index.
    Anything else (rtsp://..., a file path) -> passed through as-is.
    """
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return value


class VideoCapture:
    """Threaded reader for a webcam index; direct reads for RTSP/file sources.

    A dedicated thread keeps only the most recent webcam frame available, so the
    consumer never processes a stale buffered frame. RTSP/file sources are read
    directly — threading doesn't help there and only adds overhead.
    """

    def __init__(self, source, width=None, height=None, fps=None):
        self._is_webcam = isinstance(source, int)
        self._cap = self._open_capture(source)

        if not self._cap.isOpened():
            raise RuntimeError(f"Não foi possível abrir a fonte de câmera: {source}")

        if self._is_webcam:
            if width:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            if height:
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if fps:
                self._cap.set(cv2.CAP_PROP_FPS, fps)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._frame = None
            self._ok = False
            self._lock = threading.Lock()
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._reader, daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 5.0
            while self._frame is None and time.monotonic() < deadline:
                time.sleep(0.05)

    def _open_capture(self, source):
        if not isinstance(source, int):
            return cv2.VideoCapture(source)

        backends = [cv2.CAP_ANY]
        if platform.startswith("win"):
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

        for backend in backends:
            cap = cv2.VideoCapture(source, backend)
            if cap.isOpened():
                return cap
            cap.release()

        return cv2.VideoCapture(source)

    def _reader(self):
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            with self._lock:
                if ok and frame is not None:
                    self._frame = frame
                self._ok = ok
            if not ok:
                time.sleep(0.05)

    def read(self):
        if self._is_webcam:
            with self._lock:
                if self._frame is None:
                    return False, None
                return self._ok, self._frame.copy()
        return self._cap.read()

    def release(self):
        if self._is_webcam:
            self._stop.set()
            self._thread.join(timeout=2)
        self._cap.release()


class CameraWorker:
    """Continuously reads frames from a server-side camera and runs recognition.

    Reuses the same face_service/performance_tracker/handle_detection_results that
    the /api/recognition/detect HTTP route uses, so results (access logs, presence,
    door control, unknown-face alerts) are identical regardless of which capture
    path produced the frame.
    """

    def __init__(self, source, camera_id: str, interval_seconds: float,
                 face_service, performance_tracker, handle_results_fn):
        self.source = source
        self.camera_id = camera_id
        self.interval_seconds = interval_seconds
        self._face_service = face_service
        self._performance_tracker = performance_tracker
        self._handle_results_fn = handle_results_fn

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_frame_at: str | None = None
        self.error: str | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                cap = VideoCapture(self.source)
            except RuntimeError as e:
                self.connected = False
                self.error = str(e)
                logger.error(f"[camera_worker] {e}")
                time.sleep(2)
                continue

            self.connected = True
            self.error = None

            while not self._stop_event.is_set():
                cycle_start = time.perf_counter()
                try:
                    ok, frame = cap.read()
                except Exception as e:
                    self.error = str(e)
                    logger.error(f"[camera_worker] erro na leitura do frame: {e}")
                    break

                if not ok or frame is None:
                    break

                self.last_frame_at = datetime.now().isoformat()

                try:
                    results = self._face_service.process_frame(frame, self.camera_id)
                    if "processing_time_ms" in results:
                        self._performance_tracker.record(results["processing_time_ms"])
                    self._handle_results_fn(results, self.camera_id)
                except Exception as e:
                    self.error = str(e)
                    logger.error(f"[camera_worker] falha ao processar frame: {e}")

                elapsed = time.perf_counter() - cycle_start
                remaining = self.interval_seconds - elapsed
                if remaining > 0:
                    time.sleep(remaining)

            cap.release()
            self.connected = False
            if not self._stop_event.is_set():
                time.sleep(1)

    def get_status(self) -> dict:
        return {
            "connected": self.connected,
            "last_frame_at": self.last_frame_at,
            "error": self.error,
        }
