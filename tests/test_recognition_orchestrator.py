import pytest
from datetime import datetime, timedelta
from app.services.recognition_orchestrator import RecognitionOrchestrator, RecognitionAction

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
