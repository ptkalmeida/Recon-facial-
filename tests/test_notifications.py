from unittest.mock import MagicMock, patch

from app.services.notifications import EmailNotifier


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


def test_disabled_notifier_never_sends():
    notifier = EmailNotifier(_config(enabled=False))
    with patch("smtplib.SMTP") as mock_smtp:
        notifier.notify_unknown_detected("camera-1", 0.42)
        mock_smtp.assert_not_called()


def test_missing_smtp_config_skips_send():
    notifier = EmailNotifier(_config(smtp_host=""))
    with patch("smtplib.SMTP") as mock_smtp:
        notifier.notify_unknown_detected("camera-1", 0.42)
        mock_smtp.assert_not_called()


def test_cooldown_blocks_repeated_alert_for_same_camera():
    notifier = EmailNotifier(_config())
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp:
        notifier.notify_unknown_detected("camera-1", 0.9)
        notifier.notify_unknown_detected("camera-1", 0.9)
        assert mock_smtp.call_count == 1


def test_different_cameras_are_not_throttled_together():
    notifier = EmailNotifier(_config())
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp:
        notifier.notify_unknown_detected("camera-1", 0.9)
        notifier.notify_unknown_detected("camera-2", 0.9)
        assert mock_smtp.call_count == 2


def test_smtp_failure_does_not_raise():
    notifier = EmailNotifier(_config())
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        notifier.notify_unknown_detected("camera-1", 0.9)
