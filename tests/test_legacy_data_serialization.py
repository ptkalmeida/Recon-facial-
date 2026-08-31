"""Dados legados no banco não podem derrubar os endpoints de leitura.

Antes de `validate_person_name()` existir, `POST /api/users_register` aceitava
`name`/`email` como string livre. Uma linha assim gravada fazia
`GET /api/users` responder 500, porque `UserResponse` validava o e-mail na
saída — a aba Usuários do dashboard ficava permanentemente quebrada, sem forma
de remover o usuário problemático pela interface.
"""

import pytest
from fastapi.testclient import TestClient

from app.database.db import db_manager
from app.models.schemas import UserResponse
from app.security.auth import create_access_token
from main import app

client = TestClient(app)

MALFORMED_EMAIL = '<img src=x onerror="alert(1)">'


@pytest.fixture
def legacy_user():
    """Grava direto no banco, sem passar pela validação de entrada."""
    user = db_manager.create_user(
        name="Usuario Legado", email=MALFORMED_EMAIL, role="user"
    )
    yield user
    db_manager.delete_user(user.id)


def test_user_response_aceita_email_malformado_do_banco():
    payload = UserResponse(
        id=1, name="Usuario Legado", email=MALFORMED_EMAIL,
        role="user", is_active=True,
    )
    assert payload.email == MALFORMED_EMAIL


def test_listagem_de_usuarios_nao_quebra_com_email_malformado(legacy_user):
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': 'admin', 'role': 'admin'})}",
        "X-Forwarded-For": "203.0.113.70",
    }

    response = client.get("/api/users", headers=headers)

    assert response.status_code == 200, response.text
    assert any(u["id"] == legacy_user.id for u in response.json())


def test_detalhe_de_usuario_nao_quebra_com_email_malformado(legacy_user):
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': 'admin', 'role': 'admin'})}",
        "X-Forwarded-For": "203.0.113.71",
    }

    response = client.get(f"/api/users/{legacy_user.id}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["email"] == MALFORMED_EMAIL
