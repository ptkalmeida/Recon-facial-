"""A senha da câmera não pode sair em log nem em resposta da API.

URLs RTSP carregam `usuario:senha@`. Antes desta correção a URL completa ia para
o log no startup (main.py) e para a mensagem de erro do camera_worker — e essa
mensagem era devolvida por `/api/health`, que não exige autenticação. Qualquer
um na rede lia a senha da câmera com um GET.
"""

import io
import logging
import types
from logging.handlers import RotatingFileHandler

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.config import settings
from app.security.redaction import CredentialRedactionFilter, redact_url_credentials
from app.services import camera_worker as camera_worker_module
from app.services.camera_worker import CameraWorker, VideoCapture
from main import app, setup_logging

# `@` dentro da senha de propósito: um regex que para no primeiro `@` deixaria
# "Secreta" no log.
SENHA = "S3nh@Secreta"
URL = f"rtsp://admin:{SENHA}@192.168.1.10:554/stream1"


def _sem_senha(texto: str) -> bool:
    return "S3nh" not in texto and "Secreta" not in texto


# --- redact_url_credentials ------------------------------------------------

@pytest.mark.parametrize("entrada, esperado", [
    (URL, "rtsp://***@192.168.1.10:554/stream1"),
    ("rtsp://admin:senha@cam.local/live", "rtsp://***@cam.local/live"),
    ("http://usuario@cam.local/snapshot.jpg", "http://***@cam.local/snapshot.jpg"),
    (
        "a rtsp://u:p@h1/x e http://v:q@h2/y fim",
        "a rtsp://***@h1/x e http://***@h2/y fim",
    ),
])
def test_remove_credenciais_da_url(entrada, esperado):
    assert redact_url_credentials(entrada) == esperado


@pytest.mark.parametrize("entrada", [
    "rtsp://192.168.1.10:554/stream1",   # sem credencial
    "C:/videos/camera1.mp4",             # arquivo
    "0",                                 # índice de webcam
    "contato: admin@empresa.com",        # e-mail solto não é URL
])
def test_texto_sem_credencial_fica_intacto(entrada):
    assert redact_url_credentials(entrada) == entrada


def test_aceita_nao_string():
    assert redact_url_credentials(None) is None
    assert redact_url_credentials(0) == "0"
    assert _sem_senha(redact_url_credentials(RuntimeError(f"falha em {URL}")))


# --- CredentialRedactionFilter ---------------------------------------------

@pytest.fixture
def logger_com_filtro():
    """Logger isolado com um handler em memória e o filtro instalado."""
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(CredentialRedactionFilter())

    logger = logging.getLogger("teste.redacao")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, saida
    logger.handlers = []


def test_filtro_cobre_placeholder_e_fstring(logger_com_filtro):
    logger, saida = logger_com_filtro
    logger.info("fonte: %s", URL)
    logger.info(f"fonte: {URL}")
    logger.info("fonte: %(url)s", {"url": URL})

    texto = saida.getvalue()
    assert _sem_senha(texto)
    assert texto.count("rtsp://***@192.168.1.10:554/stream1") == 3


def test_filtro_cobre_traceback(logger_com_filtro):
    logger, saida = logger_com_filtro
    try:
        raise RuntimeError(f"Não foi possível abrir {URL}")
    except RuntimeError:
        logger.exception("falha na câmera")

    texto = saida.getvalue()
    assert "Traceback" in texto and "RuntimeError" in texto
    assert _sem_senha(texto)


def test_filtro_nao_quebra_quem_loga_com_args_errados(logger_com_filtro):
    """Exceção dentro de filtro sobe para o chamador de logger.info()."""
    logger, saida = logger_com_filtro
    logger.info("dois placeholders %s %s", URL)  # falta um argumento
    assert _sem_senha(saida.getvalue())
    assert "dois placeholders" in saida.getvalue()


# --- setup_logging instala o filtro em todos os destinos -------------------

@pytest.fixture
def logging_isolado():
    raiz = logging.getLogger()
    handlers_originais = list(raiz.handlers)
    nivel_original = raiz.level
    yield raiz
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        if isinstance(h, RotatingFileHandler):
            h.close()
    for h in handlers_originais:
        raiz.addHandler(h)
    raiz.setLevel(nivel_original)


def test_setup_logging_redige_no_arquivo_e_no_console(tmp_path, monkeypatch, logging_isolado):
    destino = tmp_path / "app.log"
    monkeypatch.setattr(settings, "log_file", str(destino))

    setup_logging()
    for handler in logging_isolado.handlers:
        assert any(isinstance(f, CredentialRedactionFilter) for f in handler.filters), handler

    # Registro vindo de um módulo qualquer, por propagação até a raiz.
    logging.getLogger("app.services.qualquer").warning("abrindo %s", URL)
    for handler in logging_isolado.handlers:
        handler.flush()

    conteudo = destino.read_text(encoding="utf-8")
    assert "rtsp://***@192.168.1.10" in conteudo
    assert _sem_senha(conteudo)


# --- camera_worker ---------------------------------------------------------

class _CapturaQueNaoAbre:
    def __init__(self, *args, **kwargs):
        pass

    def isOpened(self):
        return False

    def release(self):
        pass


def test_erro_de_abertura_sai_redigido(monkeypatch):
    monkeypatch.setattr(camera_worker_module.cv2, "VideoCapture", _CapturaQueNaoAbre)

    with pytest.raises(RuntimeError) as exc:
        VideoCapture(URL)

    assert _sem_senha(str(exc.value))
    assert "rtsp://***@192.168.1.10" in str(exc.value)


def test_loop_do_worker_nao_loga_nem_guarda_a_senha(monkeypatch, caplog):
    worker = CameraWorker(URL, "cam-teste", 1.0, None, None, None)

    class CapturaQueNaoAbreEPara(_CapturaQueNaoAbre):
        def __init__(self, *args, **kwargs):
            worker._stop_event.set()  # uma volta do loop basta

    monkeypatch.setattr(camera_worker_module.cv2, "VideoCapture", CapturaQueNaoAbreEPara)
    # Só o `time` deste módulo: o loop dorme 2 s depois de cada falha.
    monkeypatch.setattr(camera_worker_module, "time", types.SimpleNamespace(
        sleep=lambda _s: None,
        monotonic=camera_worker_module.time.monotonic,
        perf_counter=camera_worker_module.time.perf_counter,
    ))

    with caplog.at_level(logging.ERROR, logger="app.services.camera_worker"):
        worker._run()

    assert worker.connected is False
    assert worker.error and _sem_senha(worker.error)
    assert "Não foi possível abrir" in caplog.text
    assert _sem_senha(caplog.text)


def test_get_status_nao_expoe_texto_do_erro():
    worker = CameraWorker(URL, "cam-teste", 1.0, None, None, None)
    assert worker.get_status()["error"] is None

    worker._set_error(RuntimeError(f"timeout lendo {URL}"))
    status = worker.get_status()

    assert status["error"] == CameraWorker.PUBLIC_ERROR_MESSAGE
    assert "192.168.1.10" not in str(status)


def test_health_publico_nao_vaza_dados_da_camera(monkeypatch):
    worker = CameraWorker(URL, "cam-teste", 1.0, None, None, None)
    worker._set_error(RuntimeError(f"Não foi possível abrir a fonte de câmera: {URL}"))
    monkeypatch.setattr(api_routes, "camera_worker", worker)

    resposta = TestClient(app).get("/api/health")  # sem token

    assert resposta.status_code == 200
    assert _sem_senha(resposta.text)
    assert "192.168.1.10" not in resposta.text
    camera = resposta.json()["server_camera"]
    assert camera["enabled"] is True
    assert camera["connected"] is False
    assert camera["error"] == CameraWorker.PUBLIC_ERROR_MESSAGE
