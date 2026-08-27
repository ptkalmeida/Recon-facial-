import numpy as np

from app.services.face_recognition import FaceDetection, FaceRecognitionService


def _service():
    return FaceRecognitionService({})


def _detection(w, h):
    return FaceDetection(confidence=0.9, x=0, y=0, w=w, h=h)


def test_low_quality_flat_image_is_rejected():
    service = _service()
    # Uniform gray frame: zero sharpness/contrast -> should fail quality.
    frame = np.full((200, 200, 3), 128, dtype=np.uint8)
    quality = service.assess_face_quality(frame, _detection(100, 100))

    assert not quality.is_good_quality


def test_dark_image_is_rejected():
    service = _service()
    frame = np.full((200, 200, 3), 5, dtype=np.uint8)  # near-black
    quality = service.assess_face_quality(frame, _detection(100, 100))

    assert quality.brightness < 40
    assert not quality.is_good_quality


def test_textured_well_lit_image_passes():
    service = _service()
    rng = np.random.default_rng(42)
    # Same per-pixel noise replicated across all 3 channels, so the grayscale
    # conversion (a weighted average of channels) doesn't cancel out the
    # variance the way independent per-channel noise would.
    gray_noise = rng.integers(60, 200, size=(200, 200), dtype=np.uint8)
    frame = np.repeat(gray_noise[:, :, np.newaxis], 3, axis=2)
    quality = service.assess_face_quality(frame, _detection(150, 150))

    assert quality.is_good_quality


def test_extract_embedding_returns_none_for_low_quality_face():
    service = _service()
    frame = np.full((200, 200, 3), 128, dtype=np.uint8)
    embedding = service.extract_embedding(frame, _detection(100, 100))

    assert embedding is None
