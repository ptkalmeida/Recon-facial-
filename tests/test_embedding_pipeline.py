"""Regressões do caminho de extração de embedding.

Contexto: com InsightFace instalado e ativo, `extract_embedding()` chamava
`.get()` sobre o RECORTE do rosto. O detector não acha rosto num recorte onde o
rosto ocupa quase todo o quadro (verificado com fotos reais: 1 rosto no frame
completo, 0 no recorte), então o embedding caía silenciosamente no fallback de
histograma — o sistema rodava com o modelo instalado e ainda assim comparava
intensidade de pixel.
"""

import numpy as np
import pytest

import app.services.face_recognition as fr
from app.services.face_recognition import FaceDetection, FaceRecognitionService

FRAME = np.full((480, 640, 3), 128, dtype=np.uint8)
DETECTION = FaceDetection(confidence=0.99, x=200, y=150, w=200, h=200)


class FakeFace:
    """Imita o objeto Face do InsightFace."""

    def __init__(self, bbox, embedding, det_score=0.99):
        self.bbox = bbox
        self.normed_embedding = embedding
        self.det_score = det_score


class FakeInsightApp:
    """Registra em que imagem o `.get()` foi chamado."""

    def __init__(self, faces):
        self._faces = faces
        self.called_with_shapes = []

    def get(self, img):
        self.called_with_shapes.append(img.shape)
        return self._faces


@pytest.fixture
def service(monkeypatch):
    from app.config import settings_dict
    svc = FaceRecognitionService(settings_dict)
    # Sem outros backends, para isolar o caminho testado.
    for flag in ("HAS_DEEPFACE", "HAS_FACE_RECOGNITION", "HAS_MEDIAPIPE"):
        monkeypatch.setattr(fr, flag, False)
    return svc


def _unit_vector(seed: int, dim: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def test_detect_faces_carrega_o_embedding_junto(service):
    emb = _unit_vector(1)
    service._insightface_app = FakeInsightApp([FakeFace([200, 150, 400, 350], emb)])

    detections = service.detect_faces(FRAME)

    assert len(detections) == 1
    assert detections[0].embedding is not None
    np.testing.assert_allclose(detections[0].embedding, emb, rtol=1e-6)


def test_extract_embedding_reaproveita_sem_rodar_o_modelo_de_novo(service):
    emb = _unit_vector(2)
    app_fake = FakeInsightApp([])          # devolveria vazio se fosse chamado
    service._insightface_app = app_fake
    detection = FaceDetection(0.99, 200, 150, 200, 200, embedding=emb)

    resultado = service.extract_embedding(FRAME, detection, skip_quality_check=True)

    np.testing.assert_allclose(resultado, emb, rtol=1e-6)
    assert app_fake.called_with_shapes == [], "não deveria rodar o modelo outra vez"


def test_sem_embedding_pre_calculado_roda_no_frame_inteiro_nao_no_recorte(service):
    """A regressão em si: nunca chamar o detector sobre o recorte."""
    emb = _unit_vector(3)
    app_fake = FakeInsightApp([FakeFace([200, 150, 400, 350], emb)])
    service._insightface_app = app_fake

    resultado = service.extract_embedding(FRAME, DETECTION, skip_quality_check=True)

    np.testing.assert_allclose(resultado, emb, rtol=1e-6)
    assert app_fake.called_with_shapes == [FRAME.shape], (
        f"esperado rodar no frame {FRAME.shape}, rodou em {app_fake.called_with_shapes}"
    )


def test_escolhe_o_rosto_de_maior_sobreposicao(service):
    """Com vários rostos no frame, pega o que corresponde à detecção pedida."""
    correto, outro = _unit_vector(4), _unit_vector(5)
    service._insightface_app = FakeInsightApp([
        FakeFace([10, 10, 60, 60], outro),          # longe da detecção
        FakeFace([205, 155, 395, 345], correto),    # sobrepõe DETECTION
    ])

    resultado = service.extract_embedding(FRAME, DETECTION, skip_quality_check=True)

    np.testing.assert_allclose(resultado, correto, rtol=1e-6)


def test_recusa_embedding_de_histograma_por_padrao(service):
    """Sem backend real, é melhor recusar o rosto que fingir identidade."""
    service._insightface_app = None
    assert service.allow_insecure_hog_embeddings is False

    assert service.extract_embedding(FRAME, DETECTION, skip_quality_check=True) is None


def test_histograma_so_com_opt_in_explicito(service):
    service._insightface_app = None
    service.allow_insecure_hog_embeddings = True

    resultado = service.extract_embedding(FRAME, DETECTION, skip_quality_check=True)

    assert resultado is not None, "com opt-in, o comportamento antigo volta"
    assert resultado.shape[0] != 512, "não é embedding de modelo, é histograma"


def test_nitidez_minima_vem_da_configuracao():
    """O limiar era 100 fixo no código e recusava foto de webcam utilizável."""
    from app.config import settings_dict

    padrao = FaceRecognitionService(settings_dict)
    assert padrao.min_sharpness == 40.0

    # Acima da nitidez de ruído puro (~1e5), para o caso estrito reprovar mesmo.
    config_estrita = {**settings_dict,
                      "face_recognition": {**settings_dict["face_recognition"],
                                           "min_sharpness": 1e6}}
    estrito = FaceRecognitionService(config_estrita)
    assert estrito.min_sharpness == 1e6

    # Ruído forte = nitidez alta: passa no limiar padrão, reprova no estrito.
    rng = np.random.default_rng(7)
    ruido = rng.integers(0, 255, size=(480, 640, 1), dtype=np.uint8).repeat(3, axis=2)

    # `assert not x` em vez de `is False`: assess_face_quality devolve np.bool_,
    # e `np.False_ is False` é falso.
    assert padrao.assess_face_quality(ruido, DETECTION).is_good_quality
    assert not estrito.assess_face_quality(ruido, DETECTION).is_good_quality
