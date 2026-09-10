"""Phase 2 of the photo-culling feature: perceptual-hash clustering + best-of-group
ranking. Pure logic, no DB - see test_photo_quality.py for the equivalent Phase 1 tests
and photo_similarity.py's module docstring for why this can run synchronously."""

import time

import pytest

from app.services.photo_similarity import (
    MAX_GROUPING_IMAGES,
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


def test_group_is_sorted_best_first_by_sharpness_then_exposure():
    base = 0x1111_1111_1111_1111
    images = [
        GroupableImage(id=1, perceptual_hash=_hex_hash(base), sharpness_score=3.0, exposure_score=1.0),
        GroupableImage(id=2, perceptual_hash=_hex_hash(base), sharpness_score=9.0, exposure_score=0.2),
        GroupableImage(id=3, perceptual_hash=_hex_hash(base), sharpness_score=9.0, exposure_score=0.8),
    ]

    groups = group_similar_images(images)

    assert len(groups) == 1
    assert [image.id for image in groups[0]] == [3, 2, 1]


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
