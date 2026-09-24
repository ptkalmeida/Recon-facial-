from datetime import datetime, timedelta

from app.services.recognition_orchestrator import (
    RecognitionAction,
    RecognitionOrchestrator,
)


def test_should_only_trigger_log_after_cooldown():
    # Setup com cooldown de 5 segundos e 1 frame para log imediato
    orchestrator = RecognitionOrchestrator(cooldown_seconds=5, min_frames=1)
    user_id = 1
    camera_id = "cam1"
    
    # Primeira detecção -> Deve gerar ação de log
    actions = orchestrator.handle_recognition(user_id, camera_id)
    assert RecognitionAction.LOG_ACCESS in actions
    
    # Segunda detecção imediata -> Não deve gerar ação de log (cooldown)
    actions = orchestrator.handle_recognition(user_id, camera_id)
    assert RecognitionAction.LOG_ACCESS not in actions
    
    # Detecção após 6 segundos -> Deve gerar ação de log novamente
    orchestrator._last_recognition[user_id] = datetime.now() - timedelta(seconds=6)
    actions = orchestrator.handle_recognition(user_id, camera_id)
    assert RecognitionAction.LOG_ACCESS in actions

def test_should_only_trigger_log_after_min_frames():
    # Cooldown de 0 para isolar teste de frames
    orchestrator = RecognitionOrchestrator(
        cooldown_seconds=0, 
        min_frames=3, 
        window_seconds=2
    )
    user_id = 1
    camera_id = "cam1"
    
    # Frame 1 -> Nada
    assert RecognitionAction.LOG_ACCESS not in orchestrator.handle_recognition(user_id, camera_id)
    # Frame 2 -> Nada
    assert RecognitionAction.LOG_ACCESS not in orchestrator.handle_recognition(user_id, camera_id)
    # Frame 3 -> LOG_ACCESS
    assert RecognitionAction.LOG_ACCESS in orchestrator.handle_recognition(user_id, camera_id)


def test_confirmacao_e_por_camera():
    """Frames da mesma pessoa em câmeras diferentes não somam."""
    orchestrator = RecognitionOrchestrator(cooldown_seconds=0, min_frames=3, window_seconds=10)

    assert orchestrator.handle_recognition(1, "cam1") == []
    assert orchestrator.handle_recognition(1, "cam2") == []
    assert orchestrator.handle_recognition(1, "cam1") == []   # 2 na cam1
    assert RecognitionAction.LOG_ACCESS in orchestrator.handle_recognition(1, "cam1")


def test_desconhecido_precisa_de_confirmacao():
    orchestrator = RecognitionOrchestrator(cooldown_seconds=5, min_frames=3, window_seconds=10)

    assert orchestrator.handle_unknown("cam1") == []
    assert orchestrator.handle_unknown("cam1") == []
    assert orchestrator.handle_unknown("cam1") == [RecognitionAction.LOG_ACCESS]


def test_desconhecido_respeita_cooldown_por_camera():
    orchestrator = RecognitionOrchestrator(cooldown_seconds=5, min_frames=1, window_seconds=10)

    assert orchestrator.handle_unknown("cam1") == [RecognitionAction.LOG_ACCESS]
    assert orchestrator.handle_unknown("cam1") == []            # cooldown
    assert orchestrator.handle_unknown("cam2") == [RecognitionAction.LOG_ACCESS]

    orchestrator._last_unknown_log["cam1"] = datetime.now() - timedelta(seconds=6)
    assert orchestrator.handle_unknown("cam1") == [RecognitionAction.LOG_ACCESS]


def test_desconhecido_fora_da_janela_recomeca_a_contagem():
    orchestrator = RecognitionOrchestrator(cooldown_seconds=0, min_frames=2, window_seconds=2)

    assert orchestrator.handle_unknown("cam1") == []
    orchestrator._unknown_buckets["cam1"]["first_seen"] = datetime.now() - timedelta(seconds=3)
    assert orchestrator.handle_unknown("cam1") == []           # janela expirou: conta 1 de novo
    assert orchestrator.handle_unknown("cam1") == [RecognitionAction.LOG_ACCESS]


def test_cleanup_remove_estado_de_desconhecido_antigo():
    orchestrator = RecognitionOrchestrator(cooldown_seconds=0, min_frames=1)
    orchestrator.handle_unknown("cam1")
    velho = datetime.now() - timedelta(hours=2)
    orchestrator._unknown_buckets["cam1"]["first_seen"] = velho
    orchestrator._last_unknown_log["cam1"] = velho

    orchestrator.cleanup()

    assert orchestrator.get_metrics() == {"cache_size": 0, "buckets_size": 0}
