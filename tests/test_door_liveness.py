"""A porta física não pode abrir sem sinal de vivacidade.

`check_liveness()` sempre existiu, e `is_live` sempre viajou na resposta de
`/api/recognition/detect` — mas nada consumia esse campo. A porta abria apenas
por `match_confidence > 0.8`, então uma foto impressa que produzisse match
confiante abria a porta com o resultado do anti-spoofing descartado.
"""

import pytest

from app.api import routes as api_routes


@pytest.fixture
def porta_espiada(monkeypatch):
    """Substitui o door_manager e registra as aberturas."""
    aberturas = []
    monkeypatch.setattr(
        api_routes.door_manager, "open_door",
        lambda duration=5: aberturas.append(duration),
    )
    return aberturas


@pytest.fixture
def sem_efeitos_colaterais(monkeypatch):
    """Neutraliza presença/e-mail; o foco do teste é só a porta."""
    logs = []
    monkeypatch.setattr(api_routes.db_manager, "get_current_presence", lambda: [])
    monkeypatch.setattr(api_routes.db_manager, "log_presence",
                        lambda **kw: logs.append(("presence", kw)))
    monkeypatch.setattr(api_routes.db_manager, "log_access",
                        lambda **kw: logs.append(("access", kw)))
    monkeypatch.setattr(api_routes.email_notifier, "notify_unknown_detected",
                        lambda *a, **k: None)
    # Orquestrador confirma de imediato, para não precisar de 3 frames.
    monkeypatch.setattr(api_routes.orchestrator, "handle_recognition",
                        lambda *a, **k: [api_routes.RecognitionAction.LOG_ACCESS])
    return logs


def _deteccao(confidence: float, is_live: bool) -> dict:
    return {
        "detections": [{
            "user_id": 7,
            "user_name": "Pessoa Teste",
            "match_confidence": confidence,
            "is_live": is_live,
        }]
    }


def test_abre_com_confianca_alta_e_vivacidade(porta_espiada, sem_efeitos_colaterais):
    api_routes.handle_detection_results(_deteccao(0.95, True), "cam1")

    assert porta_espiada == [5], "pessoa viva e reconhecida deve abrir a porta"


def test_nao_abre_sem_vivacidade_mesmo_com_confianca_altissima(
    porta_espiada, sem_efeitos_colaterais
):
    api_routes.handle_detection_results(_deteccao(0.99, False), "cam1")

    assert porta_espiada == [], (
        "sem sinal de vivacidade a porta NÃO pode abrir, por mais confiante que "
        "seja o match — é o caso da foto impressa"
    )


def test_bloqueio_por_vivacidade_gera_trilha_de_auditoria(
    porta_espiada, sem_efeitos_colaterais
):
    api_routes.handle_detection_results(_deteccao(0.99, False), "cam1")

    bloqueios = [
        kw for tipo, kw in sem_efeitos_colaterais
        if tipo == "access" and kw.get("action") == "door_blocked_no_liveness"
    ]
    assert len(bloqueios) == 1, "a tentativa bloqueada precisa ficar registrada"
    assert bloqueios[0]["status"] == "blocked"


def test_nao_abre_com_confianca_baixa(porta_espiada, sem_efeitos_colaterais):
    api_routes.handle_detection_results(_deteccao(0.5, True), "cam1")

    assert porta_espiada == []


def test_exigencia_de_vivacidade_e_configuravel(
    porta_espiada, sem_efeitos_colaterais, monkeypatch
):
    """Instalações sem hardware sensível podem desligar a exigência."""
    monkeypatch.setattr(api_routes, "REQUIRE_LIVENESS_FOR_DOOR", False)

    api_routes.handle_detection_results(_deteccao(0.99, False), "cam1")

    assert porta_espiada == [5]


def test_limiar_da_porta_e_configuravel(
    porta_espiada, sem_efeitos_colaterais, monkeypatch
):
    monkeypatch.setattr(api_routes, "DOOR_OPEN_MIN_CONFIDENCE", 0.4)

    api_routes.handle_detection_results(_deteccao(0.5, True), "cam1")

    assert porta_espiada == [5]
