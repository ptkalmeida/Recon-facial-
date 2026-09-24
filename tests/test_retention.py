"""Retenção em lotes: desligada por padrão, e nunca apaga alerta pendente.

Sem retenção nenhuma, access_logs crescia para sempre. O prazo de guarda de
log de acesso e presença é decisão de quem opera (auditoria, LGPD), então o
padrão continua sendo guardar tudo; só o outbox de alertas tem prazo padrão.
"""

from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.database.db import AccessLog, AlertEvent, DatabaseManager, PresenceRecord


@pytest.fixture
def banco(tmp_path):
    manager = DatabaseManager(str(tmp_path / "retencao.db"))
    yield manager
    manager.engine.dispose()


def _envelhecer(banco, modelo, dias):
    with banco.session() as s:
        for linha in s.query(modelo):
            linha.created_at = datetime.now() - timedelta(days=dias)


def test_padroes_guardam_logs_e_presenca_para_sempre():
    assert settings.retention_access_log_days == 0
    assert settings.retention_presence_days == 0


def test_prazo_zero_nao_apaga_nada(banco):
    banco.log_access(user_id=None, action="antigo")
    _envelhecer(banco, AccessLog, 3650)

    assert banco.purge_expired() == {"access_logs": 0, "presence_records": 0, "alert_events": 0}
    assert len(banco.get_access_logs()) == 1


def test_apaga_so_o_que_passou_do_prazo_em_lotes(banco, monkeypatch):
    monkeypatch.setattr(DatabaseManager, "RETENTION_BATCH", 7)  # força vários lotes
    for i in range(20):
        banco.log_access(user_id=None, action=f"velho-{i}")
    _envelhecer(banco, AccessLog, 200)
    banco.log_access(user_id=None, action="recente")

    apagados = banco.purge_expired(access_log_days=180)

    assert apagados["access_logs"] == 20
    assert [l.action for l in banco.get_access_logs()] == ["recente"]


def test_presenca_tem_prazo_proprio(banco):
    user = banco.create_user(name="Pessoa Retencao", email=None)
    banco.log_presence(user_id=user.id, status="entrada")
    _envelhecer(banco, PresenceRecord, 100)
    banco.log_access(user_id=None, action="log")
    _envelhecer(banco, AccessLog, 100)

    apagados = banco.purge_expired(presence_days=90)

    assert apagados == {"access_logs": 0, "presence_records": 1, "alert_events": 0}


def test_alerta_pendente_nunca_e_apagado(banco):
    banco.enqueue_alert("unknown_detected", {"camera_id": "cam"}, ["email", "webhook"])
    ids = [e.id for e in banco.get_alert_events()]
    banco.record_alert_attempt(ids[0], None, None)                       # entregue
    banco.record_alert_attempt(ids[1], "falhou", datetime.now() + timedelta(minutes=5))  # vai tentar de novo
    _envelhecer(banco, AlertEvent, 365)

    apagados = banco.purge_expired(alert_days=90)

    assert apagados["alert_events"] == 1
    (restante,) = banco.get_alert_events()
    assert restante.id == ids[1] and restante.status == "failed"
