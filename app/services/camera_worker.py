"""Optional server-side camera capture (local webcam index or RTSP/file URL).

Adapted from EPI-Detect-main/core/capture.py + server.py's threaded capture pattern.
Disabled by default (SERVER_CAMERA_ENABLED=false) — the browser-based capture flow in
app/templates/dashboard.html keeps working unchanged whether this is enabled or not.
"""

import logging
import random
import threading
import time
from datetime import datetime
from sys import platform

import cv2

from app.security.redaction import redact_url_credentials

logger = logging.getLogger(__name__)

#: Esquemas tratados como stream de rede (leitura em thread + timeouts).
NETWORK_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://", "tcp://")

#: Timeout do FFmpeg para abrir e para ler cada frame. Sem ele, uma câmera fora
#: do ar ou que parou de responder trava a leitura por tempo indeterminado.
NETWORK_TIMEOUT_MS = 10000


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


def is_network_source(source) -> bool:
    return isinstance(source, str) and source.lower().startswith(NETWORK_SCHEMES)


class VideoCapture:
    """Leitura de câmera guardando só o frame mais recente.

    Webcam e stream de rede (RTSP/HTTP) são lidos continuamente numa thread, e
    `read()` devolve o último frame. Ler direto e dormir entre leituras - como
    era feito com RTSP - deixa os frames se acumularem no buffer do decoder: a
    inferência passa a olhar o passado, com atraso que cresce sem limite.

    Arquivo local é lido direto: aí o consumidor é quem dita o ritmo (numa
    thread, o arquivo seria consumido a toda velocidade).

    `frame_seq` aumenta a cada frame novo e `last_frame_monotonic` marca quando
    ele chegou - o consumidor usa os dois para não reprocessar o mesmo frame e
    para perceber um stream que parou sem dar erro.
    """

    def __init__(self, source, width=None, height=None, fps=None):
        self.source = source
        self._is_webcam = isinstance(source, int)
        self._is_network = is_network_source(source)
        self.threaded = self._is_webcam or self._is_network
        self._cap = self._open_capture(source)

        if not self._cap.isOpened():
            # A URL RTSP carrega usuário e senha: a mensagem vai para o log e
            # para `self.error`, então sai redigida.
            raise RuntimeError(
                "Não foi possível abrir a fonte de câmera: "
                f"{redact_url_credentials(source)}"
            )

        self.frame_seq = 0
        self.last_frame_monotonic: float | None = None
        #: True quando a thread de leitura desistiu (stream caiu).
        self.failed = False

        if self.threaded:
            if self._is_webcam:
                if width:
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                if height:
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                if fps:
                    self._cap.set(cv2.CAP_PROP_FPS, fps)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._frame = None
            self._lock = threading.Lock()
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._reader, daemon=True, name="CameraReader"
            )
            self._thread.start()
            deadline = time.monotonic() + 5.0
            while self._frame is None and not self.failed and time.monotonic() < deadline:
                time.sleep(0.05)

    def _open_capture(self, source):
        if self._is_network:
            return self._open_network(source)
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

    @staticmethod
    def _open_network(source):
        abrir = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
        ler = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
        if abrir is None or ler is None:  # OpenCV antigo, sem os timeouts
            return cv2.VideoCapture(source)
        return cv2.VideoCapture(
            source, cv2.CAP_FFMPEG,
            [abrir, NETWORK_TIMEOUT_MS, ler, NETWORK_TIMEOUT_MS],
        )

    def _reader(self):
        falhas_seguidas = 0
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if ok and frame is not None:
                falhas_seguidas = 0
                with self._lock:
                    self._frame = frame
                    self.frame_seq += 1
                    self.last_frame_monotonic = time.monotonic()
                continue
            falhas_seguidas += 1
            # Stream de rede que falha seguidamente caiu: desiste e deixa o
            # CameraWorker reconectar (com backoff). Webcam tolera falhas
            # esporádicas, como antes.
            if self._is_network and falhas_seguidas >= 3:
                self.failed = True
                return
            time.sleep(0.05)

    def read(self):
        if self.threaded:
            with self._lock:
                if self._frame is None:
                    return False, None
                return not self.failed, self._frame.copy()
        ok, frame = self._cap.read()
        if ok and frame is not None:
            self.frame_seq += 1
            self.last_frame_monotonic = time.monotonic()
        return ok, frame

    def release(self):
        if self.threaded:
            self._stop.set()
            self._thread.join(timeout=2)
        self._cap.release()


class CameraWorker:
    """Continuously reads frames from a server-side camera and runs recognition.

    Reuses the same face_service/performance_tracker/handle_detection_results that
    the /api/recognition/detect HTTP route uses, so results (access logs, presence,
    door control, unknown-face alerts) are identical regardless of which capture
    path produced the frame.

    Reconexão: espera exponencial com jitter entre tentativas (1 s, 2 s, 4 s...
    até 60 s), zerada no primeiro frame recebido - com a câmera fora do ar, o
    worker não martela a rede e a CPU a cada 2 s. Um watchdog reconecta quando o
    stream para de mandar frames sem dar erro (comum em RTSP e em NVR).
    """

    # Texto fixo para quem não é admin: o detalhe do erro fica no log.
    PUBLIC_ERROR_MESSAGE = "Falha na captura da câmera; detalhes no log do servidor"

    def __init__(self, source, camera_id: str, interval_seconds: float,
                 face_service, performance_tracker, handle_results_fn,
                 backoff_base_seconds: float = 1.0, backoff_max_seconds: float = 60.0,
                 stall_timeout_seconds: float | None = None,
                 status_listener=None):
        self.source = source
        self.camera_id = camera_id
        self.interval_seconds = interval_seconds
        self._face_service = face_service
        self._performance_tracker = performance_tracker
        self._handle_results_fn = handle_results_fn
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        # Sem frame novo por este tempo, o stream é considerado travado.
        self.stall_timeout_seconds = (
            stall_timeout_seconds if stall_timeout_seconds is not None
            else max(10.0, 5 * interval_seconds)
        )
        #: Chamado com (camera_id, conectado: bool) quando a conexão muda.
        self._status_listener = status_listener

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_frame_at: str | None = None
        self.error: str | None = None
        self.reconnect_attempts = 0
        self._falhas_seguidas = 0

    def start(self):
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"CameraWorker-{self.camera_id}"
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _proxima_espera(self) -> float:
        """Backoff exponencial com jitter de ±20%."""
        base = min(
            self.backoff_base_seconds * (2 ** self._falhas_seguidas),
            self.backoff_max_seconds,
        )
        self._falhas_seguidas += 1
        return base * random.uniform(0.8, 1.2)

    def _set_connected(self, conectado: bool) -> None:
        if conectado == self.connected:
            return
        self.connected = conectado
        if self._status_listener is not None:
            try:
                self._status_listener(self.camera_id, conectado)
            except Exception as e:
                logger.error(f"[camera_worker] listener de status falhou: {e}")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                cap = VideoCapture(self.source)
            except RuntimeError as e:
                self._set_connected(False)
                self._set_error(e)
                self.reconnect_attempts += 1
                espera = self._proxima_espera()
                logger.error(f"[camera_worker] {self.error} (nova tentativa em {espera:.0f}s)")
                self._stop_event.wait(espera)
                continue

            self.error = None
            self._consumir(cap)
            cap.release()
            self._set_connected(False)
            if not self._stop_event.is_set():
                self.reconnect_attempts += 1
                self._stop_event.wait(self._proxima_espera())

    def _consumir(self, cap: VideoCapture) -> None:
        """Processa frames até o stream cair, travar ou o worker parar."""
        ultimo_seq = 0
        inicio = time.monotonic()
        while not self._stop_event.is_set():
            cycle_start = time.perf_counter()
            try:
                ok, frame = cap.read()
            except Exception as e:
                self._set_error(e)
                logger.error(f"[camera_worker] erro na leitura do frame: {self.error}")
                return

            if cap.failed or (not ok and not cap.threaded):
                return

            referencia = cap.last_frame_monotonic or inicio
            if time.monotonic() - referencia > self.stall_timeout_seconds:
                self.error = (
                    f"stream sem frames novos há mais de {self.stall_timeout_seconds:g}s"
                )
                logger.warning(f"[camera_worker] {self.error}; reconectando")
                return

            if ok and frame is not None and cap.frame_seq != ultimo_seq:
                ultimo_seq = cap.frame_seq
                self._falhas_seguidas = 0
                self._set_connected(True)
                self.last_frame_at = datetime.now().isoformat()
                try:
                    results = self._face_service.process_frame(frame, self.camera_id)
                    if "processing_time_ms" in results:
                        self._performance_tracker.record(results["processing_time_ms"])
                    self._handle_results_fn(results, self.camera_id)
                except Exception as e:
                    self._set_error(e)
                    logger.error(f"[camera_worker] falha ao processar frame: {self.error}")

            elapsed = time.perf_counter() - cycle_start
            remaining = self.interval_seconds - elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)

    def _set_error(self, exc: Exception) -> None:
        # Erros do OpenCV/FFmpeg podem repetir a URL da fonte, com a senha.
        self.error = redact_url_credentials(exc)

    def get_status(self) -> dict:
        """Estado seguro para exposição pública (usado por /api/health).

        `/api/health` não exige autenticação, então o texto do erro não sai
        daqui, nem redigido: além da URL, ele pode revelar IP interno, porta e
        caminho da câmera. A chave `error` continua existindo com o mesmo tipo
        (string ou null), para não quebrar quem só testa se há erro.
        """
        return {
            "connected": self.connected,
            "last_frame_at": self.last_frame_at,
            "error": self.PUBLIC_ERROR_MESSAGE if self.error else None,
            "reconnect_attempts": self.reconnect_attempts,
        }
