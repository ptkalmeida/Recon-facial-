"""Falha do modelo não pode virar "ninguém no frame".

Antes, uma exceção do InsightFace em `detect_faces` fazia a detecção cair em
silêncio para o Haar cascade; o rosto do Haar não tem embedding, e o frame
terminava como "nenhum reconhecido" - sem sinal algum no /api/health. No
cadastro, a falha virava 500 e deixava o usuário criado sem rosto.
"""

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.database.db import db_manager
from app.security.auth import create_access_token
from app.services.face_recognition import (
    INFERENCE_FAILURES_DEGRADED_AFTER,
    FaceInferenceError,
    FaceRecognitionService,
)
from main import app

FRAME = np.zeros((32, 32, 3), dtype=np.uint8)


class _ModeloQueFalha:
    def get(self, frame):
        raise RuntimeError("onnxruntime: sessão corrompida")


class _ModeloQueFunciona:
    def get(self, frame):
        return []


class _HaarEspiao:
    chamado = False

    def detectMultiScale(self, *a, **k):
        _HaarEspiao.chamado = True
        return []


def _service(modelo) -> FaceRecognitionService:
    s = FaceRecognitionService({"face_recognition": {}})
    s._insightface_app = modelo
    s.face_cascade = _HaarEspiao()
    _HaarEspiao.chamado = False
    return s


def test_falha_do_modelo_e_reportada_e_nao_cai_para_o_haar():
    service = _service(_ModeloQueFalha())

    resultado = service.process_frame(FRAME, "cam")

    assert resultado["error"] == "inference_failed"
    assert resultado["detections"] == []
    assert not _HaarEspiao.chamado
    assert service.consecutive_inference_failures == 1


def test_falhas_seguidas_marcam_o_servico_e_um_sucesso_zera():
    service = _service(_ModeloQueFalha())
    for _ in range(INFERENCE_FAILURES_DEGRADED_AFTER):
        service.process_frame(FRAME, "cam")
    assert service.get_backend_info()["inference_failing"] is True

    service._insightface_app = _ModeloQueFunciona()
    resultado = service.process_frame(FRAME, "cam")

    assert "error" not in resultado
    assert service.consecutive_inference_failures == 0
    assert service.get_backend_info()["inference_failing"] is False


def test_detect_faces_propaga_a_falha():
    service = _service(_ModeloQueFalha())
    try:
        service.detect_faces(FRAME)
    except FaceInferenceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("falha do modelo foi engolida")


def test_health_degrada_com_falhas_seguidas_sem_expor_o_erro(monkeypatch):
    monkeypatch.setattr(api_routes.face_service, "consecutive_inference_failures",
                        INFERENCE_FAILURES_DEGRADED_AFTER)

    dados = TestClient(app).get("/api/health").json()

    assert dados["status"] == "degraded"
    assert dados["recognition"]["inference_failing"] is True
    assert "onnxruntime" not in str(dados)


def test_cadastro_com_falha_do_modelo_responde_503_e_nao_deixa_usuario(monkeypatch):
    def detectar(_img):
        raise FaceInferenceError("InsightFace detection error: boom")

    monkeypatch.setattr(api_routes.face_service, "detect_faces", detectar)
    ok, jpeg = cv2.imencode(".jpg", np.full((64, 64, 3), 127, np.uint8))
    token = create_access_token({"sub": "admin", "id": 0, "role": "admin"})

    r = TestClient(app).post(
        "/api/users_register",
        data={"name": "Pessoa Falha Modelo"},
        files=[("images", ("f.jpg", jpeg.tobytes(), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.140"},
    )

    assert r.status_code == 503
    assert db_manager.get_user_by_name("Pessoa Falha Modelo") is None
