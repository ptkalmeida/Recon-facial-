"""A inferência não pode travar o servidor.

`/recognition/detect` era `async def` e chamava o modelo (~0,9 s em CPU) direto
no event loop: durante cada frame, nenhuma outra requisição era atendida —
/api/health, o polling do dashboard e o login ficavam parados esperando.
"""

import asyncio
import threading
import time

import cv2
import httpx
import numpy as np
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.security.auth import create_access_token
from app.services.face_recognition import FaceRecognitionService
from main import app

INFERENCIA_LENTA = 1.5


def _jpeg() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


def test_health_responde_enquanto_a_deteccao_roda(monkeypatch):
    """As duas requisições no MESMO event loop, como no uvicorn.

    (O TestClient sem `with` abre um loop novo por requisição, e aí nada
    disputaria o loop - o teste passaria até com o código antigo.)
    """
    def processamento_lento(frame, camera_id="default"):
        time.sleep(INFERENCIA_LENTA)  # bloqueante, como o modelo de verdade
        return {"frame_id": 1, "faces_detected": 0, "detections": [], "processing_time_ms": 1.0}

    monkeypatch.setattr(api_routes.face_service, "process_frame", processamento_lento)
    token = create_access_token({"sub": "admin", "id": 1, "role": "admin"})

    async def cenario():
        # Peer "testclient": o conftest o declara proxy confiável, então o
        # X-Forwarded-For dá um IP próprio a este teste no rate limiter.
        transporte = httpx.ASGITransport(app=app, client=("testclient", 50000))
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as c:
            # Cronômetro desde o início do cenário: com o loop bloqueado, nem o
            # asyncio.sleep abaixo volta antes do fim da inferência, então medir
            # só a chamada do health esconderia o bloqueio.
            inicio = time.perf_counter()
            deteccao = asyncio.create_task(c.post(
                "/api/recognition/detect",
                files={"image": ("f.jpg", _jpeg(), "image/jpeg")},
                headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.90"},
            ))
            await asyncio.sleep(0.3)  # a detecção já está dentro da "inferência"

            health = await c.get("/api/health")
            decorrido = time.perf_counter() - inicio
            return health, decorrido, await deteccao

    health, decorrido, deteccao = asyncio.run(cenario())

    assert health.status_code == 200
    # Enviado em ~0,3 s: tem de voltar bem antes de a inferência (1,5 s) acabar.
    assert decorrido < 1.0, f"health esperou a inferência ({decorrido:.2f}s)"
    assert deteccao.status_code == 200


def test_imagem_invalida_continua_400():
    client = TestClient(app)
    token = create_access_token({"sub": "admin", "id": 1, "role": "admin"})
    r = client.post(
        "/api/recognition/detect",
        files={"image": ("f.jpg", b"isto nao e imagem", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.91"},
    )
    assert r.status_code == 400


def test_modelo_atende_uma_chamada_por_vez():
    """HTTP e a câmera do servidor chamam o modelo em paralelo: tem de serializar."""
    service = FaceRecognitionService({"face_recognition": {}})
    em_andamento = 0
    pico = 0
    trava = threading.Lock()

    def deteccao_instrumentada(frame):
        nonlocal em_andamento, pico
        with trava:
            em_andamento += 1
            pico = max(pico, em_andamento)
        time.sleep(0.05)
        with trava:
            em_andamento -= 1
        return []

    # Substitui só o corpo: o lock vem de process_frame, que continua o original.
    service.detect_faces = deteccao_instrumentada
    frame = np.zeros((32, 32, 3), dtype=np.uint8)

    threads = [threading.Thread(target=service.process_frame, args=(frame, f"cam{i}")) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert pico == 1
