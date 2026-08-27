import time

from app.api import routes as api_routes
from app.services.recognition_orchestrator import RecognitionAction


def _known_detection(user_id=1, user_name="Alice", confidence=0.95):
    return {
        "user_id": user_id,
        "user_name": user_name,
        "match_confidence": confidence,
    }


def _unknown_detection(confidence=0.2):
    return {
        "user_id": None,
        "user_name": "Desconhecido",
        "match_confidence": confidence,
    }


def test_known_high_confidence_logs_access_presence_and_opens_door(monkeypatch):
    calls = {"log_access": [], "log_presence": [], "open_door": []}

    monkeypatch.setattr(
        api_routes.orchestrator,
        "handle_recognition",
        lambda user_id, camera_id: [RecognitionAction.LOG_ACCESS],
    )
    monkeypatch.setattr(
        api_routes.db_manager, "log_access", lambda **kw: calls["log_access"].append(kw)
    )
    monkeypatch.setattr(
        api_routes.db_manager, "log_presence", lambda **kw: calls["log_presence"].append(kw)
    )
    monkeypatch.setattr(api_routes.db_manager, "get_current_presence", list)
    monkeypatch.setattr(
        api_routes.door_manager, "open_door", lambda duration: calls["open_door"].append(duration)
    )

    results = {"detections": [_known_detection(confidence=0.95)]}
    api_routes.handle_detection_results(results, "cam-1")

    assert len(calls["log_access"]) == 1
    assert calls["log_access"][0]["action"] == "recognition"
    assert len(calls["log_presence"]) == 1
    assert calls["log_presence"][0]["status"] == "entrada"
    assert calls["open_door"] == [5]


def test_known_low_confidence_does_not_open_door(monkeypatch):
    calls = {"open_door": []}

    monkeypatch.setattr(
        api_routes.orchestrator,
        "handle_recognition",
        lambda user_id, camera_id: [RecognitionAction.LOG_ACCESS],
    )
    monkeypatch.setattr(api_routes.db_manager, "log_access", lambda **kw: None)
    monkeypatch.setattr(api_routes.db_manager, "log_presence", lambda **kw: None)
    monkeypatch.setattr(api_routes.db_manager, "get_current_presence", list)
    monkeypatch.setattr(
        api_routes.door_manager, "open_door", lambda duration: calls["open_door"].append(duration)
    )

    results = {"detections": [_known_detection(confidence=0.5)]}
    api_routes.handle_detection_results(results, "cam-1")

    assert calls["open_door"] == []


def test_no_actions_from_orchestrator_skips_logging(monkeypatch):
    calls = {"log_access": []}

    monkeypatch.setattr(api_routes.orchestrator, "handle_recognition", lambda user_id, camera_id: [])
    monkeypatch.setattr(
        api_routes.db_manager, "log_access", lambda **kw: calls["log_access"].append(kw)
    )

    results = {"detections": [_known_detection()]}
    api_routes.handle_detection_results(results, "cam-1")

    assert calls["log_access"] == []


def test_unknown_detection_logs_and_notifies(monkeypatch):
    calls = {"log_access": [], "notify": []}

    monkeypatch.setattr(
        api_routes.db_manager, "log_access", lambda **kw: calls["log_access"].append(kw)
    )
    monkeypatch.setattr(
        api_routes.email_notifier,
        "notify_unknown_detected",
        lambda camera_id, confidence: calls["notify"].append((camera_id, confidence)),
    )

    results = {"detections": [_unknown_detection(confidence=0.3)]}
    api_routes.handle_detection_results(results, "cam-1")

    assert len(calls["log_access"]) == 1
    assert calls["log_access"][0]["action"] == "unknown_detected"

    # notify_unknown_detected runs in a background thread; wait briefly for it.
    deadline = time.monotonic() + 2
    while not calls["notify"] and time.monotonic() < deadline:
        time.sleep(0.02)

    assert calls["notify"] == [("cam-1", 0.3)]
