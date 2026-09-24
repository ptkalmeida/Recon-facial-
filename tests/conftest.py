"""Configuração compartilhada da suíte."""

import atexit
import os
import shutil
import tempfile

import pytest

# Banco, salt e log dos testes numa pasta temporária, definidos ANTES de qualquer
# import da aplicação (o `db_manager` é criado no import de app.database.db).
# Sem isto a suíte escrevia no banco real em data/ — um teste cria e apaga um
# usuário com e-mail malicioso de propósito, e uma interrupção no meio deixava
# esse registro no banco de produção. Atribuição direta, não setdefault: nem um
# DATABASE_PATH de produção exportado no shell pode levar os testes para lá.
_DIR_TESTES = tempfile.mkdtemp(prefix="face-recognition-testes-")
os.environ["DATABASE_PATH"] = os.path.join(_DIR_TESTES, "teste.db")
os.environ["LOG_FILE"] = os.path.join(_DIR_TESTES, "teste.log")
# SQLite e o log ficam abertos até o fim do processo no Windows; o que não der
# para apagar agora fica para a limpeza de temporários do sistema.
atexit.register(shutil.rmtree, _DIR_TESTES, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def _confia_no_peer_do_testclient():
    """Faz `X-Forwarded-For` valer dentro dos testes.

    `get_client_ip()` só honra cabeçalhos de proxy quando a conexão vem de um
    peer listado em TRUSTED_PROXIES — sem isso, qualquer cliente furaria o rate
    limit trocando o cabeçalho a cada tentativa.

    Vários testes usam `X-Forwarded-For` para dar a cada caso um IP próprio e não
    disputar a mesma cota do rate limiter. O peer do TestClient do FastAPI é a
    string "testclient", então declaramos esse peer como confiável APENAS aqui.
    Em produção o valor padrão continua vazio.

    O import é feito aqui dentro (e não no topo) porque este conftest também é
    carregado pela suíte de navegador, que roda num venv só com Playwright, sem
    as dependências da aplicação.
    """
    try:
        from app.config import settings
    except ImportError:
        yield  # suíte de navegador: nada a configurar
        return

    original = settings.trusted_proxies
    settings.trusted_proxies = "testclient"
    yield
    settings.trusted_proxies = original
