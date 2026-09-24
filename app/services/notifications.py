"""Canais de entrega de alerta.

Cada canal tem `name`, `configured` e `deliver(alert)`. `deliver` LANÇA exceção
quando a entrega falha: quem decide tentar de novo é o dispatcher do outbox
(app/services/alerts.py), não o canal. Para acrescentar um canal (Telegram,
Teams...), basta uma classe com essa forma registrada em `build_channels()`.
"""

import hashlib
import hmac
import json
import logging
import smtplib
import time
import urllib.error
import urllib.request
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

#: Quanto da resposta de erro de um webhook é lido e guardado. Um servidor
#: hostil ou quebrado respondendo 100 MB não pode esgotar a memória nem encher a
#: coluna last_error.
WEBHOOK_ERROR_READ_BYTES = 4096
WEBHOOK_ERROR_KEEP_CHARS = 200

_TITULOS = {
    "unknown_detected": "Pessoa desconhecida detectada",
    "camera_offline": "Câmera fora do ar",
    "camera_online": "Câmera de volta",
}


def describe_alert(alert: dict) -> tuple[str, str]:
    """Assunto e corpo legíveis para humanos (e-mail)."""
    tipo = alert.get("event_type", "")
    dados = alert.get("payload", {}) or {}
    titulo = _TITULOS.get(tipo, tipo)
    camera = dados.get("camera_id") or "webcam"

    linhas = [f"{titulo}.", "", f"Câmera: {camera}"]
    if tipo == "unknown_detected":
        conf = dados.get("confidence")
        linhas.append(f"Confiança: {conf:.2f}" if isinstance(conf, (int, float)) else "Confiança: N/A")
        if dados.get("faces"):
            linhas.append(f"Rostos desconhecidos no frame: {dados['faces']}")
    if tipo == "camera_online" and dados.get("offline_seconds") is not None:
        linhas.append(f"Tempo fora do ar: {int(dados['offline_seconds'])} s")
    linhas.append(f"Horário: {dados.get('occurred_at', 'N/A')}")
    return f"[Face Recognition] {titulo} ({camera})", "\n".join(linhas) + "\n"


class EmailChannel:
    """E-mail via SMTP com STARTTLS."""

    name = "email"

    def __init__(self, config: dict):
        self.smtp_host = config.get("smtp_host", "")
        self.smtp_port = config.get("smtp_port", 587)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        self.smtp_from = config.get("smtp_from", "")
        self.alert_email_to = config.get("alert_email_to", "")

    @property
    def configured(self) -> bool:
        return bool(self.smtp_host and self.alert_email_to)

    def deliver(self, alert: dict) -> None:
        assunto, corpo = describe_alert(alert)
        message = MIMEText(corpo, "plain", "utf-8")
        message["Subject"] = assunto
        message["From"] = self.smtp_from or self.smtp_user
        message["To"] = self.alert_email_to

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.starttls()
            if self.smtp_user:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(message["From"], [self.alert_email_to], message.as_string())
        logger.info("Alerta %s enviado por e-mail", alert.get("event_type"))


def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    """Assinatura do webhook: HMAC-SHA256 de "<timestamp>.<corpo>".

    O timestamp entra na assinatura para o receptor poder recusar replay:
    reenviar uma mensagem capturada exige mudar o timestamp, o que invalida a
    assinatura.
    """
    mensagem = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), mensagem, hashlib.sha256).hexdigest()


class WebhookChannel:
    """POST JSON para uma URL, assinado quando há segredo."""

    name = "webhook"

    def __init__(self, url: str, secret: str = "", timeout: float = 10.0):
        self.url = url
        self.secret = secret
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def deliver(self, alert: dict) -> None:
        body = json.dumps(alert, default=str, ensure_ascii=False).encode("utf-8")
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Timestamp": timestamp}
        if self.secret:
            headers["X-Signature"] = sign_webhook(self.secret, timestamp, body)

        requisicao = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                if 200 <= resposta.status < 300:
                    return  # sucesso: o corpo nem é lido
                trecho = resposta.read(WEBHOOK_ERROR_READ_BYTES)
                raise RuntimeError(f"http {resposta.status}: {_trecho(trecho)}")
        except urllib.error.HTTPError as e:
            trecho = e.read(WEBHOOK_ERROR_READ_BYTES) if e.fp else b""
            raise RuntimeError(f"http {e.code}: {_trecho(trecho)}") from None


def _trecho(dados: bytes) -> str:
    return dados.decode("utf-8", errors="replace")[:WEBHOOK_ERROR_KEEP_CHARS]


def build_channels(alerts_config: dict) -> list:
    """Canais configurados a partir de settings_dict["alerts"]."""
    canais = [
        EmailChannel(alerts_config),
        WebhookChannel(
            alerts_config.get("webhook_url", ""),
            alerts_config.get("webhook_secret", ""),
        ),
    ]
    return [c for c in canais if c.configured]
