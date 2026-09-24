"""Embedding de outro modelo não é comparado em silêncio.

O cadastro gravava em `model_used` o modelo PEDIDO no config ("Facenet512"),
não o backend que gerou o vetor (InsightFace/ArcFace). E ArcFace e Facenet512
têm a mesma dimensão (512): trocar de backend fazia o sistema comparar vetores
de espaços diferentes sem erro nenhum - distâncias sem sentido.
"""

import numpy as np
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.database.db import db_manager
from app.security.auth import create_access_token
from app.services.face_recognition import FaceDetection, FaceRecognitionService
from main import app

V = np.eye(8, dtype=np.float32)[0].tolist()


def _service(backend: str) -> FaceRecognitionService:
    s = FaceRecognitionService({"face_recognition": {}})
    s.embedding_backend = backend
    return s


def test_embedding_de_outro_backend_e_ignorado_e_contado():
    s = _service("insightface:buffalo_l")
    s.load_known_faces([
        {"user_id": 1, "user_name": "A", "embedding_data": V, "model_used": "insightface:buffalo_l"},
        {"user_id": 2, "user_name": "B", "embedding_data": V, "model_used": "deepface:Facenet512"},
    ])

    assert set(s._known_embeddings) == {1}
    assert s.incompatible_embeddings == 1
    assert s.get_backend_info()["incompatible_embeddings"] == 1


def test_rotulo_antigo_sem_backend_continua_aceito():
    """Registros de antes deste campo ter valor real: origem desconhecida."""
    s = _service("insightface:buffalo_l")
    s.load_known_faces([
        {"user_id": 3, "user_name": "C", "embedding_data": V, "model_used": "Facenet512"},
        {"user_id": 4, "user_name": "D", "embedding_data": V},
    ])

    assert set(s._known_embeddings) == {3, 4}
    assert s.incompatible_embeddings == 0


def test_servico_nao_inicializado_nao_filtra():
    s = _service("não inicializado")
    s.load_known_faces([
        {"user_id": 5, "user_name": "E", "embedding_data": V, "model_used": "deepface:Facenet512"},
    ])
    assert set(s._known_embeddings) == {5}


def test_cadastro_grava_o_backend_real(monkeypatch):
    monkeypatch.setattr(api_routes.face_service, "embedding_backend", "insightface:buffalo_l")
    monkeypatch.setattr(api_routes.face_service, "detect_faces",
                        lambda img: [FaceDetection(confidence=0.9, x=0, y=0, w=10, h=10)])
    monkeypatch.setattr(api_routes.face_service, "extract_embedding",
                        lambda img, det: np.array(V, dtype=np.float32))
    import cv2
    ok, jpeg = cv2.imencode(".jpg", np.full((32, 32, 3), 127, np.uint8))
    token = create_access_token({"sub": "admin", "id": 0, "role": "admin"})

    r = TestClient(app).post(
        "/api/users_register",
        data={"name": "Pessoa Rotulo Backend"},
        files=[("images", ("f.jpg", jpeg.tobytes(), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.150"},
    )
    try:
        assert r.status_code == 200, r.text
        (emb,) = db_manager.get_embeddings(r.json()["user"]["id"])
        assert emb.model_used == "insightface:buffalo_l"
    finally:
        db_manager.delete_user(r.json()["user"]["id"])
        api_routes._reload_known_faces()
