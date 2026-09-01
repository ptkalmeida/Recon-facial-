"""Configuração compartilhada da suíte."""

import pytest


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
