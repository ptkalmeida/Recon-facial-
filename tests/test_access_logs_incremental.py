from app.database.db import DatabaseManager


def _make_manager():
    return DatabaseManager(db_path=":memory:")


def test_after_id_filters_only_newer_logs():
    manager = _make_manager()
    user = manager.create_user(name="Alice")

    log1 = manager.log_access(user_id=user.id, action="recognition", status="success")
    log2 = manager.log_access(user_id=user.id, action="recognition", status="success")
    log3 = manager.log_access(user_id=user.id, action="unknown_detected", status="unknown")

    all_logs = manager.get_access_logs()
    assert len(all_logs) == 3

    newer_logs = manager.get_access_logs(after_id=log1.id)
    newer_ids = {log.id for log in newer_logs}
    assert newer_ids == {log2.id, log3.id}

    no_new_logs = manager.get_access_logs(after_id=log3.id)
    assert no_new_logs == []
