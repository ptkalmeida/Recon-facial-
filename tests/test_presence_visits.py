"""Presença como visita: uma entrada, "visto por último" atualizado, uma saída.

Antes, "presente" dependia da idade do registro de ENTRADA: quem ficava parado
diante da câmera virava "ausente" depois do timeout (60 s) e ganhava uma
"entrada" nova — o dashboard piscava presente/ausente e o relatório tinha uma
entrada por minuto, sem nenhuma saída.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from app.database.db import DatabaseManager, PresenceRecord


@pytest.fixture
def banco(tmp_path):
    manager = DatabaseManager(str(tmp_path / "presenca.db"))
    yield manager
    manager.engine.dispose()


@pytest.fixture
def pessoa(banco):
    return banco.create_user(name="Pessoa Presenca", email=None)


def _envelhecer(banco, registro_id, segundos, campo="last_seen"):
    with banco.session() as s:
        r = s.get(PresenceRecord, registro_id)
        setattr(r, campo, datetime.now() - timedelta(seconds=segundos))


def _registros(banco, user_id):
    return sorted(banco.get_presence_records(user_id=user_id), key=lambda r: r.id)


def test_primeira_deteccao_abre_a_visita(banco, pessoa):
    visita = banco.mark_seen(pessoa.id, "cam-1")

    assert visita.status == "entrada"
    assert visita.check_in is not None and visita.last_seen is not None
    assert visita.check_out is None


def test_deteccoes_seguidas_atualizam_a_mesma_visita(banco, pessoa):
    primeira = banco.mark_seen(pessoa.id, "cam-1")
    _envelhecer(banco, primeira.id, 30)          # visto há 30 s (timeout: 60 s)
    segunda = banco.mark_seen(pessoa.id, "cam-1")

    assert segunda.id == primeira.id
    assert len(_registros(banco, pessoa.id)) == 1
    assert (datetime.now() - segunda.last_seen).total_seconds() < 5


def test_quem_fica_parado_continua_presente(banco, pessoa):
    """O pisca-pisca: entrada antiga, mas visto agora = presente."""
    visita = banco.mark_seen(pessoa.id, "cam-1")
    _envelhecer(banco, visita.id, 3600, campo="created_at")   # entrou há 1 hora
    _envelhecer(banco, visita.id, 3600, campo="check_in")
    banco.mark_seen(pessoa.id, "cam-1")                        # e continua ali

    presenca = {p["user"]["id"]: p for p in banco.get_current_presence()}

    assert presenca[pessoa.id]["status"] == "presente"
    assert len(_registros(banco, pessoa.id)) == 1


def test_volta_depois_do_timeout_encerra_e_abre_outra(banco, pessoa):
    primeira = banco.mark_seen(pessoa.id, "cam-1")
    _envelhecer(banco, primeira.id, 120)
    segunda = banco.mark_seen(pessoa.id, "cam-1")

    antiga, nova = _registros(banco, pessoa.id)
    assert segunda.id != primeira.id
    assert antiga.status == "saida"
    assert antiga.check_out == antiga.last_seen       # saiu quando foi visto por último
    assert nova.status == "entrada"


def test_ausente_depois_do_timeout(banco, pessoa):
    visita = banco.mark_seen(pessoa.id, "cam-1")
    _envelhecer(banco, visita.id, 120)

    presenca = {p["user"]["id"]: p for p in banco.get_current_presence()}

    assert presenca[pessoa.id]["status"] == "ausente"


def test_encerramento_periodico_grava_a_saida(banco, pessoa):
    visita = banco.mark_seen(pessoa.id, "cam-1")
    _envelhecer(banco, visita.id, 120)

    assert banco.close_stale_presence() == 1
    (registro,) = _registros(banco, pessoa.id)
    assert registro.status == "saida"
    assert registro.check_out is not None
    assert banco.close_stale_presence() == 0      # idempotente


def test_registro_antigo_sem_last_seen_nao_e_reescrito(banco, pessoa):
    """Eventos de entrada do formato antigo não ganham saída inventada."""
    legado = banco.log_presence(user_id=pessoa.id, status="entrada")
    _envelhecer(banco, legado.id, 3600, campo="created_at")

    assert banco.close_stale_presence() == 0
    banco.mark_seen(pessoa.id, "cam-1")

    antigo = next(r for r in _registros(banco, pessoa.id) if r.id == legado.id)
    assert antigo.status == "entrada" and antigo.check_out is None


def test_migracao_adiciona_coluna_em_banco_existente(tmp_path):
    """Banco criado antes da coluna last_seen: ganha a coluna e mantém os dados."""
    caminho = tmp_path / "antigo.db"
    conn = sqlite3.connect(caminho)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE,
            email VARCHAR(255), role VARCHAR(50), is_active BOOLEAN,
            created_at DATETIME, updated_at DATETIME);
        CREATE TABLE presence_records (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            status VARCHAR(50) NOT NULL, check_in DATETIME, check_out DATETIME,
            camera_source VARCHAR(255), created_at DATETIME);
        INSERT INTO users (id, name, is_active) VALUES (1, 'Antiga', 1);
        INSERT INTO presence_records (user_id, status, created_at)
            VALUES (1, 'entrada', '2026-01-01 08:00:00');
    """)
    conn.close()

    for _ in range(2):  # idempotente: o segundo boot não tenta adicionar de novo
        manager = DatabaseManager(str(caminho))
        manager.engine.dispose()

    conn = sqlite3.connect(caminho)
    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(presence_records)")}
    linhas = conn.execute("SELECT status, last_seen FROM presence_records").fetchall()
    conn.close()
    assert "last_seen" in colunas
    assert linhas == [("entrada", None)]
