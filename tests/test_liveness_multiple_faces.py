"""Com vários rostos no frame, todos são comparados com o frame anterior.

`check_liveness()` guardava o frame atual como referência a cada rosto. O
segundo rosto do mesmo frame era então comparado com o próprio frame atual:
movimento zero, `is_live=False` sempre. Com duas pessoas diante da câmera, a
segunda nunca passava na vivacidade — e a porta exige vivacidade.
"""

import numpy as np

from app.services.face_recognition import FaceDetection, FaceRecognitionService

ROSTOS = [
    FaceDetection(confidence=0.99, x=10, y=10, w=30, h=30),
    FaceDetection(confidence=0.99, x=60, y=10, w=30, h=30),
]


def _service() -> FaceRecognitionService:
    service = FaceRecognitionService({"face_recognition": {}, "anti_spoofing": {"enabled": True}})
    service.detect_faces = lambda frame: list(ROSTOS)
    service.extract_embedding = lambda frame, det, **kw: np.ones(4, dtype=np.float32)
    service.verify_face = lambda emb, camera_id=None: (None, 0.0, "unknown")
    return service


def _frame(valor_nos_rostos: int) -> np.ndarray:
    frame = np.zeros((60, 110, 3), dtype=np.uint8)
    for r in ROSTOS:
        frame[r.y:r.y + r.h, r.x:r.x + r.w] = valor_nos_rostos
    return frame


def test_os_dois_rostos_com_movimento_passam():
    service = _service()
    service.process_frame(_frame(0), "cam")           # referência
    resultado = service.process_frame(_frame(120), "cam")  # os dois rostos mudaram

    vivos = [d["is_live"] for d in resultado["detections"]]
    assert vivos == [True, True]


def test_imagem_estatica_continua_barrada_nos_dois():
    service = _service()
    service.process_frame(_frame(80), "cam")
    resultado = service.process_frame(_frame(80), "cam")  # nada mudou: foto parada

    vivos = [d["is_live"] for d in resultado["detections"]]
    assert vivos == [False, False]


def test_referencia_e_o_frame_processado_por_ultimo():
    service = _service()
    service.process_frame(_frame(0), "cam")
    service.process_frame(_frame(120), "cam")

    guardado = service._frame_history["cam"]
    assert np.array_equal(guardado, _frame(120))


def test_chamada_avulsa_continua_guardando_o_frame():
    service = _service()
    service.check_liveness(_frame(5), ROSTOS[0], "avulsa")
    assert "avulsa" in service._frame_history
