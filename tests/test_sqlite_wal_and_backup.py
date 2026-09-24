"""SQLite em WAL com busy_timeout, e backup que restaura de verdade.

- Várias threads escrevem ao mesmo tempo (requisições, câmera do servidor,
  alertas). No journal padrão, uma escrita bloqueia até as leituras e o SQLite
  desiste com "database is locked".
- O backup copiava `data/crypto_salt.bin`, que não existe, e deixava de fora o
  salt real: um backup restaurado não decifrava nenhum embedding. E, com WAL,
  copiar só o `.db` perde o que ainda está no `-wal`.
"""

import importlib.util
import sqlite3
import threading
import zipfile
from pathlib import Path

from app.config import PROJECT_ROOT
from app.database.db import SQLITE_BUSY_TIMEOUT_MS, DatabaseManager
from app.security.crypto import SALT_FILENAME


def _pragma(manager: DatabaseManager, nome: str):
    with manager.engine.connect() as conn:
        return conn.exec_driver_sql(f"PRAGMA {nome}").scalar()


def test_banco_em_arquivo_usa_wal_e_espera_o_lock(tmp_path):
    manager = DatabaseManager(str(tmp_path / "wal.db"))

    assert _pragma(manager, "journal_mode") == "wal"
    assert _pragma(manager, "busy_timeout") == SQLITE_BUSY_TIMEOUT_MS
    manager.engine.dispose()


def test_wal_pode_ser_desligado_para_pasta_de_rede(tmp_path):
    manager = DatabaseManager(str(tmp_path / "rede.db"), wal=False)

    assert _pragma(manager, "journal_mode") == "delete"
    assert _pragma(manager, "busy_timeout") == SQLITE_BUSY_TIMEOUT_MS
    manager.engine.dispose()


def test_banco_em_memoria_continua_funcionando():
    manager = DatabaseManager(":memory:")
    manager.log_access(user_id=None, action="teste")
    assert len(manager.get_access_logs()) == 1


def test_escritas_concorrentes_nao_travam(tmp_path):
    manager = DatabaseManager(str(tmp_path / "concorrente.db"))
    erros = []

    def escrever(n):
        try:
            for i in range(40):
                manager.log_access(user_id=None, action=f"t{n}-{i}")
                manager.get_access_logs(limit=5)  # leitura intercalada
        except Exception as exc:  # pragma: no cover - é o que o teste procura
            erros.append(exc)

    threads = [threading.Thread(target=escrever, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not erros, erros
    assert len(manager.get_access_logs(limit=1000)) == 200
    manager.engine.dispose()


def _modulo_backup():
    spec = importlib.util.spec_from_file_location("backup", PROJECT_ROOT / "scripts" / "backup.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_backup_inclui_salt_e_transacoes_do_wal(tmp_path):
    banco = tmp_path / "dados" / "face_recognition.db"
    manager = DatabaseManager(str(banco))
    for i in range(25):
        manager.log_access(user_id=None, action=f"antes-do-backup-{i}")
    # A conexão continua aberta no pool: as linhas estão no -wal, ainda não
    # passaram para o .db - é o caso que a cópia simples de arquivo perde.
    assert (banco.parent / "face_recognition.db-wal").exists()
    (banco.parent / SALT_FILENAME).write_bytes(b"0123456789abcdef")

    zip_path = _modulo_backup().create_backup(banco=banco, destino=tmp_path)

    with zipfile.ZipFile(zip_path) as zf:
        nomes = set(zf.namelist())
        assert f"data/{SALT_FILENAME}" in nomes
        assert zf.read(f"data/{SALT_FILENAME}") == b"0123456789abcdef"
        assert "data/face_recognition.db" in nomes
        assert not any(n.endswith(("-wal", "-shm")) for n in nomes)
        restaurado = tmp_path / "restaurado.db"
        restaurado.write_bytes(zf.read("data/face_recognition.db"))

    conn = sqlite3.connect(restaurado)
    try:
        total = conn.execute(
            "select count(*) from access_logs where action like 'antes-do-backup-%'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert total == 25
    manager.engine.dispose()
