"""Cheap, model-free technical quality signals for the photo-culling feature (Phase 1 of
the "beste Bilder vorschlagen" pipeline - see project notes). Deliberately OpenCV-free:
uses only Pillow/numpy/scipy, already dependencies of this backend, so this stays usable
inline in the request path (no new container, no model weights to ship).

Scores are for RELATIVE ranking within one tenant's batch/gallery, not an absolute,
universally calibrated quality bar - "sharper than the other 999 photos in this upload"
is the question this answers, not "is this professionally sharp". Downstream phases
(similarity clustering, aesthetic/CLIP scoring, face-region quality) build on top of
these same two numbers rather than replacing them.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

# Both metrics are computed on a downscaled copy so score magnitude doesn't depend on the
# original resolution (a 50MP and a 5MP photo of the same scene should score similarly) and
# so this stays fast even on a large batch - see the module docstring on why this can run
# inline instead of needing the dedicated worker container later phases will need.
_ANALYSIS_MAX_DIMENSION = 512

# Histogram bins at the very top/bottom of the 0-255 range count as "clipped" (blown-out
# highlights / crushed shadows) for the exposure score below.
_CLIPPED_BIN_WIDTH = 3


def _load_grayscale_array(content: bytes) -> np.ndarray | None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)  # respect camera rotation metadata
            image = image.convert("L")
            image.thumbnail((_ANALYSIS_MAX_DIMENSION, _ANALYSIS_MAX_DIMENSION))
            return np.asarray(image, dtype=np.float64)
    except Exception:
        return None


def compute_sharpness_score(content: bytes) -> float | None:
    """Laplacian-variance blur estimate: a sharp image has a lot of high-frequency edge
    energy, a blurred/out-of-focus one doesn't. Unbounded, higher is sharper. Returns None
    for content PIL can't decode (mirrors _generate_thumbnail_bytes's convention in
    file_service.py)."""
    gray = _load_grayscale_array(content)
    if gray is None:
        return None
    return float(ndimage.laplace(gray).var())


def compute_exposure_score(content: bytes) -> float | None:
    """1.0 = no clipped shadows/highlights at all, 0.0 = the whole image is crushed black
    or blown-out white. Simple clipped-pixel-fraction metric rather than a full histogram
    model - "is this frame too dark/too bright to be usable" is the question, not a
    photometric exposure analysis. Returns None for content PIL can't decode."""
    gray = _load_grayscale_array(content)
    if gray is None:
        return None
    total_pixels = gray.size
    if total_pixels == 0:
        return None
    clipped_shadows = float(np.count_nonzero(gray <= _CLIPPED_BIN_WIDTH))
    clipped_highlights = float(np.count_nonzero(gray >= 255 - _CLIPPED_BIN_WIDTH))
    clipped_fraction = (clipped_shadows + clipped_highlights) / total_pixels
    return max(0.0, 1.0 - clipped_fraction)


def composite_quality_score(
    sharpness: float | None, exposure: float | None, face_quality: float | None
) -> float | None:
    """The one "how good is this photo" ranking used everywhere a single number is
    needed to pick a best image - album best-of/Stern selection (photo_album_service.py)
    and near-duplicate-series best-pick (photo_similarity.py) both call this, rather than
    each keeping its own formula (audit fix, 2026-09-17: they used to disagree - the
    duplicate-series picker ignored face_quality_score entirely, so it could pick a
    different "best" frame than the album picker for the same photos, and that picker's
    choice drives a destructive delete).

    Prefers face_quality (Phase 3, only present for images with a detected face) when
    available, since it's the most informative signal; otherwise falls back to sharpness
    scaled down by up to half for poor exposure, so an unscored-for-faces photo still
    lands on a comparable scale to a scored one rather than always losing to it."""
    if face_quality is not None:
        return face_quality
    if sharpness is not None and exposure is not None:
        return sharpness * (0.5 + 0.5 * exposure)
    return None
