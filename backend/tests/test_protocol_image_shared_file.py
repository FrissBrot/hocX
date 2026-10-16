"""Audit MAIN-BE-001 / MAIN-BE-007: Protokollbilder, die per "aus letztem Protokoll
übernehmen" dieselbe StoredFile teilen, und der Freeze-Schutz der Bild-Routen."""
import asyncio
import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models import ProtocolImage, StoredFile
from app.services.file_service import FileService, _safe_storage_path
from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "storage-local" / "thumbnails"))


def _png_upload() -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color=(10, 20, 30)).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename="bild.png", headers=Headers({"content-type": "image/png"}))


def _make_block(db, tenant_id: int, template_id: int, number: str, status: str = "geplant"):
    protocol = make_protocol(db, tenant_id, template_id, protocol_number=number, status=status)
    element = make_protocol_element(db, protocol.id)
    return protocol, make_protocol_element_block(db, element.id, configuration_snapshot_json={})


def _shared_image_setup(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    _, block_a = _make_block(db, tenant.id, template.id, "P-A")
    _, block_b = _make_block(db, tenant.id, template.id, "P-B")
    service = FileService()
    image_a = asyncio.run(service.save_protocol_image(db, protocol_element_block=block_a, file=_png_upload()))
    image_a_row = db.query(ProtocolImage).filter(ProtocolImage.public_id == image_a.id).one()
    # So legt create_from_template übernommene Bilder an: gleiche stored_file_id.
    image_b_row = ProtocolImage(
        protocol_element_block_id=block_b.id,
        stored_file_id=image_a_row.stored_file_id,
        sort_index=0,
    )
    db.add(image_b_row)
    db.flush()
    return tenant, service, image_a_row, image_b_row


def test_delete_shared_protocol_image_keeps_file_for_other_protocol(db):
    from app.core.config import settings

    _, service, image_a, image_b = _shared_image_setup(db)
    stored_file = db.get(StoredFile, image_a.stored_file_id)
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    assert file_path.exists()

    assert service.delete_protocol_image(db, image_b.id) is True

    assert db.get(ProtocolImage, image_a.id) is not None
    assert db.get(StoredFile, image_a.stored_file_id) is not None
    assert file_path.exists()


def test_delete_last_protocol_image_reference_removes_file_and_thumbnail(db):
    from app.core.config import settings

    _, service, image_a, image_b = _shared_image_setup(db)
    stored_file_id = image_a.stored_file_id
    stored_file = db.get(StoredFile, stored_file_id)
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    thumb_path = (
        _safe_storage_path(settings.thumbnail_root, stored_file.thumbnail_path) if stored_file.thumbnail_path else None
    )

    service.delete_protocol_image(db, image_b.id)
    service.delete_protocol_image(db, image_a.id)

    assert db.get(StoredFile, stored_file_id) is None
    assert not file_path.exists()
    if thumb_path is not None:
        assert not Path(thumb_path).exists()


def test_image_routes_reject_frozen_protocol(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    _, open_block = _make_block(db, tenant.id, template.id, "P-1")
    image = asyncio.run(FileService().save_protocol_image(db, protocol_element_block=open_block, file=_png_upload()))
    protocol_closed, closed_block = _make_block(db, tenant.id, template.id, "P-2", status="abgeschlossen")
    image_row = db.query(ProtocolImage).filter(ProtocolImage.public_id == image.id).one()
    image_row.protocol_element_block_id = closed_block.id
    db.flush()
    user = make_current_user(tenant.id, role="admin")

    with pytest.raises(HTTPException) as delete_exc:
        files_routes.delete_image(image.id, db=db, user=user)
    assert delete_exc.value.status_code == 409

    with pytest.raises(HTTPException) as upload_exc:
        asyncio.run(
            files_routes.upload_image(
                closed_block.public_id, file=_png_upload(), title=None, caption=None, db=db, user=user
            )
        )
    assert upload_exc.value.status_code == 409
    assert db.get(ProtocolImage, image_row.id) is not None
    assert protocol_closed.status == "abgeschlossen"
