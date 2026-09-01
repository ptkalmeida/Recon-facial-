"""O logging tem de honrar a configuração e escrever em disco.

`main.py` chamava `logging.basicConfig(level=logging.INFO, format=...)`: o nível
era fixo (LOG_LEVEL não tinha efeito) e não havia handler de arquivo, então
LOG_FILE, LOG_MAX_SIZE_MB e LOG_BACKUP_COUNT eram configuração morta e a
aplicação nunca deixava log em disco — num controle de acesso, o log operacional
se perdia ao fechar o console.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from app.config import settings
from main import setup_logging


@pytest.fixture
def logging_isolado():
    """Preserva e restaura a configuração real do logging."""
    raiz = logging.getLogger()
    handlers_originais = list(raiz.handlers)
    nivel_original = raiz.level
    yield
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        if isinstance(h, RotatingFileHandler):
            h.close()
    for h in handlers_originais:
        raiz.addHandler(h)
    raiz.setLevel(nivel_original)


def test_escreve_no_arquivo_configurado(tmp_path, monkeypatch, logging_isolado):
    destino = tmp_path / "sub" / "app.log"
    monkeypatch.setattr(settings, "log_file", str(destino))

    setup_logging()
    logging.getLogger("teste").warning("mensagem de prova")
    for h in logging.getLogger().handlers:
        h.flush()

    assert destino.exists(), "o diretório deve ser criado e o arquivo aberto"
    assert "mensagem de prova" in destino.read_text(encoding="utf-8")


def test_nivel_vem_da_configuracao(tmp_path, monkeypatch, logging_isolado):
    monkeypatch.setattr(settings, "log_file", str(tmp_path / "app.log"))
    monkeypatch.setattr(settings, "log_level", "WARNING")

    setup_logging()

    assert logging.getLogger().level == logging.WARNING


def test_nivel_invalido_nao_derruba_a_aplicacao(tmp_path, monkeypatch, logging_isolado):
    monkeypatch.setattr(settings, "log_file", str(tmp_path / "app.log"))
    monkeypatch.setattr(settings, "log_level", "NAO_EXISTE")

    setup_logging()

    assert logging.getLogger().level == logging.INFO


def test_rotacao_usa_os_valores_configurados(tmp_path, monkeypatch, logging_isolado):
    monkeypatch.setattr(settings, "log_file", str(tmp_path / "app.log"))
    monkeypatch.setattr(settings, "log_max_size_mb", 3)
    monkeypatch.setattr(settings, "log_backup_count", 7)

    setup_logging()
    rotativos = [h for h in logging.getLogger().handlers
                 if isinstance(h, RotatingFileHandler)]

    assert len(rotativos) == 1
    assert rotativos[0].maxBytes == 3 * 1024 * 1024
    assert rotativos[0].backupCount == 7


def test_mantem_o_console_junto_do_arquivo(tmp_path, monkeypatch, logging_isolado):
    monkeypatch.setattr(settings, "log_file", str(tmp_path / "app.log"))

    setup_logging()
    handlers = logging.getLogger().handlers

    assert any(isinstance(h, RotatingFileHandler) for h in handlers)
    assert any(type(h) is logging.StreamHandler for h in handlers)


def test_caminho_invalido_nao_impede_o_boot(monkeypatch, logging_isolado):
    """Sem permissão/disco, seguir só com console é melhor que não subir."""
    monkeypatch.setattr(settings, "log_file", "\x00caminho/invalido.log")

    setup_logging()  # não deve levantar

    assert any(type(h) is logging.StreamHandler
               for h in logging.getLogger().handlers)
