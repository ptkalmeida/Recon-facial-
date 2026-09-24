"""Alertas: outbox, canais (e-mail e webhook) e alerta de câmera offline.

Os cinco cenários do notificador de e-mail anterior continuam cobertos, agora
sobre a API do outbox (o e-mail passou a ser um canal entregue pelo
dispatcher, com nova tentativa):

- desligado -> nada é enviado            (test_disabled_notifier_never_sends)
- SMTP incompleto -> canal não entra      (test_missing_smtp_config_skips_send)
- cooldown por câmera                     (test_cooldown_blocks_repeated_alert_for_same_camera)
- câmeras diferentes independentes        (test_different_cameras_are_not_throttled_together)
- falha de SMTP não levanta exceção       (test_smtp_failure_does_not_raise)
"""

import email
import email.header
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest

from app.database.db import AlertEvent, DatabaseManager
from app.services.alerts import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    AlertService,
    CameraOfflineMonitor,
)
from app.services.notifications import (
    WEBHOOK_ERROR_KEEP_CHARS,
    EmailChannel,
    WebhookChannel,
    build_channels,
    sign_webhook,
)


def _config(**overrides):
    base = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "alerts@example.com",
        "smtp_password": "secret",
        "smtp_from": "alerts@example.com",
        "alert_email_to": "security@example.com",
        "cooldown_seconds": 600,
    }
    base.update(overrides)
    return base


@pytest.fixture
def banco(tmp_path):
    manager = DatabaseManager(str(tmp_path / "alertas.db"))
    yield manager
    manager.engine.dispose()


def _servico(banco, config=None, **kw):
    config = config or _config()
    return AlertService(banco, build_channels(config), enabled=config["enabled"],
                        cooldown_seconds=config["cooldown_seconds"], **kw)


def _smtp_ok():
    servidor = MagicMock()
    servidor.__enter__.return_value = servidor
    return servidor


def _todos(banco):
    with banco.session() as s:
        return s.query(AlertEvent).order_by(AlertEvent.id).all()


# --- os cinco cenários do notificador anterior -----------------------------

def test_disabled_notifier_never_sends(banco):
    servico = _servico(banco, _config(enabled=False))
    with patch("smtplib.SMTP") as mock_smtp:
        assert servico.emit("unknown_detected", {"camera_id": "camera-1"}, "camera-1") is False
        servico.dispatch_due()
        mock_smtp.assert_not_called()
    assert _todos(banco) == []


def test_missing_smtp_config_skips_send(banco):
    servico = _servico(banco, _config(smtp_host=""))
    assert servico.channel_names == []
    with patch("smtplib.SMTP") as mock_smtp:
        assert servico.emit("unknown_detected", {"camera_id": "camera-1"}, "camera-1") is False
        servico.dispatch_due()
        mock_smtp.assert_not_called()


def test_cooldown_blocks_repeated_alert_for_same_camera(banco):
    servico = _servico(banco)
    with patch("smtplib.SMTP", return_value=_smtp_ok()) as mock_smtp:
        servico.emit("unknown_detected", {"camera_id": "camera-1", "confidence": 0.9}, "camera-1")
        servico.emit("unknown_detected", {"camera_id": "camera-1", "confidence": 0.9}, "camera-1")
        servico.dispatch_due()
        assert mock_smtp.call_count == 1


def test_different_cameras_are_not_throttled_together(banco):
    servico = _servico(banco)
    with patch("smtplib.SMTP", return_value=_smtp_ok()) as mock_smtp:
        servico.emit("unknown_detected", {"camera_id": "camera-1", "confidence": 0.9}, "camera-1")
        servico.emit("unknown_detected", {"camera_id": "camera-2", "confidence": 0.9}, "camera-2")
        servico.dispatch_due()
        assert mock_smtp.call_count == 2


def test_smtp_failure_does_not_raise(banco):
    servico = _servico(banco)
    servico.emit("unknown_detected", {"camera_id": "camera-1", "confidence": 0.9}, "camera-1")
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        assert servico.dispatch_due() == 0   # não levanta
    (evento,) = _todos(banco)
    assert evento.status == "failed" and "connection refused" in evento.last_error


# --- outbox e nova tentativa ------------------------------------------------

def test_falha_agenda_nova_tentativa_e_depois_entrega(banco):
    servico = _servico(banco)
    servico.emit("unknown_detected", {"camera_id": "cam", "confidence": 0.5}, "cam")

    with patch("smtplib.SMTP", side_effect=OSError("smtp fora do ar")):
        servico.dispatch_due()
    (evento,) = _todos(banco)
    assert evento.attempts == 1
    espera = (evento.next_attempt_at - datetime.now()).total_seconds()
    assert BACKOFF_SECONDS[0] - 5 < espera <= BACKOFF_SECONDS[0]

    # Antes do prazo, não tenta de novo.
    with patch("smtplib.SMTP", return_value=_smtp_ok()) as mock_smtp:
        servico.dispatch_due()
        mock_smtp.assert_not_called()

    # Vencido o prazo, entrega.
    with banco.session() as s:
        s.get(AlertEvent, evento.id).next_attempt_at = datetime.now() - timedelta(seconds=1)
    with patch("smtplib.SMTP", return_value=_smtp_ok()):
        assert servico.dispatch_due() == 1
    (evento,) = _todos(banco)
    assert evento.status == "sent" and evento.attempts == 2 and evento.delivered_at


def test_desiste_apos_o_maximo_de_tentativas(banco):
    servico = _servico(banco)
    servico.emit("unknown_detected", {"camera_id": "cam"}, "cam")

    for _ in range(MAX_ATTEMPTS + 2):
        with banco.session() as s:
            for e in s.query(AlertEvent):
                if e.next_attempt_at:
                    e.next_attempt_at = datetime.now() - timedelta(seconds=1)
        with patch("smtplib.SMTP", side_effect=OSError("sempre falha")):
            servico.dispatch_due()

    (evento,) = _todos(banco)
    assert evento.attempts == MAX_ATTEMPTS
    assert evento.status == "failed" and evento.next_attempt_at is None


def test_um_canal_quebrado_nao_impede_o_outro(banco):
    class Quebrado:
        name, configured = "quebrado", True

        def deliver(self, alert):
            raise RuntimeError("boom")

    entregues = []

    class Funciona:
        name, configured = "funciona", True

        def deliver(self, alert):
            entregues.append(alert)

    servico = AlertService(banco, [Quebrado(), Funciona()], enabled=True)
    servico.emit("camera_offline", {"camera_id": "cam"})
    assert servico.dispatch_due() == 1
    assert entregues[0]["event_type"] == "camera_offline"
    assert entregues[0]["payload"]["camera_id"] == "cam"


def test_erro_guardado_sem_credencial_de_url(banco):
    class Vaza:
        name, configured = "vaza", True

        def deliver(self, alert):
            raise RuntimeError("falhou em http://usuario:senha123@hook.local/x")

    servico = AlertService(banco, [Vaza()], enabled=True)
    servico.emit("camera_offline", {"camera_id": "cam"})
    servico.dispatch_due()
    (evento,) = _todos(banco)
    assert "senha123" not in evento.last_error


# --- e-mail -----------------------------------------------------------------

def test_email_descreve_o_evento():
    canal = EmailChannel(_config())
    servidor = _smtp_ok()
    with patch("smtplib.SMTP", return_value=servidor):
        canal.deliver({"event_type": "camera_offline",
                       "payload": {"camera_id": "portaria", "occurred_at": "2026-09-24T10:00:00"}})
    mensagem = email.message_from_string(servidor.sendmail.call_args[0][2])
    corpo = mensagem.get_payload(decode=True).decode("utf-8")
    assunto = str(email.header.make_header(email.header.decode_header(mensagem["Subject"])))
    assert assunto == "[Face Recognition] Câmera fora do ar (portaria)"
    assert "Câmera: portaria" in corpo
    assert "2026-09-24T10:00:00" in corpo


# --- webhook ----------------------------------------------------------------

class _Receptor(BaseHTTPRequestHandler):
    status = 200
    corpo_resposta = b"ok"
    recebido: dict = {}

    def do_POST(self):
        tamanho = int(self.headers["Content-Length"])
        _Receptor.recebido = {"headers": dict(self.headers), "body": self.rfile.read(tamanho)}
        self.send_response(_Receptor.status)
        self.end_headers()
        self.wfile.write(_Receptor.corpo_resposta)

    def log_message(self, *a):
        pass


@pytest.fixture
def receptor():
    servidor = HTTPServer(("127.0.0.1", 0), _Receptor)
    t = threading.Thread(target=servidor.serve_forever, daemon=True)
    t.start()
    _Receptor.status, _Receptor.corpo_resposta = 200, b"ok"
    yield f"http://127.0.0.1:{servidor.server_port}/hook"
    servidor.shutdown()


def test_webhook_assinado_com_timestamp(receptor):
    WebhookChannel(receptor, secret="segredo").deliver(
        {"event_id": 1, "event_type": "unknown_detected", "payload": {"camera_id": "cam"}}
    )
    h, corpo = _Receptor.recebido["headers"], _Receptor.recebido["body"]
    assert json.loads(corpo)["payload"]["camera_id"] == "cam"
    assert h["X-Signature"] == sign_webhook("segredo", h["X-Timestamp"], corpo)
    # Mesma mensagem com outro timestamp não confere: replay é detectável.
    assert h["X-Signature"] != sign_webhook("segredo", str(int(h["X-Timestamp"]) + 1), corpo)


def test_webhook_com_erro_levanta_e_le_resposta_limitada(receptor):
    _Receptor.status, _Receptor.corpo_resposta = 500, b"x" * 100_000
    with pytest.raises(RuntimeError) as exc:
        WebhookChannel(receptor).deliver({"event_type": "t", "payload": {}})
    assert str(exc.value).startswith("http 500")
    assert len(str(exc.value)) <= WEBHOOK_ERROR_KEEP_CHARS + 20


def test_webhook_sem_url_nao_e_canal():
    assert build_channels(_config(smtp_host="", webhook_url="")) == []
    canais = build_channels(_config(smtp_host="", webhook_url="http://x/y"))
    assert [c.name for c in canais] == ["webhook"]


# --- câmera offline ---------------------------------------------------------

class _Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _AlertasEspiao:
    def __init__(self):
        self.emitidos = []

    def emit(self, event_type, payload, cooldown_key=None):
        self.emitidos.append((event_type, payload))
        return True


def test_queda_curta_nao_alerta():
    relogio, alertas = _Relogio(), _AlertasEspiao()
    monitor = CameraOfflineMonitor(alertas, threshold_seconds=60, clock=relogio)
    monitor.register("cam")
    monitor.on_status("cam", True)
    monitor.on_status("cam", False)
    relogio.t += 20
    monitor.check()
    monitor.on_status("cam", True)
    relogio.t += 100
    monitor.check()
    assert alertas.emitidos == []


def test_offline_depois_do_limite_e_online_ao_voltar():
    relogio, alertas = _Relogio(), _AlertasEspiao()
    monitor = CameraOfflineMonitor(alertas, threshold_seconds=60, clock=relogio)
    monitor.register("cam")
    monitor.on_status("cam", True)
    monitor.on_status("cam", False)
    relogio.t += 61
    monitor.check()
    monitor.check()                      # não repete durante o mesmo episódio
    relogio.t += 30
    monitor.on_status("cam", True)

    tipos = [t for t, _ in alertas.emitidos]
    assert tipos == ["camera_offline", "camera_online"]
    assert alertas.emitidos[1][1]["offline_seconds"] == 91


def test_camera_que_nunca_conecta_alerta():
    relogio, alertas = _Relogio(), _AlertasEspiao()
    monitor = CameraOfflineMonitor(alertas, threshold_seconds=60, clock=relogio)
    monitor.register("cam")
    relogio.t += 61
    monitor.check()
    assert [t for t, _ in alertas.emitidos] == ["camera_offline"]
