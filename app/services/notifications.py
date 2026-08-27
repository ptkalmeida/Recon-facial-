import logging
import smtplib
import threading
import time
from datetime import datetime
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends email alerts for security-relevant events, with per-camera cooldown."""

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.smtp_host = config.get("smtp_host", "")
        self.smtp_port = config.get("smtp_port", 587)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        self.smtp_from = config.get("smtp_from", "")
        self.alert_email_to = config.get("alert_email_to", "")
        self.cooldown_seconds = config.get("cooldown_seconds", 600)

        self._last_alert: dict[str, float] = {}
        self._lock = threading.Lock()

    def _should_send(self, camera_id: str) -> bool:
        now = time.time()
        with self._lock:
            last = self._last_alert.get(camera_id)
            if last is not None and (now - last) < self.cooldown_seconds:
                return False
            self._last_alert[camera_id] = now
            return True

    def notify_unknown_detected(self, camera_id: str | None, confidence: float | None = None) -> None:
        """Send (or skip, if within cooldown) an alert about an unknown face detection."""
        if not self.enabled:
            return

        if not self.smtp_host or not self.alert_email_to:
            logger.warning("Alertas habilitados, mas SMTP_HOST ou ALERT_EMAIL_TO não configurados")
            return

        camera_label = camera_id or "webcam"

        if not self._should_send(camera_label):
            return

        try:
            self._send_email(camera_label, confidence)
        except Exception as e:
            logger.error(f"Falha ao enviar alerta de e-mail: {e}")

    def _send_email(self, camera_label: str, confidence: float | None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        confidence_text = f"{confidence:.2f}" if confidence is not None else "N/A"

        body = (
            f"Pessoa desconhecida detectada.\n\n"
            f"Câmera: {camera_label}\n"
            f"Confiança: {confidence_text}\n"
            f"Horário: {timestamp}\n"
        )

        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = f"[Face Recognition] Desconhecido detectado ({camera_label})"
        message["From"] = self.smtp_from or self.smtp_user
        message["To"] = self.alert_email_to

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.starttls()
            if self.smtp_user:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(message["From"], [self.alert_email_to], message.as_string())

        logger.info(f"Alerta de desconhecido enviado por e-mail (câmera: {camera_label})")
