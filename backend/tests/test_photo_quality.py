"""Phase 1 of the photo-culling feature: cheap, model-free technical quality signals.
Pure functions on image bytes, no DB/storage involved - see test_file_thumbnails.py for
the equivalent upload-pipeline-level tests of _generate_thumbnail_bytes."""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.services.photo_quality import compute_exposure_score, compute_sharpness_score


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _checkerboard(size: int = 256, tile: int = 4) -> Image.Image:
    xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    pattern = (((xs // tile) + (ys // tile)) % 2 * 255).astype(np.uint8)
    return Image.fromarray(pattern, mode="L").convert("RGB")


def test_sharpness_score_is_higher_for_a_sharp_image_than_a_blurred_copy():
    sharp = _checkerboard()
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius=6))

    sharp_score = compute_sharpness_score(_png_bytes(sharp))
    blurred_score = compute_sharpness_score(_png_bytes(blurred))

    assert sharp_score is not None
    assert blurred_score is not None
    assert sharp_score > blurred_score


def test_sharpness_score_is_none_for_undecodable_content():
    assert compute_sharpness_score(b"not an image") is None


def test_exposure_score_penalizes_clipped_highlights_and_shadows():
    well_exposed = Image.new("RGB", (64, 64), color=(128, 128, 128))
    blown_out = Image.new("RGB", (64, 64), color=(255, 255, 255))
    crushed_black = Image.new("RGB", (64, 64), color=(0, 0, 0))

    well_exposed_score = compute_exposure_score(_png_bytes(well_exposed))
    blown_out_score = compute_exposure_score(_png_bytes(blown_out))
    crushed_black_score = compute_exposure_score(_png_bytes(crushed_black))

    assert well_exposed_score == 1.0
    assert blown_out_score == 0.0
    assert crushed_black_score == 0.0
    assert well_exposed_score > blown_out_score
    assert well_exposed_score > crushed_black_score


def test_exposure_score_is_none_for_undecodable_content():
    assert compute_exposure_score(b"not an image") is None
