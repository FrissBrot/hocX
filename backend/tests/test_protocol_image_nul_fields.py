"""Nachtlauf 2026-11-25 (protokolle/eingaben): NUL-Zeichen in Multipart-Feldern des Protokollbild-
Uploads. NulGuardMiddleware prüft nur JSON-Bodies; Titel, Legende und Dateiname eines Bildes
mit NUL liessen erst das INSERT mit psycopg.DataError scheitern (400 «Image could not be
uploaded» plus Eintrag im Fehlerprotokoll). Jetzt: Titel/Legende 400 ohne Fehlerprotokoll,
Steuerzeichen im Dateinamen werden entfernt."""

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models import StoredFile
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
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(content: bytes, filename: str = "bild.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "image/png"}))


def _block(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="image")
    return tenant, block


@pytest.mark.parametrize("field", ["title", "caption"])
def test_nul_in_title_or_caption_is_rejected_without_error_log(db, field):
    tenant, block = _block(db)
    user = make_current_user(tenant.id)
    kwargs = {"title": None, "caption": None, field: "Vorstand\x00 2026"}

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            files_routes._upload_image_impl(
                block.public_id, file=_upload(_png((1, 2, 3))), include_gps=False, db=db, user=user, **kwargs
            )
        )

    assert rejected.value.status_code == 400
    # Erwartet: ValueError als Ursache, damit der HTTPException-Handler nichts protokolliert
    assert isinstance(rejected.value.__cause__, ValueError)


def test_control_characters_are_removed_from_the_file_name(db):
    _tenant, block = _block(db)

    result = asyncio.run(
        FileService().save_protocol_image(db, protocol_element_block=block, file=_upload(_png((4, 5, 6)), filename="Sitz\x00ung\t1.png"))
    )

    stored = db.scalar(select(StoredFile).where(StoredFile.public_id == result.stored_file_id))
    assert stored.original_name == "Sitzung1.png"


def test_file_name_of_only_control_characters_gets_a_fallback(db):
    _tenant, block = _block(db)

    result = asyncio.run(
        FileService().save_protocol_image(db, protocol_element_block=block, file=_upload(_png((7, 8, 9)), filename="\x00\x01"))
    )

    stored = db.scalar(select(StoredFile).where(StoredFile.public_id == result.stored_file_id))
    assert stored.original_name == "datei"
