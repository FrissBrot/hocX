"""Duplicate-check helpers added to routes/public.py for the tenant-wide image-similarity
warning. No DB fixture exists anywhere in this test suite yet (see test_upload_size_limits.py's
docstring) - list_checksums_for_element/list_tenant_image_hashes in repository.py are simple,
directly-mirrored SQLAlchemy Core selects following the exact join pattern already used (and
covered) by count_files_by_element, so this file focuses on the actually new logic: the
perceptual-hash computation and comparison, which is pure and needs no DB."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from app.routes.public import _compute_perceptual_hash, _has_close_perceptual_match


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _circle_png_bytes(size: tuple[int, int], cx: int, cy: int, r: int) -> bytes:
    """A flat-color image is a degenerate case for pHash (DCT of a constant image is always
    the same hash regardless of hue) - draw an actual shape so perceptual similarity/difference
    is meaningful."""
    image = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(image).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 180, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_compute_perceptual_hash_returns_none_for_non_image_mime():
    assert _compute_perceptual_hash(b"%PDF-1.4 ...", "application/pdf") is None


def test_compute_perceptual_hash_returns_none_for_undecodable_image_bytes():
    assert _compute_perceptual_hash(b"not a real image", "image/png") is None


def test_compute_perceptual_hash_returns_hash_for_real_image():
    assert _compute_perceptual_hash(_png_bytes((10, 20, 30)), "image/png") is not None


def test_has_close_perceptual_match_true_for_near_identical_images():
    a = _compute_perceptual_hash(_circle_png_bytes((200, 150), 100, 75, 50), "image/png")
    # Same picture, slightly resized/cropped.
    b = _compute_perceptual_hash(_circle_png_bytes((196, 148), 98, 74, 49), "image/png")

    assert _has_close_perceptual_match(a, [b])


def test_has_close_perceptual_match_false_for_different_images():
    a = _compute_perceptual_hash(_circle_png_bytes((200, 150), 100, 75, 50), "image/png")
    # Same canvas size, but a completely different composition (circle elsewhere in the frame).
    b = _compute_perceptual_hash(_circle_png_bytes((200, 150), 40, 110, 45), "image/png")

    assert not _has_close_perceptual_match(a, [b])


def test_has_close_perceptual_match_false_for_empty_candidates():
    a = _compute_perceptual_hash(_circle_png_bytes((200, 150), 100, 75, 50), "image/png")

    assert not _has_close_perceptual_match(a, [])
