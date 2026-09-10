"""face_quality.py: face detection + crop scoring.

Note on coverage: these tests verify (a) the detector loads and runs without crashing,
(b) it correctly reports "no face" for non-face input, and (c) the sharpness/exposure
scoring math itself is correct once a region is given to it. They do NOT verify positive
detection accuracy against a real photograph of a face - sourcing a real face image as a
committed test fixture raised licensing/consent questions (whose photo, redistributable
under what terms) that weren't worth working around for this pass. Do one manual smoke
test with a real photo before relying on this in production.
"""

import cv2
import numpy as np
import pytest

from app.face_quality import _exposure, _sharpness, load_detector, score_face_quality

MODEL_PATH = "/app/models/face_detection_yunet.onnx"


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
