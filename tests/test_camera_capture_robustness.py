"""Captura no servidor: último frame, timeouts, backoff, watchdog e dedupe.

Antes: RTSP era lido direto e o worker dormia entre leituras (os frames se
acumulavam no buffer e a inferência olhava o passado), a reconexão era a cada
2 s fixos, e um stream que parava de mandar frames sem dar erro ficava
"conectado" para sempre.
"""

import threading
import time

import numpy as np
import pytest

from app.services import camera_worker as cw
from app.services.camera_worker import NETWORK_TIMEOUT_MS, CameraWorker, VideoCapture


class CameraFalsa:
    """Imita cv2.VideoCapture. `roteiro(n)` diz o que a n-ésima leitura faz."""

    instancias: list = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.n = 0
        self.soltou = False
        type(self).instancias.append(self)

    def isOpened(self):
        return True

    def set(self, *args):
        return True

    def release(self):
        self.soltou = True

    def read(self):
        self.n += 1
        return self.roteiro(self.n)

    @staticmethod
    def roteiro(n):
        time.sleep(0.005)
        return True, np.full((4, 4, 3), n % 256, dtype=np.uint8)


@pytest.fixture
def camera_falsa(monkeypatch):
    """Subclasse nova por teste: roteiro e instâncias não vazam entre testes."""
    class Camera(CameraFalsa):
        instancias = []
    monkeypatch.setattr(cw.cv2, "VideoCapture", Camera)
    return Camera


def _esperar(condicao, limite=3.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def test_rtsp_abre_com_timeouts_do_ffmpeg(camera_falsa):
    cap = VideoCapture("rtsp://camera.local/stream")
    try:
        args = camera_falsa.instancias[0].args
        assert args[1] == cw.cv2.CAP_FFMPEG
        assert list(args[2]).count(NETWORK_TIMEOUT_MS) == 2
    finally:
        cap.release()


def test_rtsp_entrega_o_frame_mais_recente(camera_falsa):
    cap = VideoCapture("rtsp://camera.local/stream")
    try:
        time.sleep(0.2)  # o consumidor demorou: vários frames chegaram nesse meio-tempo
        ok, frame = cap.read()
        leituras = camera_falsa.instancias[0].n
        assert ok
        assert cap.frame_seq > 5
        # É o último frame lido (ou o penúltimo, se outro chegou entre as linhas).
        assert int(frame[0, 0, 0]) in {leituras % 256, (leituras - 1) % 256}
    finally:
        cap.release()


def test_stream_que_cai_e_marcado_como_falho(camera_falsa):
    camera_falsa.roteiro = staticmethod(
        lambda n: (True, np.zeros((4, 4, 3), np.uint8)) if n <= 2 else (False, None)
    )
    cap = VideoCapture("rtsp://camera.local/stream")
    try:
        assert _esperar(lambda: cap.failed)
    finally:
        cap.release()


def test_backoff_exponencial_com_teto_e_jitter():
    worker = CameraWorker("rtsp://x/y", "cam", 1.0, None, None, None,
                          backoff_base_seconds=1.0, backoff_max_seconds=60.0)
    esperas = [worker._proxima_espera() for _ in range(9)]
    nominais = [1, 2, 4, 8, 16, 32, 60, 60, 60]
    for espera, nominal in zip(esperas, nominais):
        assert 0.8 * nominal <= espera <= 1.2 * nominal


def test_watchdog_reconecta_stream_travado(camera_falsa, caplog):
    """Um frame e depois silêncio, sem erro: o worker tem de reconectar."""
    camera_falsa.roteiro = staticmethod(lambda n: (True, np.zeros((4, 4, 3), np.uint8))
                                        if n == 1 else (time.sleep(0.05) or (False, None)))
    # Webcam (índice) tolera falha de leitura sem marcar `failed`: só o watchdog
    # percebe que parou.
    processados = []
    worker = CameraWorker(0, "cam", 0.02, _ServicoFalso(processados), _Tracker(), lambda *a: None,
                          backoff_base_seconds=0.01, stall_timeout_seconds=0.3)
    worker.start()
    try:
        assert _esperar(lambda: len(camera_falsa.instancias) >= 2, limite=4.0)
        assert camera_falsa.instancias[0].soltou  # a conexão travada foi liberada
        assert "sem frames novos há mais de 0.3s" in caplog.text
    finally:
        worker.stop()


def test_frame_repetido_nao_e_reprocessado(camera_falsa):
    """Câmera lenta (1 frame a cada 0,4 s), loop a cada 0,02 s: processa só frames novos."""
    camera_falsa.roteiro = staticmethod(
        lambda n: (time.sleep(0.4) or (True, np.full((4, 4, 3), n, np.uint8)))
    )
    processados = []
    worker = CameraWorker(0, "cam", 0.02, _ServicoFalso(processados), _Tracker(), lambda *a: None,
                          stall_timeout_seconds=5)
    worker.start()
    time.sleep(1.3)
    worker.stop()

    valores = [int(f[0, 0, 0]) for f in processados]
    assert 1 <= len(valores) <= 4
    assert len(valores) == len(set(valores))  # nenhum frame processado duas vezes


def test_listener_avisa_conexao_e_queda(camera_falsa):
    camera_falsa.roteiro = staticmethod(
        lambda n: (time.sleep(0.01) or (True, np.zeros((4, 4, 3), np.uint8))) if n <= 5
        else (False, None)
    )
    eventos = []
    worker = CameraWorker("rtsp://x/y", "cam-9", 0.01, _ServicoFalso([]), _Tracker(),
                          lambda *a: None, backoff_base_seconds=5.0,
                          status_listener=lambda cam, conectado: eventos.append((cam, conectado)))
    worker.start()
    try:
        assert _esperar(lambda: ("cam-9", False) in eventos)
        assert eventos[0] == ("cam-9", True)
        assert worker.get_status()["reconnect_attempts"] >= 1
    finally:
        worker.stop()


def test_stop_nao_espera_o_backoff(camera_falsa, monkeypatch):
    """Com 60 s de espera entre tentativas, parar o worker tem de ser imediato."""
    class NaoAbre(camera_falsa):
        def isOpened(self):
            return False
    monkeypatch.setattr(cw.cv2, "VideoCapture", NaoAbre)
    worker = CameraWorker("rtsp://x/y", "cam", 1.0, None, None, None, backoff_base_seconds=60)
    worker.start()
    assert _esperar(lambda: worker.reconnect_attempts >= 1)

    inicio = time.monotonic()
    worker.stop()
    assert time.monotonic() - inicio < 1.0


class _ServicoFalso:
    def __init__(self, destino):
        self.destino = destino
        self._lock = threading.Lock()

    def process_frame(self, frame, camera_id):
        with self._lock:
            self.destino.append(frame.copy())
        return {"detections": [], "processing_time_ms": 1.0}


class _Tracker:
    def record(self, _ms):
        pass
