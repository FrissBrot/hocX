"""face_quality.py: face detection + crop scoring.

tests/fixtures/nasa_official_portrait.jpg is a real photograph of a real face (public
domain, see fixtures/ATTRIBUTION.md for provenance/license) - used below to verify actual
positive detection, not just "doesn't crash". That fixture is also what caught a real bug:
YuNet reliably found nothing at all on the original ~5200x6500px image, only after
downscaling (see face_quality.py's module docstring and _DETECTION_MAX_DIMENSION) - so
these tests double as the regression test for that fix.
"""

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.face_quality import _exposure, _sharpness, load_detector, score_face_quality

# Same env var app/worker.py reads (default matches the Dockerfile's bake-in path) - CI
# runs this on a bare runner instead of inside the built image, so it points this at
# wherever the "download the model" step put it.
MODEL_PATH = os.environ.get("PHOTO_WORKER_MODEL_PATH", "/app/models/face_detection_yunet.onnx")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _png_bytes(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


@pytest.fixture(scope="module")
def detector():
    return load_detector(MODEL_PATH)


def test_detector_loads_and_finds_no_face_in_a_blank_image(detector):
    blank = np.zeros((200, 200, 3), dtype=np.uint8)
    assert score_face_quality(detector, _png_bytes(blank)) is None


def test_detector_finds_no_face_in_random_noise(detector):
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, size=(200, 200, 3), dtype=np.uint8)
    assert score_face_quality(detector, _png_bytes(noise)) is None


def test_score_face_quality_returns_none_for_undecodable_bytes(detector):
    assert score_face_quality(detector, b"not an image") is None


def test_score_face_quality_returns_none_for_empty_bytes(detector):
    assert score_face_quality(detector, b"") is None


def test_sharpness_is_higher_for_a_sharp_crop_than_a_blurred_one():
    size = 128
    xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    checkerboard = (((xs // 4) + (ys // 4)) % 2 * 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(checkerboard, (15, 15), 0)

    assert _sharpness(checkerboard) > _sharpness(blurred)


def test_exposure_penalizes_clipped_highlights_and_shadows():
    well_exposed = np.full((64, 64), 128, dtype=np.uint8)
    blown_out = np.full((64, 64), 255, dtype=np.uint8)
    crushed_black = np.full((64, 64), 0, dtype=np.uint8)

    assert _exposure(well_exposed) == 1.0
    assert _exposure(blown_out) == 0.0
    assert _exposure(crushed_black) == 0.0


def test_score_face_quality_detects_a_real_face_and_returns_a_positive_score(detector):
    image_bytes = (FIXTURES_DIR / "nasa_official_portrait.jpg").read_bytes()

    score = score_face_quality(detector, image_bytes)

    assert score is not None
    assert score > 0


def test_score_face_quality_is_lower_for_a_blurred_copy_of_the_same_real_photo(detector):
    array = np.frombuffer((FIXTURES_DIR / "nasa_official_portrait.jpg").read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    blurred = cv2.GaussianBlur(image, (25, 25), 0)
    ok, buffer = cv2.imencode(".jpg", blurred)
    assert ok

    sharp_score = score_face_quality(detector, cv2.imencode(".jpg", image)[1].tobytes())
    blurred_score = score_face_quality(detector, buffer.tobytes())

    assert sharp_score is not None
    assert blurred_score is not None
    assert sharp_score > blurred_score
