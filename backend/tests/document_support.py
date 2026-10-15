"""Gemeinsame Hilfen für die Dokument-Tests (Speicher im tmp-Ordner, Dateien mit Herkunft)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models import GalleryImage, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.documents import formats
from tests.factories import make_list_definition, make_list_entry

FIXTURES = Path(__file__).parent / "fixtures" / "documents"

MIME_BY_SUFFIX = {
    ".docx": formats.DOCX,
    ".doc": formats.DOC,
    ".odt": formats.ODT,
    ".rtf": formats.RTF,
    ".pdf": formats.PDF,
    ".txt": formats.TXT,
    ".md": formats.MD,
    ".csv": formats.CSV,
    ".xlsx": formats.XLSX,
    ".png": "image/png",
    ".zip": "application/zip",
}


@pytest.fixture
def document_storage(monkeypatch, tmp_path):
    """Dateisystem-Speicher und Arbeitsordner im tmp-Ordner des Tests."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "storage_work_root", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    return tmp_path


@pytest.fixture
def savepoint_rollback(db, monkeypatch):
    """Der Testrahmen (conftest.db) hält eine äussere Transaktion offen; ein echtes rollback() im
    Code unter Test würde sie mitnehmen und alle Testdaten verwerfen. Die Fehlerpfade, die diese
    Tests auslösen, sind keine Datenbankfehler (Sandbox, fehlende Datei, Mandant) und lassen keine
    halbfertigen Änderungen zurück - rollback() verwirft hier darum nur den Objekt-Cache."""
    monkeypatch.setattr(db, "rollback", db.expire_all)


def put_stored_file(
    db, tenant_id: int, name: str, data: bytes, *, mime_type: str | None = None, scan_status: str = "clean",
    namespace: str = MAIN, created_by: int | None = None,
) -> StoredFile:
    suffix = Path(name).suffix.lower()
    key = f"uploads/tenant-{tenant_id}/documents/{name}" if namespace == MAIN else f"tenant-{tenant_id}/{name}"
    info = get_object_store().put_bytes(db, namespace, key, data, content_type=mime_type)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type=mime_type or MIME_BY_SUFFIX.get(suffix),
        storage_path=key, file_size_bytes=info.size, checksum_sha256=info.sha256, scan_status=scan_status,
        created_by=created_by,
    )
    db.add(stored_file)
    db.flush()
    return stored_file


def gallery_document(db, tenant_id: int, name: str, data: bytes | None = None, **kwargs) -> StoredFile:
    """Dokument-Upload über den Dateien-Tab (gallery_image ohne Bezug)."""
    stored_file = put_stored_file(db, tenant_id, name, data if data is not None else (FIXTURES / name).read_bytes(), **kwargs)
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id, created_by=kwargs.get("created_by")))
    db.flush()
    return stored_file


def submission_document(db, tenant_id: int, name: str, data: bytes | None = None, *, delete_comment: str | None = None, **kwargs):
    """Wie die Abgabebox es schreibt: submission_upload + stored_file (Namespace abgabebox) +
    submission_upload_file."""
    list_definition = make_list_definition(db, tenant_id, name=f"Liste {uuid.uuid4().hex[:8]}")
    entry = make_list_entry(db, list_definition.id)
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Berichte", public_slug=f"berichte-{entry.id}", source_type="list",
        list_definition_id=list_definition.id,
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, list_entry_id=entry.id, status="submitted")
    db.add(upload)
    db.flush()
    stored_file = put_stored_file(
        db, tenant_id, name, data if data is not None else (FIXTURES / name).read_bytes(), namespace=ABGABEBOX, **kwargs
    )
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id, delete_comment=delete_comment))
    db.flush()
    return assignment, upload, stored_file
