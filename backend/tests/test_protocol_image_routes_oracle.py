"""Nachtlauf 2026-11-19 (protokolle/mandantentrennung): Die Protokollbild-Routen in files.py
lösen Block bzw. Bild ohne Mandant auf und prüfen danach nur ensure_can_read_protocol_block, das
mit 403 «Protocol not assigned to current reader» antwortet. Unbekannte IDs ergeben 404 - fremde
Blöcke/Bilder (ohne RLS) und Entwürfe für Leser ohne Entwurfsrecht verraten so ihre Existenz
(SECURITY-RULES 1.6). Die Schreibrouten (Upload, Löschen) folgen derselben Prüfung."""
import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models import ProtocolImage
from app.services.file_service import FileService
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

    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "storage-local" / "thumbnails"))


def _png_upload() -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), color=(10, 20, 30)).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename="bild.png", headers=Headers({"content-type": "image/png"}))


def _block_with_image(db, tenant_id: int):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    image = asyncio.run(FileService().save_protocol_image(db, protocol_element_block=block, file=_png_upload()))
    return block, db.query(ProtocolImage).filter(ProtocolImage.public_id == image.id).one()


def _status(call) -> int:
    with pytest.raises(HTTPException) as exc_info:
        call()
    return exc_info.value.status_code


def test_foreign_block_and_image_answer_like_unknown_ids(db):
    owner = make_tenant(db, "Besitzer")
    other = make_tenant(db, "Fremd")
    block, image = _block_with_image(db, owner.id)
    attacker = make_current_user(other.id)

    unknown_list = _status(lambda: files_routes.list_images(uuid.uuid4(), db=db, user=attacker))
    unknown_delete = _status(lambda: files_routes.delete_image(uuid.uuid4(), db=db, user=attacker))
    assert (unknown_list, unknown_delete) == (404, 404)

    assert _status(lambda: files_routes.list_images(block.public_id, db=db, user=attacker)) == 404
    assert _status(lambda: files_routes.delete_image(image.public_id, db=db, user=attacker)) == 404
    upload = lambda: asyncio.run(files_routes._upload_image_impl(  # noqa: E731
        protocol_element_block_id=block.public_id, file=_png_upload(), title=None, caption=None,
        include_gps=True, db=db, user=attacker,
    ))
    assert _status(upload) == 404


def test_draft_images_answer_404_for_reader_without_draft_access(db):
    tenant = make_tenant(db)
    block, _image = _block_with_image(db, tenant.id)
    reader = make_current_user(tenant.id, role="reader")

    assert _status(lambda: files_routes.list_images(block.public_id, db=db, user=reader)) == 404
