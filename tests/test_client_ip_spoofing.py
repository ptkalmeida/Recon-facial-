"""O rate limit não pode ser furado trocando cabeçalho de proxy.

`get_client_ip()` é a chave do rate limiter. Enquanto ela aceitava
`X-Forwarded-For` de qualquer origem, bastava mandar um IP diferente por
requisição para anular o limite de 5 tentativas de login: brute force sem
limite contra o único login do sistema.
"""

import pytest

from app.config import settings
from app.security.rate_limiter import RateLimiter, create_rate_limit_key, get_client_ip


class FakeRequest:
    def __init__(self, peer, headers=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = headers or {}


@pytest.fixture
def sem_proxy_confiavel(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")


@pytest.fixture
def com_proxy_confiavel(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1")


def test_ignora_forwarded_de_peer_nao_confiavel(sem_proxy_confiavel):
    req = FakeRequest("203.0.113.9", {"X-Forwarded-For": "1.2.3.4"})

    assert get_client_ip(req) == "203.0.113.9", (
        "sem proxy declarado, vale o IP real da conexão"
    )


def test_ignora_real_ip_de_peer_nao_confiavel(sem_proxy_confiavel):
    req = FakeRequest("203.0.113.9", {"X-Real-IP": "1.2.3.4"})

    assert get_client_ip(req) == "203.0.113.9"


def test_honra_forwarded_de_proxy_declarado(com_proxy_confiavel):
    req = FakeRequest("10.0.0.1", {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})

    assert get_client_ip(req) == "198.51.100.7", (
        "atrás de um proxy declarado, o IP do cliente vem do cabeçalho"
    )


def test_proxy_declarado_sem_cabecalho_usa_o_peer(com_proxy_confiavel):
    assert get_client_ip(FakeRequest("10.0.0.1")) == "10.0.0.1"


def test_sem_peer_algum(sem_proxy_confiavel):
    assert get_client_ip(FakeRequest(None)) == "unknown"


def test_rotacao_de_forwarded_nao_fura_mais_o_limite(sem_proxy_confiavel):
    """O ataque em si: um IP novo por tentativa não deve ganhar cota nova."""
    limiter = RateLimiter(max_requests=3, window_seconds=60, block_duration_seconds=60)

    resultados = []
    for i in range(6):
        req = FakeRequest("203.0.113.9", {"X-Forwarded-For": f"1.2.3.{i}"})
        chave = create_rate_limit_key("login", get_client_ip(req))
        permitido, _ = limiter.is_allowed(chave)
        resultados.append(permitido)

    assert resultados[:3] == [True, True, True]
    assert resultados[3:] == [False, False, False], (
        "todas as tentativas caem na mesma cota, apesar do cabeçalho variar"
    )
