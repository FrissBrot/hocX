"""Phase 2 of the photo-culling feature: perceptual-hash clustering + best-of-group
ranking. Pure logic, no DB - see test_photo_quality.py for the equivalent Phase 1 tests
and photo_similarity.py's module docstring for why this can run synchronously."""

import time

import pytest

from app.services.photo_quality import composite_quality_score
from app.services.photo_similarity import (
    MAX_GROUPING_IMAGES,
    SERIES_HAMMING_THRESHOLD,
    SIMILARITY_HAMMING_THRESHOLD,
    GroupableImage,
    group_similar_images,
)


def _hex_hash(value: int) -> str:
    return format(value, "016x")


def test_near_identical_hashes_are_grouped_together():
    base = 0x1234_5678_9ABC_DEF0
    close = base ^ 0b111  # Hamming distance 3, within SIMILARITY_HAMMING_THRESHOLD (5)
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=10.0, exposure_score=0.9),
        GroupableImage(id=2, perceptual_hash=_hex_hash(close), sharpness_score=5.0, exposure_score=0.9),
    ]

    groups = group_similar_images(images)

    assert len(groups) == 1
    assert {image.id for image in groups[0]} == {1, 2}


def test_dissimilar_hashes_stay_in_separate_groups():
    base = 0x0000_0000_0000_0000
    far = 0xFFFF_FFFF_FFFF_FFFF  # Hamming distance 64
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=10.0, exposure_score=0.9),
        GroupableImage(id=2, perceptual_hash=_hex_hash(far), sharpness_score=5.0, exposure_score=0.9),
    ]

    groups = group_similar_images(images)

    assert len(groups) == 2


def test_group_is_sorted_best_first_by_composite_quality_score():
    base = 0x1111_1111_1111_1111
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=3.0, exposure_score=1.0),
        GroupableImage(id=2, perceptual_hash=_hex_hash(base), sharpness_score=9.0, exposure_score=0.2),
        GroupableImage(id=3, perceptual_hash=_hex_hash(base), sharpness_score=9.0, exposure_score=0.8),
    ]

    groups = group_similar_images(images)

    assert len(groups) == 1
    assert [image.id for image in groups[0]] == [3, 2, 1]


def test_group_ranking_uses_the_same_formula_as_album_best_of_selection():
    """Regression test (2026-09-17 audit fix): _quality_rank used to be its own
    (sharpness, exposure) tuple sort that silently ignored face_quality_score, so it could
    disagree with photo_album_service.recompute_best_of's composite_quality_score-based
    ranking for the same photos - and this ranking's pick drives the destructive "Nur
    beste behalten" delete. Both now delegate to the one shared composite_quality_score
    function (photo_quality.py), so two images with a tied composite score (one via a
    high face_quality_score, one via sharpness*exposure landing on the same number) must
    tie here too - not something a (sharpness, exposure) tuple sort could ever do, since
    it never looks at face_quality_score at all."""
    base = 0x5555_5555_5555_5555
    images = [
        # Gleicher Gesamtscore trotz unterschiedlicher Rohwerte und Gesichtsvorrang.
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=60.0, exposure_score=0.2, face_quality_score=None),
        GroupableImage(id=2, perceptual_hash=_hex_hash(base), sharpness_score=999.0, exposure_score=0.01, face_quality_score=9.0),
    ]

    groups = group_similar_images(images)

    assert {image.id for image in groups[0]} == {1, 2}
    assert composite_quality_score(60.0, 0.2, None) == composite_quality_score(None, None, 9.0) == 6.0


def test_images_without_a_perceptual_hash_never_join_a_group():
    base = 0x2222_2222_2222_2222
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=1.0, exposure_score=1.0),
        GroupableImage(id=2, perceptual_hash=None, sharpness_score=1.0, exposure_score=1.0),
        GroupableImage(id=3, perceptual_hash=None, sharpness_score=1.0, exposure_score=1.0),
    ]

    groups = group_similar_images(images)

    assert sorted(len(group) for group in groups) == [1, 1, 1]


def test_missing_scores_rank_last_but_are_still_returned():
    base = 0x3333_3333_3333_3333
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=None, exposure_score=None),
        GroupableImage(id=2, perceptual_hash=_hex_hash(base), sharpness_score=1.0, exposure_score=0.1),
    ]

    groups = group_similar_images(images)

    assert [image.id for image in groups[0]] == [2, 1]


def test_series_threshold_groups_images_too_far_apart_for_the_default_duplicate_threshold():
    """The "Ähnliche" tab passes threshold=SERIES_HAMMING_THRESHOLD (looser than the
    "Duplikate" tab's default SIMILARITY_HAMMING_THRESHOLD) so related-but-distinct frames of
    a series still cluster, without the default call's behavior changing."""
    base = 0x0000_0000_0000_0000
    mid_distance = base ^ 0b1111_1110  # Hamming distance 7: over the default 5, within 14.

    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=10.0, exposure_score=0.9),
        GroupableImage(id=2, perceptual_hash=_hex_hash(mid_distance), sharpness_score=5.0, exposure_score=0.9),
    ]

    assert len(group_similar_images(images, threshold=SIMILARITY_HAMMING_THRESHOLD)) == 2
    assert len(group_similar_images(images)) == 2  # default matches SIMILARITY_HAMMING_THRESHOLD

    series_groups = group_similar_images(images, threshold=SERIES_HAMMING_THRESHOLD)
    assert len(series_groups) == 1
    assert {image.id for image in series_groups[0]} == {1, 2}


def test_transitive_chain_merges_into_one_group():
    # A-B close, B-C close, A-C far: should still end up as one group via B.
    a = 0x0000_0000_0000_0000
    b = a ^ 0b111  # distance 3 from a
    c = b ^ 0b111_000  # distance 3 from b, but distance 6 from a (over threshold alone)
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(a), sharpness_score=1.0, exposure_score=1.0),
        GroupableImage(id=2, perceptual_hash=_hex_hash(b), sharpness_score=1.0, exposure_score=1.0),
        GroupableImage(id=3, perceptual_hash=_hex_hash(c), sharpness_score=1.0, exposure_score=1.0),
    ]

    groups = group_similar_images(images)

    assert len(groups) == 1
    assert {image.id for image in groups[0]} == {1, 2, 3}


def test_raises_above_max_grouping_images():
    images = [
        GroupableImage(id=i, perceptual_hash=_hex_hash(i), sharpness_score=1.0, exposure_score=1.0)
        for i in range(MAX_GROUPING_IMAGES + 1)
    ]

    with pytest.raises(ValueError):
        group_similar_images(images)


def test_max_grouping_images_completes_in_well_under_a_second():
    """Benchmark backing the MAX_GROUPING_IMAGES cap - see photo_similarity.py's module
    docstring. Random hashes essentially never collide within the threshold, so this also
    exercises the worst case (no early union() shortcuts)."""
    import random

    rng = random.Random(0)
    images = [
        GroupableImage(id=i, perceptual_hash=_hex_hash(rng.getrandbits(64)), sharpness_score=1.0, exposure_score=1.0)
        for i in range(MAX_GROUPING_IMAGES)
    ]

    started = time.perf_counter()
    group_similar_images(images)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0


def _photo_like_image(size=(240, 320)):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (70, 120, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 60, 120, 250), fill=(200, 60, 40))
    draw.ellipse((100, 20, 200, 120), fill=(240, 220, 90))
    draw.rectangle((150, 180, 230, 300), fill=(30, 140, 60))
    return image


def test_perceptual_hash_ignores_exif_orientation():
    from app.services.upload_pipeline import perceptual_hash_of_image

    upright = _photo_like_image()
    sideways = upright.rotate(90, expand=True)  # pixels stored sideways...
    exif = sideways.getexif()
    exif[274] = 6  # ...with "rotate 90 CW to display" tag (undoes the rotate above)
    sideways.info["exif"] = exif.tobytes()
    import io

    from PIL import Image

    buffer = io.BytesIO()
    sideways.save(buffer, format="JPEG", exif=exif.tobytes(), quality=95)
    with Image.open(io.BytesIO(buffer.getvalue())) as reloaded:
        assert perceptual_hash_of_image(reloaded) - perceptual_hash_of_image(upright) <= 5


def test_perceptual_hash_ignores_black_letterbox_border():
    from PIL import Image

    from app.services.upload_pipeline import perceptual_hash_of_image

    photo = _photo_like_image()
    framed = Image.new("RGB", (photo.width + 90, photo.height + 140), (0, 0, 0))
    framed.paste(photo, (30, 90))
    assert perceptual_hash_of_image(framed) - perceptual_hash_of_image(photo) <= 5


def test_perceptual_hash_keeps_dark_photos_uncropped():
    from PIL import Image

    from app.services.upload_pipeline import _crop_uniform_border

    # Dark corners but bright content covering <40% of the frame must not be treated as border.
    night = Image.new("RGB", (200, 200), (5, 5, 5))
    night.paste((250, 250, 250), (80, 80, 120, 120))
    assert _crop_uniform_border(night).size == (200, 200)
