"""Consistência de autorização: rotas sensíveis exigem papel de admin.

O achado F3 da auditoria era a divergência entre rotas de escrita (protegidas com
`require_admin`) e rotas de leitura/ação igualmente sensíveis, que aceitavam
qualquer token válido. Este teste trava o contrato: um token com
`role != "admin"` recebe 403 nessas rotas.
"""

import pytest
from fastapi.testclient import TestClient

from app.security.auth import create_access_token
from main import app

client = TestClient(app)

#: (método, caminho) das rotas que só o admin pode acessar.
ADMIN_ONLY_ROUTES = [
    ("GET", "/api/users"),
    ("GET", "/api/users/1"),
    ("PUT", "/api/users/1"),
    ("DELETE", "/api/users/1"),
    ("GET", "/api/access-logs"),
    ("GET", "/api/presence/history"),
    ("POST", "/api/export"),
    ("POST", "/api/hardware/open-door"),
]


@pytest.fixture(scope="module")
def non_admin_headers():
    token = create_access_token({"sub": "operador", "role": "user"})
    return {
        "Authorization": f"Bearer {token}",
        # IP dedicado para não competir com o rate limiter geral dos outros testes.
        "X-Forwarded-For": "203.0.113.50",
    }


@pytest.mark.parametrize("method,path", ADMIN_ONLY_ROUTES)
def test_non_admin_token_is_forbidden(method, path, non_admin_headers):
    response = client.request(method, path, headers=non_admin_headers, json={})

    assert response.status_code == 403, (
        f"{method} {path} respondeu {response.status_code}; "
        "rota sensível deveria exigir require_admin"
    )


@pytest.mark.parametrize("method,path", ADMIN_ONLY_ROUTES)
def test_missing_token_is_unauthorized(method, path):
    response = client.request(
        method, path, json={}, headers={"X-Forwarded-For": "203.0.113.51"}
    )

    assert response.status_code in (401, 403)
