"""Phase 2 of the photo-culling feature: groups visually similar images using the
perceptual_hash already computed for the tenant-wide duplicate-upload warning (see
file_service.py's PERCEPTUAL_DUPLICATE_THRESHOLD/_closest_perceptual_match), and picks one
"best" image per group using the Phase 1 quality scores (photo_quality.py). Pure
computation over already-computed per-image data - no model, no DB/network access inside
this module - which is why grouping can run synchronously in the request path instead of
needing the dedicated worker container later phases will need: an int XOR + popcount per
pair costs a fraction of a microsecond, so even the O(n^2) pairwise comparison stays under
a second for the batch sizes (~1000 images) this feature targets. See
tests/test_photo_similarity.py for the benchmark MAX_GROUPING_IMAGES is based on.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.photo_quality import composite_quality_score

# Same "close enough to be a near-duplicate" threshold as file_service.py's tenant-wide
# duplicate-upload warning - one definition of "similar" across the feature rather than two
# independently-tuned ones. Not imported from there to avoid a circular import (file_service
# imports this module, not the other way around).
SIMILARITY_HAMMING_THRESHOLD = 5

# Safety cap for the synchronous grouping endpoint/service method - protects the shared,
# memory-constrained backend container from an unbounded O(n^2) computation blocking one of
# its two worker processes. Larger batches need the async worker Phase 3 introduces.
MAX_GROUPING_IMAGES = 1500


@dataclass(frozen=True)
class GroupableImage:
    id: int
    perceptual_hash: str | None
    sharpness_score: float | None
    exposure_score: float | None
    face_quality_score: float | None = None


def _hamming_distance(hash_a: int, hash_b: int) -> int:
    return bin(hash_a ^ hash_b).count("1")


def _quality_rank(image: GroupableImage) -> float:
    """Sort key for picking the best image within a group - the same composite_quality_score
    used for album best-of/Stern selection (photo_album_service.py), so the "best" pick here
    and there can't disagree for the same photo (audit fix, 2026-09-17: this used to be its
    own sharpness/exposure-only tuple, silently ignoring face_quality_score even though the
    "Nur beste behalten" button built on this ranking permanently deletes every other image
    in the group). Missing scores rank last rather than raising - an unscored image just
    never outranks a scored one, though it can still be the (only) image in its own
    singleton group."""
    score = composite_quality_score(image.sharpness_score, image.exposure_score, image.face_quality_score)
    return score if score is not None else float("-inf")


def group_similar_images(images: list[GroupableImage]) -> list[list[GroupableImage]]:
    """Union-find clustering by perceptual-hash Hamming distance. Images without a
    perceptual_hash (a decode failure at upload time - see _compute_perceptual_hash) never
    join a group, each becomes its own singleton. Returns groups in first-seen order (the
    order `images` was given in), each group's images sorted best-first (see _quality_rank).
    Raises ValueError above MAX_GROUPING_IMAGES - callers should catch this and ask the user
    to narrow their filter rather than let it silently run long."""
    if len(images) > MAX_GROUPING_IMAGES:
        raise ValueError(f"too many images to group synchronously (max {MAX_GROUPING_IMAGES}, got {len(images)})")

    parent = {image.id: image.id for image in images}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    hashed = [(image, int(image.perceptual_hash, 16)) for image in images if image.perceptual_hash]
    for i, (image_a, hash_a) in enumerate(hashed):
        for image_b, hash_b in hashed[i + 1 :]:
            if _hamming_distance(hash_a, hash_b) <= SIMILARITY_HAMMING_THRESHOLD:
                union(image_a.id, image_b.id)

    groups: dict[int, list[GroupableImage]] = {}
    for image in images:
        groups.setdefault(find(image.id), []).append(image)

    return [sorted(group, key=_quality_rank, reverse=True) for group in groups.values()]
