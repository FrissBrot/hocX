"""save_protocol_image(): exact-duplicate blocking (SHA-256, scoped to the protocol_element_block)
and perceptual-hash duplicate warning (scoped to the tenant, non-blocking)."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageDraw
from starlette.datastructures import Headers

from app.models.entities import Protocol, Tenant
from app.services.file_service import FileService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    # In the real running stack settings.storage_root is bind-mounted to the host's
    # ./storage directory - writing unmonkeypatched would leave real files behind on disk,
    # same convention as test_document_template_service.py.
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _circle_png_bytes(size: tuple[int, int], cx: int, cy: int, r: int) -> bytes:
    """A flat-color image is a degenerate case for pHash (DCT of a constant image is always
    the same hash regardless of hue) - draw an actual shape so perceptual similarity/difference
    is meaningful. Small size/position shifts stay close; moving the circle elsewhere in the
    frame is a genuinely different composition."""
    image = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(image).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 180, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_file(content: bytes, filename: str = "image.png", content_type: str = "image/png") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def _make_tenant_with_protocol(db) -> tuple[Tenant, Protocol]:
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    return tenant, protocol


_next_sort_index = iter(range(1000))


def _make_block(db, protocol_id: int):
    element = make_protocol_element(db, protocol_id, sort_index=next(_next_sort_index))
    return make_protocol_element_block(db, element.id, configuration_snapshot_json={})


def test_exact_duplicate_within_same_block_is_rejected(db):
    _, protocol = _make_tenant_with_protocol(db)
    block = _make_block(db, protocol.id)
    service = FileService()
    content = _png_bytes((10, 20, 30))

    asyncio.run(service.save_protocol_image(db, protocol_element_block=block, file=_upload_file(content)))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.save_protocol_image(db, protocol_element_block=block, file=_upload_file(content)))
    assert exc_info.value.status_code == 409


def test_identical_image_in_different_block_of_same_tenant_is_not_blocked(db):
    """Exact-duplicate blocking is scoped to the block, not the tenant - reusing the same
    picture (e.g. a club logo) in a different block/protocol must still be allowed."""
    _, protocol = _make_tenant_with_protocol(db)
    block_a = _make_block(db, protocol.id)
    block_b = _make_block(db, protocol.id)
    service = FileService()
    content = _png_bytes((40, 50, 60))

    asyncio.run(service.save_protocol_image(db, protocol_element_block=block_a, file=_upload_file(content)))
    result = asyncio.run(service.save_protocol_image(db, protocol_element_block=block_b, file=_upload_file(content)))

    assert result.id is not None


def test_similar_image_in_same_tenant_gets_duplicate_warning_but_still_uploads(db):
    _, protocol = _make_tenant_with_protocol(db)
    block_a = _make_block(db, protocol.id)
    block_b = _make_block(db, protocol.id)
    service = FileService()

    asyncio.run(
        service.save_protocol_image(
            db, protocol_element_block=block_a, file=_upload_file(_circle_png_bytes((200, 150), 100, 75, 50), filename="a.png")
        )
    )
    # Same picture, slightly resized/cropped - visually near-identical, byte-different -
    # exercises the perceptual-hash path rather than the SHA-256 exact-match path.
    result = asyncio.run(
        service.save_protocol_image(
            db,
            protocol_element_block=block_b,
            file=_upload_file(_circle_png_bytes((196, 148), 98, 74, 49), filename="b.png"),
        )
    )

    assert result.id is not None
    assert result.duplicate_warning is not None


def test_visually_different_image_in_same_tenant_gets_no_warning(db):
    _, protocol = _make_tenant_with_protocol(db)
    block_a = _make_block(db, protocol.id)
    block_b = _make_block(db, protocol.id)
    service = FileService()

    asyncio.run(
        service.save_protocol_image(
            db, protocol_element_block=block_a, file=_upload_file(_circle_png_bytes((200, 150), 100, 75, 50), filename="a.png")
        )
    )
    # Same canvas size, but a completely different composition (circle elsewhere in the frame).
    result = asyncio.run(
        service.save_protocol_image(
            db, protocol_element_block=block_b, file=_upload_file(_circle_png_bytes((200, 150), 40, 110, 45), filename="b.png")
        )
    )

    assert result.duplicate_warning is None


def test_identical_image_across_different_tenants_gets_no_warning(db):
    """The tenant-wide similarity warning must never leak across tenants."""
    _, protocol_a = _make_tenant_with_protocol(db)
    _, protocol_b = _make_tenant_with_protocol(db)
    block_a = _make_block(db, protocol_a.id)
    block_b = _make_block(db, protocol_b.id)
    service = FileService()
    content = _png_bytes((90, 90, 200))

    asyncio.run(service.save_protocol_image(db, protocol_element_block=block_a, file=_upload_file(content, filename="a.png")))
    result = asyncio.run(service.save_protocol_image(db, protocol_element_block=block_b, file=_upload_file(content, filename="b.png")))

    assert result.duplicate_warning is None
