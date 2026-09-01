"""O sistema tem de dizer qual backend de reconhecimento está REALMENTE em uso.

`self.model_name`/`self.detector_backend` são o que o config.yaml *pede*. Se a
biblioteca correspondente não estiver instalada, `initialize()` cai num fallback
e devolve True do mesmo jeito — então `/api/health` anunciava
`active_provider: "Facenet512"` enquanto rodava Haar cascade e embeddings de
histograma (`_extract_hog_features`), que não identificam ninguém.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.config import settings_dict
from app.services.face_recognition import FaceRecognitionService
from main import app

client = TestClient(app)


@pytest.fixture
def service():
    return FaceRecognitionService(settings_dict)


def _sem_bibliotecas_de_reconhecimento(monkeypatch):
    """Simula o ambiente sem insightface/deepface/dlib/mediapipe."""
    import app.services.face_recognition as fr
    for flag in ("HAS_INSIGHTFACE", "HAS_DEEPFACE", "HAS_FACE_RECOGNITION", "HAS_MEDIAPIPE"):
        monkeypatch.setattr(fr, flag, False)


def test_fallback_hog_e_reportado_como_degradado(service, monkeypatch):
    _sem_bibliotecas_de_reconhecimento(monkeypatch)

    assert service.initialize() is True  # sobe, mas degradado
    info = service.get_backend_info()

    assert service.recognition_degraded is True
    assert info["detection_backend"] == "opencv-haar"
    assert info["embedding_backend"] == FaceRecognitionService.HOG_EMBEDDING_BACKEND
    # O configurado continua visível, para deixar a divergência explícita.
    assert info["configured_model"] == "Facenet512"
    assert info["degraded"] is True


def test_backend_reportado_nao_e_o_configurado_quando_ha_fallback(service, monkeypatch):
    _sem_bibliotecas_de_reconhecimento(monkeypatch)
    service.initialize()

    assert "Facenet512" not in service.get_backend_info()["embedding_backend"], (
        "não pode anunciar o modelo configurado quando ele não está em uso"
    )


def test_deepface_disponivel_nao_e_degradado(service, monkeypatch):
    """Com DeepFace presente, os embeddings vêm do modelo — não é degradado."""
    import app.services.face_recognition as fr
    monkeypatch.setattr(fr, "HAS_INSIGHTFACE", False)
    monkeypatch.setattr(fr, "HAS_DEEPFACE", True)
    monkeypatch.setattr(fr, "DeepFace", type("FakeDeepFace", (), {
        "detectFace": staticmethod(lambda *a, **k: None),
    }), raising=False)

    service.initialize()

    assert service.recognition_degraded is False
    assert service.get_backend_info()["embedding_backend"] == "deepface:Facenet512"


def test_mediapipe_detecta_mas_embedding_ainda_e_hog(service, monkeypatch):
    """MediaPipe só detecta: o embedding continua caindo em HOG."""
    import app.services.face_recognition as fr
    for flag in ("HAS_INSIGHTFACE", "HAS_DEEPFACE", "HAS_FACE_RECOGNITION"):
        monkeypatch.setattr(fr, flag, False)
    monkeypatch.setattr(fr, "HAS_MEDIAPIPE", True)

    fake_detection = type("FakeFD", (), {})()
    monkeypatch.setattr(fr, "mp", type("FakeMp", (), {
        "solutions": type("S", (), {
            "face_detection": type("FD", (), {
                "FaceDetection": staticmethod(lambda **kw: fake_detection)
            })
        })
    }), raising=False)

    service.initialize()

    assert service.get_backend_info()["detection_backend"] == "mediapipe"
    assert service.recognition_degraded is True, (
        "detecção por MediaPipe não implica embedding com valor biométrico"
    )


def test_health_expoe_backend_real_e_degrada(monkeypatch):
    monkeypatch.setattr(
        api_routes.face_service, "embedding_backend",
        FaceRecognitionService.HOG_EMBEDDING_BACKEND,
    )
    monkeypatch.setattr(api_routes.face_service, "detection_backend", "opencv-haar")

    data = client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.80"}).json()

    assert data["status"] == "degraded"
    assert data["active_provider"] == FaceRecognitionService.HOG_EMBEDDING_BACKEND
    assert data["recognition"]["degraded"] is True
    assert "não é confiável" in data["recognition"]["warning"]


def test_health_sem_degradacao_nao_traz_aviso(monkeypatch):
    monkeypatch.setattr(
        api_routes.face_service, "embedding_backend", "deepface:Facenet512")
    monkeypatch.setattr(
        api_routes.face_service, "detection_backend", "deepface:retinaface")
    monkeypatch.setitem(api_routes.service_status, "model_ready", True)

    data = client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.81"}).json()

    assert data["recognition"]["degraded"] is False
    assert "warning" not in data["recognition"]
    assert data["active_provider"] == "deepface:Facenet512"
