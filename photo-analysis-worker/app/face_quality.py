"""Photo-culling Phase 3: detects the most confident face in an image and scores its
sharpness/exposure. Deliberately its own small implementation rather than importing
backend/app/services/photo_quality.py's sharpness/exposure functions - this is a separate
Docker build context (see the Dockerfile), and this worker already needs OpenCV for face
detection, so it uses cv2/numpy directly instead of also pulling in Pillow/scipy.

Manually verified against a real photograph (a public-domain NASA official portrait - see
tests/test_face_quality.py's docstring for why that isn't committed as a fixture). That
smoke test caught a real bug fixed here: YuNet reliably fails to detect anything at all on
a full, unscaled modern-camera-resolution image (tested: still finds a face at 2000px on
the longer side, confidence ~0.94; finds nothing at all at 3000px) - _DETECTION_MAX_DIMENSION
below keeps every image in the range that was actually confirmed to work.
"""

from __future__ import annotations

import cv2
import numpy as np

# YuNet's own default from opencv_zoo's demo.py - below this, "detections" are mostly
# false positives on texture/noise rather than real faces.
MIN_FACE_CONFIDENCE = 0.9

# See the module docstring: YuNet was confirmed working up to ~2000px and confirmed
# broken (no detections at all, not just lower confidence) at 3000px on the same real
# photo. 1600 keeps real-world phone/DSLR-resolution uploads well inside the confirmed-
# working range while still giving the sharpness/exposure scoring below a decently
# detailed crop to work with.
_DETECTION_MAX_DIMENSION = 1600

# Clipped-highlight/shadow pixel threshold, same convention as backend's
# photo_quality.py's compute_exposure_score (0-255 range, close to either end counts as
# "clipped").
_CLIPPED_BIN_WIDTH = 3


def load_detector(model_path: str) -> cv2.FaceDetectorYN:
    # inputSize is set to a placeholder here and overridden per-image in
    # score_face_quality via setInputSize - YuNet needs it to match the actual frame size.
    return cv2.FaceDetectorYN_create(model_path, "", (320, 320))


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _exposure(gray: np.ndarray) -> float:
    total = gray.size
    if total == 0:
        return 0.0
    clipped = int(np.count_nonzero(gray <= _CLIPPED_BIN_WIDTH)) + int(np.count_nonzero(gray >= 255 - _CLIPPED_BIN_WIDTH))
    return max(0.0, 1.0 - clipped / total)


def score_face_quality(detector: cv2.FaceDetectorYN, image_bytes: bytes) -> float | None:
    """Returns a quality score for the most confident detected face's region, or None if
    the bytes couldn't be decoded as an image or no face was found. The score combines
    sharpness (dominant factor) and exposure (tie-breaker among similarly-sharp faces) the
    same way photo_similarity.py's _quality_rank orders images - exposure alone maxes out
    at 1.0 so it can only ever scale sharpness down, never overrule it."""
    if not image_bytes:
        # cv2.imdecode raises a hard C++ assertion on an empty buffer instead of
        # returning None the way it does for non-empty-but-invalid data.
        return None
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return None

    height, width = image.shape[:2]
    if height == 0 or width == 0:
        return None

    scale = min(1.0, _DETECTION_MAX_DIMENSION / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
        height, width = image.shape[:2]

    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None

    # Each row: [x, y, w, h, <5 landmark x/y pairs>, confidence] - see opencv_zoo's
    # demo.py (models/face_detection_yunet/demo.py), which this mirrors.
    best = max(faces, key=lambda face: face[14])
    if best[14] < MIN_FACE_CONFIDENCE:
        return None

    x, y, w, h = (int(round(v)) for v in best[:4])
    x, y = max(0, x), max(0, y)
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return _sharpness(gray) * (0.5 + 0.5 * _exposure(gray))
