from app.services.camera_worker import resolve_camera_source


def test_empty_source_is_disabled():
    assert resolve_camera_source("") is None
    assert resolve_camera_source(None) is None
    assert resolve_camera_source("   ") is None


def test_digit_source_becomes_webcam_index():
    assert resolve_camera_source("0") == 0
    assert resolve_camera_source("2") == 2


def test_rtsp_url_passes_through_as_string():
    url = "rtsp://user:pass@192.168.1.10:554/stream1"
    assert resolve_camera_source(url) == url


def test_file_path_passes_through_as_string():
    path = "C:/videos/camera1.mp4"
    assert resolve_camera_source(path) == path
