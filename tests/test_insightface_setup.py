"""O InsightFace carrega só o que o serviço usa, com o limiar configurado.

- Sem `allowed_modules`, o pacote buffalo_l rodava 5 modelos por rosto em cada
  frame (incluindo landmark 2D/3D e gênero/idade, descartados): 609 ms contra
  355 ms por frame medidos em CPU, com o mesmo embedding.
- `detector_threshold` do config.yaml não era lido: valia o padrão do
  InsightFace (0,5), e caixas de baixa confiança viravam "rostos".
"""

from pathlib import Path

import pytest

from app.services import face_recognition as fr
from app.services.face_recognition import INSIGHTFACE_MODULES, FaceRecognitionService


class _FaceAnalysisFalso:
    criado_com: dict = {}
    preparado_com: dict = {}

    def __init__(self, **kwargs):
        _FaceAnalysisFalso.criado_com = kwargs

    def prepare(self, **kwargs):
        _FaceAnalysisFalso.preparado_com = kwargs


def test_carrega_so_deteccao_e_reconhecimento_com_o_limiar_da_config(monkeypatch):
    monkeypatch.setattr(fr, "HAS_INSIGHTFACE", True)
    monkeypatch.setattr(fr, "FaceAnalysis", _FaceAnalysisFalso, raising=False)
    service = FaceRecognitionService({"face_recognition": {"detector_threshold": 0.7}})

    assert service.initialize()

    assert _FaceAnalysisFalso.criado_com["allowed_modules"] == ["detection", "recognition"]
    assert _FaceAnalysisFalso.preparado_com["det_thresh"] == 0.7


def test_valor_do_config_yaml_chega_ao_servico():
    from app.api.routes import face_service
    from app.config import settings

    assert face_service.detector_threshold == settings.face_detector_threshold


FOTO = Path(__file__).resolve().parent.parent / "images" / "foto1.jpeg"


@pytest.mark.skipif(not FOTO.exists(), reason="foto de validação local ausente")
def test_modelo_real_com_modulos_reduzidos_gera_embedding():
    """Com o modelo de verdade: detecção + embedding normalizado continuam saindo."""
    pytest.importorskip("insightface")
    import cv2
    import numpy as np
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", allowed_modules=INSIGHTFACE_MODULES)
    app.prepare(ctx_id=0, det_size=(640, 640))
    faces = app.get(cv2.imread(str(FOTO)))

    assert sorted(app.models) == sorted(INSIGHTFACE_MODULES)
    assert faces and faces[0].normed_embedding.shape == (512,)
    assert np.isclose(np.linalg.norm(faces[0].normed_embedding), 1.0, atol=1e-3)
