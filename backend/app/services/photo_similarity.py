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

import imagehash

from app.services.photo_quality import composite_quality_score
from app.services.upload_pipeline import PERCEPTUAL_DUPLICATE_THRESHOLD

# Same "close enough to be a near-duplicate" threshold as upload_pipeline.py's tenant-wide
# duplicate-upload warning - one definition of "similar" across the feature rather than two
# independently-tuned ones (audit fix, 2026-09-17: this used to be its own separately-
# tuned SIMILARITY_HAMMING_THRESHOLD constant, despite the module docstring already
# claiming they were unified - no circular import actually blocks this: upload_pipeline.py
# has no reason to import this module back).
SIMILARITY_HAMMING_THRESHOLD = PERCEPTUAL_DUPLICATE_THRESHOLD

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


def _hash_as_int(perceptual_hash: imagehash.ImageHash) -> int:
    return int("".join("1" if bit else "0" for bit in perceptual_hash.hash.flatten()), 2)


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

    # Same imagehash.hex_to_hash + `-` distance upload_pipeline.py's own duplicate check
    # uses (audit fix, 2026-09-17: this used to parse the hex string as a raw int and XOR
    # it by hand instead - a second, independent hash-distance implementation that would
    # break differently than upload_pipeline's if the stored hash format ever changed).
    #
    # The parse still goes through imagehash, but each hash is converted to a plain int
    # once, so the O(n^2) loop below is an int XOR + popcount (same bit-for-bit Hamming
    # distance as ImageHash.__sub__) instead of a numpy array comparison per pair - that
    # was ~4.5s for MAX_GROUPING_IMAGES on a CI runner, i.e. 10x+ slower than this module's
    # docstring promises.
    hashed = [(image, _hash_as_int(imagehash.hex_to_hash(image.perceptual_hash))) for image in images if image.perceptual_hash]
    for i, (image_a, bits_a) in enumerate(hashed):
        for image_b, bits_b in hashed[i + 1 :]:
            if (bits_a ^ bits_b).bit_count() <= SIMILARITY_HAMMING_THRESHOLD:
                union(image_a.id, image_b.id)

    groups: dict[int, list[GroupableImage]] = {}
    for image in images:
        groups.setdefault(find(image.id), []).append(image)

    return [sorted(group, key=_quality_rank, reverse=True) for group in groups.values()]
