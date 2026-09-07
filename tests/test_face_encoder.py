"""Wiring between image loading and the face encoder.

The detector is mocked so these run without the 280 MB model pack; what is
under test is that the encoder reads files correctly and hands the right array
to detection — the seam where a real bug slipped through once because nothing
exercised it.
"""

from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from face.detector import DetectedFace, FaceDetectionError
from face.encoder import FaceEncoder
from utils.imaging import MAX_DETECTION_EDGE, load_image


def fake_face(size=100):
    return DetectedFace(
        bbox=(0, 0, size, size),
        det_score=0.9,
        embedding=np.ones(512, dtype=np.float32) / np.sqrt(512),
    )


@pytest.fixture()
def encoder():
    detector = Mock()
    detector.detect.return_value = [fake_face()]
    detector.detect_primary.return_value = (fake_face(), 1)
    return FaceEncoder(detector)


def write_image(tmp_path, name, shape=(60, 40)):
    image = np.full((*shape, 3), 128, dtype=np.uint8)
    path = tmp_path / name
    assert cv2.imwrite(str(path), image)
    return path


@pytest.mark.parametrize("name", ["a.jpg", "a.jpeg", "a.JPEG", "a.png", "a.webp"])
def test_encode_file_accepts_every_supported_spelling(encoder, tmp_path, name):
    face, count = encoder.encode_file(write_image(tmp_path, name))
    assert count == 1
    assert face.embedding.shape == (512,)


def test_encode_file_expands_a_tilde_path(encoder, tmp_path, monkeypatch):
    write_image(tmp_path, "home.jpg")
    monkeypatch.setenv("HOME", str(tmp_path))
    face, _ = encoder.encode_file("~/home.jpg")
    assert face is not None


def test_encode_file_reports_a_missing_file_as_a_face_error(encoder, tmp_path):
    with pytest.raises(FaceDetectionError, match="Image not found"):
        encoder.encode_file(tmp_path / "absent.jpg")


def test_encode_file_reports_a_non_image_as_a_face_error(encoder, tmp_path):
    (tmp_path / "text.jpg").write_bytes(b"definitely not an image")
    with pytest.raises(FaceDetectionError, match="not a recognised image"):
        encoder.encode_file(tmp_path / "text.jpg")


def test_encode_loaded_passes_the_image_through_to_detection(encoder, tmp_path):
    loaded = load_image(write_image(tmp_path, "x.jpg"))
    encoder.encode_loaded(loaded)

    passed = encoder.detector.detect_primary.call_args[0][0]
    assert passed.shape == loaded.bgr.shape


def test_encode_loaded_downscales_a_very_large_image(encoder, tmp_path):
    path = tmp_path / "huge.png"
    cv2.imwrite(str(path), np.zeros((MAX_DETECTION_EDGE + 600, 200, 3), dtype=np.uint8))

    encoder.encode_loaded(load_image(path))
    passed = encoder.detector.detect_primary.call_args[0][0]
    assert max(passed.shape[:2]) == MAX_DETECTION_EDGE


def test_encode_file_and_encode_loaded_agree(encoder, tmp_path):
    """encode_file must be exactly encode_loaded over a freshly read file."""
    path = write_image(tmp_path, "same.jpg")
    encoder.encode_file(path)
    from_file = encoder.detector.detect_primary.call_args[0][0]

    encoder.encode_loaded(load_image(path))
    from_loaded = encoder.detector.detect_primary.call_args[0][0]

    assert np.array_equal(from_file, from_loaded)


def test_encode_bytes_returns_none_for_non_image_data(encoder):
    assert encoder.encode_bytes(b"not an image") is None
    assert encoder.encode_bytes(b"") is None


def test_encode_bytes_returns_none_when_no_face_is_found(encoder, tmp_path):
    encoder.detector.detect.return_value = []
    data = write_image(tmp_path, "x.jpg").read_bytes()
    assert encoder.encode_bytes(data) is None


def test_encode_bytes_returns_the_primary_face(encoder, tmp_path):
    data = write_image(tmp_path, "x.jpg").read_bytes()
    assert encoder.encode_bytes(data).embedding.shape == (512,)
