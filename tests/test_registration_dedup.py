"""Fotos repetidas no cadastro.

A mesma foto enviada duas vezes dava um par com distância 0: o limiar
calibrado (p95 das distâncias entre as fotos) despencava e a média do
embedding pendia para aquela foto.
"""

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.database.db import db_manager
from app.security.auth import create_access_token
from app.services.face_recognition import (
    NEAR_DUPLICATE_DISTANCE,
    FaceDetection,
    FaceRecognitionService,
    dedupe_embeddings,
    dedupe_image_bytes,
)
from main import app

DIM = 512


def _unitario(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _vizinho(base: np.ndarray, distancia: float, seed: int) -> np.ndarray:
    """Vetor unitário a exatamente `distancia` (cosseno) de `base`."""
    ruido = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    ruido -= np.dot(ruido, base) * base
    ruido /= np.linalg.norm(ruido)
    cos = 1.0 - distancia
    return (cos * base + np.sqrt(1 - cos**2) * ruido).astype(np.float32)


def _png(marca: int) -> bytes:
    """Imagem PNG (sem perda) cujo pixel [0,0] identifica a foto."""
    img = np.full((32, 32, 3), 10, np.uint8)
    img[0, 0, 0] = marca
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def modelo_falso(monkeypatch):
    """Detector/embedding falsos: a foto de marca N devolve VETORES[N]."""
    vetores: dict[int, np.ndarray] = {}
    servico = api_routes.face_service
    monkeypatch.setattr(servico, "embedding_backend", "insightface:buffalo_l")
    monkeypatch.setattr(
        servico, "detect_faces",
        lambda img: [FaceDetection(x=0, y=0, w=32, h=32, confidence=0.99)],
    )
    monkeypatch.setattr(
        servico, "extract_embedding",
        lambda img, det, *a, **k: vetores[int(img[0, 0, 0])].copy(),
    )
    criados: list[str] = []
    yield vetores, criados
    for nome in criados:
        user = db_manager.get_user_by_name(nome)
        if user:
            db_manager.delete_user(user.id)
    api_routes._reload_known_faces()


def _cadastrar(nome: str, fotos: list[bytes], ip: str):
    token = create_access_token({"sub": "admin", "id": 0, "role": "admin"})
    return TestClient(app).post(
        "/api/users_register",
        data={"name": nome},
        files=[("images", (f"f{i}.png", f, "image/png")) for i, f in enumerate(fotos)],
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": ip},
    )


# --- funções puras -------------------------------------------------------

def test_dedupe_image_bytes_remove_identicas_e_mantem_ordem():
    a, b, c = b"foto-a", b"foto-b", b"foto-c"
    unicos, descartadas = dedupe_image_bytes([a, b, a, c, b])
    assert unicos == [a, b, c]
    assert descartadas == 2


def test_dedupe_embeddings_remove_quase_iguais_e_mantem_distintos():
    base = _unitario(1)
    quase = _vizinho(base, NEAR_DUPLICATE_DISTANCE / 2, seed=2)
    distinto = _vizinho(base, 0.10, seed=3)

    mantidos, descartados = dedupe_embeddings([base, quase, distinto])

    assert descartados == 1
    assert mantidos[0] is base and mantidos[1] is distinto


def test_dedupe_embeddings_ignora_a_escala_do_vetor():
    base = _unitario(4)
    mantidos, descartados = dedupe_embeddings([base, base * 3.0])
    assert descartados == 1 and len(mantidos) == 1


def test_duplicata_derrubava_o_limiar_calibrado():
    servico = FaceRecognitionService({"face_recognition": {}})
    base = _unitario(5)
    fotos = [base, _vizinho(base, 0.20, seed=6), _vizinho(base, 0.25, seed=7)]

    sem_repeticao = servico.calibrate_threshold(fotos)
    com_repeticao = servico.calibrate_threshold(fotos + [base.copy(), base.copy()])
    limpas, _ = dedupe_embeddings(fotos + [base.copy(), base.copy()])

    assert com_repeticao < sem_repeticao  # o problema que motivou o dedupe
    assert servico.calibrate_threshold(limpas) == pytest.approx(sem_repeticao)


# --- cadastro pela API ---------------------------------------------------

def test_api_descarta_foto_enviada_duas_vezes(modelo_falso):
    vetores, criados = modelo_falso
    vetores[1] = _unitario(10)
    vetores[2] = _vizinho(vetores[1], 0.15, seed=11)
    criados.append("Pessoa Dedup Hash")

    r = _cadastrar("Pessoa Dedup Hash", [_png(1), _png(2), _png(1)], "203.0.113.150")

    assert r.status_code == 200, r.text
    assert r.json()["photos_used"] == 2
    assert r.json()["duplicate_photos_discarded"] == 1


def test_api_descarta_foto_quase_identica(modelo_falso):
    vetores, criados = modelo_falso
    vetores[3] = _unitario(12)
    vetores[4] = _vizinho(vetores[3], 0.005, seed=13)  # bytes diferentes, mesmo rosto/pose
    vetores[5] = _vizinho(vetores[3], 0.15, seed=14)
    criados.append("Pessoa Dedup Embedding")

    r = _cadastrar("Pessoa Dedup Embedding", [_png(3), _png(4), _png(5)], "203.0.113.151")

    assert r.status_code == 200, r.text
    assert r.json()["photos_used"] == 2
    assert r.json()["duplicate_photos_discarded"] == 1
