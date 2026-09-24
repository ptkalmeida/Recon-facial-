"""Histerese de identidade: entra com match estrito, mantém numa faixa mais larga.

Com um limiar único (0,4), um frame de perfil ou borrado de quem está parado
diante da câmera caía para "desconhecido": a presença piscava e surgiam alertas
de desconhecido para pessoa cadastrada. A faixa [0,4; 0,55) agora mantém a
identidade - com travas: mesma pessoa, mesma câmera, poucos segundos depois de
um match estrito, sem se renovar sozinha, e nunca abrindo a porta.
"""

import numpy as np
import pytest

from app.api import routes as api_routes
from app.services.face_recognition import FaceRecognitionService

E0 = np.eye(8, dtype=np.float32)[0]
E1 = np.eye(8, dtype=np.float32)[1]


def _a_distancia(d: float) -> np.ndarray:
    """Vetor unitário a distância de cosseno `d` de E0."""
    c = 1.0 - d
    return (c * E0 + np.sqrt(1.0 - c * c) * E1).astype(np.float32)


@pytest.fixture
def service():
    s = FaceRecognitionService({"face_recognition": {
        "threshold": 0.4, "hold_threshold": 0.55, "hold_seconds": 3.0,
    }})
    s.load_known_faces([{"user_id": 7, "user_name": "Ana", "embedding_data": E0.tolist()}])
    return s


def test_sem_match_estrito_antes_nao_ha_histerese(service):
    assert service.verify_face(_a_distancia(0.5), "cam1")[0] is None


def test_mantem_na_mesma_camera_depois_do_match_estrito(service):
    user, conf, tipo = service.verify_face(_a_distancia(0.2), "cam1")
    assert (user, tipo) == (7, "known") and conf > 0

    user, conf, tipo = service.verify_face(_a_distancia(0.5), "cam1")
    assert (user, conf, tipo) == (7, 0.0, FaceRecognitionService.HELD_MATCH)


def test_outra_camera_nao_herda(service):
    service.verify_face(_a_distancia(0.2), "cam1")
    assert service.verify_face(_a_distancia(0.5), "cam2")[0] is None


def test_acima_da_faixa_continua_desconhecido(service):
    service.verify_face(_a_distancia(0.2), "cam1")
    assert service.verify_face(_a_distancia(0.6), "cam1")[0] is None


def test_prazo_expira(service):
    service.verify_face(_a_distancia(0.2), "cam1")
    service._identity_hold[("cam1", 7)] -= 10  # match estrito há 10 s (prazo: 3 s)

    assert service.verify_face(_a_distancia(0.5), "cam1")[0] is None


def test_frame_mantido_nao_renova_o_prazo(service):
    """Uma sequência de matches fracos não pode se sustentar indefinidamente."""
    service.verify_face(_a_distancia(0.2), "cam1")
    service._identity_hold[("cam1", 7)] -= 2.5
    marca = service._identity_hold[("cam1", 7)]

    assert service.verify_face(_a_distancia(0.5), "cam1")[2] == FaceRecognitionService.HELD_MATCH
    assert service._identity_hold[("cam1", 7)] == marca

    service._identity_hold[("cam1", 7)] -= 1.0  # agora 3,5 s desde o estrito
    assert service.verify_face(_a_distancia(0.5), "cam1")[0] is None


def test_sem_camera_comportamento_antigo(service):
    service.verify_face(_a_distancia(0.2))
    assert service.verify_face(_a_distancia(0.5))[0] is None


def test_porta_nunca_abre_por_histerese(monkeypatch):
    """Mesmo que a confiança viesse alta, match "held" não aciona a porta."""
    aberturas, logs = [], []
    monkeypatch.setattr(api_routes.orchestrator, "handle_recognition",
                        lambda *a, **k: [api_routes.RecognitionAction.LOG_ACCESS])
    monkeypatch.setattr(api_routes.db_manager, "log_access", lambda **kw: logs.append(kw))
    monkeypatch.setattr(api_routes.db_manager, "mark_seen", lambda **kw: None)
    monkeypatch.setattr(api_routes.door_manager, "open_door",
                        lambda duration=5: aberturas.append(duration))

    deteccao = {"user_id": 7, "user_name": "Ana", "match_confidence": 0.99,
                "match_type": FaceRecognitionService.HELD_MATCH, "is_live": True}
    api_routes.handle_detection_results({"detections": [deteccao]}, "cam1")

    assert aberturas == []
    assert logs[0]["details"] == {"match_type": FaceRecognitionService.HELD_MATCH}


def test_match_estrito_continua_abrindo_a_porta(monkeypatch):
    aberturas = []
    monkeypatch.setattr(api_routes.orchestrator, "handle_recognition",
                        lambda *a, **k: [api_routes.RecognitionAction.LOG_ACCESS])
    monkeypatch.setattr(api_routes.db_manager, "log_access", lambda **kw: None)
    monkeypatch.setattr(api_routes.db_manager, "mark_seen", lambda **kw: None)
    monkeypatch.setattr(api_routes.door_manager, "open_door",
                        lambda duration=5: aberturas.append(duration))

    deteccao = {"user_id": 7, "user_name": "Ana", "match_confidence": 0.99,
                "match_type": "known", "is_live": True}
    api_routes.handle_detection_results({"detections": [deteccao]}, "cam1")

    assert aberturas == [5]
