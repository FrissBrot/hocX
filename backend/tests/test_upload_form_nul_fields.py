"""Nachtlauf 2026-11-25 (dateien-fotos/fehlerbehandlung): NulGuardMiddleware prüft nur JSON-Bodies,
nicht Multipart. Beim Galerie- und Dokument-Upload landeten NUL-Zeichen aus dem Formular (Tags,
Client-Dateiname) ungeprüft im Upload-Verlauf (JSONB-Optionen) bzw. im Galerie-Auftrag
(original_filenames) - das Speichern scheiterte mit psycopg.DataError: 500 und Eintrag im
Fehlerprotokoll für einen reinen Eingabefehler. Verwandt: Protokollbilder (#142)."""

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import GalleryUploadJob
from tests.factories import make_current_user, make_tenant

FORM = dict(event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None)


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _file(content: bytes, name: str, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({"content-type": content_type}))


def test_gallery_upload_rejects_nul_in_tags_as_input_error(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(files_routes.upload_gallery_images(
            files=[_file(_png(), "a.png", "image/png")], tags="Lager\x00", db=db, user=writer, **FORM,
        ))
    assert exc_info.value.status_code == 422
    assert exc_info.value.__cause__ is None  # erwartet: kein Eintrag im Fehlerprotokoll


def test_document_upload_rejects_nul_in_tags_as_input_error(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(files_routes.upload_documents(
            files=[_file(b"%PDF-1.7\n%test\n", "a.pdf", "application/pdf")], tags="Vertrag\x00", db=db, user=writer, **FORM,
        ))
    assert exc_info.value.status_code == 422
    assert exc_info.value.__cause__ is None


def test_gallery_upload_strips_control_characters_from_the_client_file_name(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    queued = asyncio.run(files_routes.upload_gallery_images(
        files=[_file(_png(), "fe\x00rien.png", "image/png")], tags=None, db=db, user=writer, **FORM,
    ))
    job = db.scalar(select(GalleryUploadJob).where(GalleryUploadJob.id == queued.id))
    assert job.original_filenames == ["ferien.png"]
