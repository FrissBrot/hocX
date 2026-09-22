"""Phase 1 of the photo-culling feature: cheap, model-free technical quality signals.
Pure functions on image bytes, no DB/storage involved - see test_file_thumbnails.py for
the equivalent upload-pipeline-level tests of _generate_thumbnail_bytes."""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.services.photo_quality import composite_quality_score, compute_exposure_score, compute_quality_scores, compute_sharpness_score


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


def test_sharp_subject_on_blurred_background_is_not_rated_as_blurry():
    """Portrait with bokeh: only a small region is in focus. A global variance would rate
    this like a blurry photo; the tile-based percentile must stay close to the all-sharp one."""
    sharp = _checkerboard(size=512)
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius=6))
    portrait = blurred.copy()
    portrait.paste(sharp.crop((192, 128, 384, 384)), (192, 128))

    all_sharp_score = compute_sharpness_score(_png_bytes(sharp))
    portrait_score = compute_sharpness_score(_png_bytes(portrait))
    all_blurred_score = compute_sharpness_score(_png_bytes(blurred))

    assert portrait_score is not None and all_sharp_score is not None and all_blurred_score is not None
    assert portrait_score > all_blurred_score * 10
    assert portrait_score > all_sharp_score * 0.5


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


def test_compute_quality_scores_matches_the_individual_functions():
    """compute_quality_scores decodes once instead of twice (audit fix, 2026-09-17) but
    must agree exactly with calling both individual functions separately."""
    sharp = _checkerboard()
    content = _png_bytes(sharp)

    sharpness, exposure = compute_quality_scores(content)

    assert sharpness == compute_sharpness_score(content)
    assert exposure == compute_exposure_score(content)


def test_compute_quality_scores_is_none_none_for_undecodable_content():
    assert compute_quality_scores(b"not an image") == (None, None)


def test_good_portrait_outranks_a_more_detailed_scene():
    assert composite_quality_score(20, 0.9, 100) > composite_quality_score(300, 1.0, None)


def test_sharp_background_cannot_rescue_a_blurry_face():
    assert composite_quality_score(1000, 1.0, 1) < composite_quality_score(100, 1.0, None)


def test_portrait_ranking_ignores_background_sharpness():
    assert composite_quality_score(10, 0.9, 100) == composite_quality_score(1000, 0.9, 100)


def test_quality_score_preserves_missing_and_zero_scores():
    assert composite_quality_score(None, None, None) is None
    assert composite_quality_score(100, None, None) is None
    assert composite_quality_score(None, None, 0) == 0
    assert composite_quality_score(0, 1, None) == 0
