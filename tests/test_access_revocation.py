"""Excluir ou desativar uma pessoa revoga o reconhecimento na hora.

Antes: excluir não recarregava os rostos em memória (a pessoa seguia sendo
reconhecida e abrindo a porta até reiniciar o servidor), e desativar não
revogava nunca — os embeddings eram carregados sem filtrar `is_active`, então o
rosto voltava até depois de um restart. Num controle de acesso, é o funcionário
desligado que continua entrando.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.database.db import db_manager
from app.security.auth import create_access_token
from main import app

client = TestClient(app)


def _headers(ip: str) -> dict:
    token = create_access_token({"sub": "admin", "id": 0, "role": "admin"})
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": ip}


def _vetor(semente: int) -> list[float]:
    v = np.random.default_rng(semente).normal(size=16).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def pessoa():
    """Pessoa cadastrada com embedding, carregada no reconhecimento."""
    criados = []

    def criar(nome: str, semente: int):
        user = db_manager.create_user(name=nome, email=None, role="user")
        db_manager.add_embedding(user_id=user.id, embedding_data=_vetor(semente), is_primary=True)
        criados.append(user.id)
        api_routes._reload_known_faces()
        return user, np.array(_vetor(semente), dtype=np.float32)

    yield criar
    for user_id in criados:
        db_manager.delete_user(user_id)
    api_routes._reload_known_faces()


def _reconhecido(embedding) -> int | None:
    user_id, _conf, _tipo = api_routes.face_service.verify_face(embedding)
    return user_id


def test_excluir_revoga_na_hora(pessoa):
    user, emb = pessoa("Pessoa Excluida", 1)
    assert _reconhecido(emb) == user.id

    r = client.delete(f"/api/users/{user.id}", headers=_headers("203.0.113.120"))

    assert r.status_code == 200
    assert _reconhecido(emb) is None


def test_desativar_revoga_e_reativar_devolve(pessoa):
    user, emb = pessoa("Pessoa Desativada", 2)
    assert _reconhecido(emb) == user.id

    r = client.put(f"/api/users/{user.id}", json={"is_active": False},
                   headers=_headers("203.0.113.121"))
    assert r.status_code == 200
    assert _reconhecido(emb) is None

    r = client.put(f"/api/users/{user.id}", json={"is_active": True},
                   headers=_headers("203.0.113.122"))
    assert r.status_code == 200
    assert _reconhecido(emb) == user.id


def test_desativado_nao_volta_depois_de_reiniciar(pessoa):
    """O carregamento do boot (main.py) também não pode trazer o inativo."""
    user, _emb = pessoa("Pessoa Inativa", 3)
    db_manager.update_user(user.id, is_active=False)

    ids_carregados = {d["user_id"] for d in db_manager.get_all_embeddings_data()}

    assert user.id not in ids_carregados
