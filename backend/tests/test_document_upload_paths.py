"""Alle Uploadwege legen logische Dokumente an (Dateien-Tab, Word-Import; Abgabebox über
document_sync, siehe test_document_processing.py), Löschpfade nehmen sie wieder mit."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.models import StoredFile
from app.models.document_entities import Document, DocumentFile, DocumentJob, DocumentVersion
from app.services import document_service, public_id_service
from app.services.file_service import FileService
from app.services.tenant_cleanup_service import TenantCleanupService
from tests.document_support import FIXTURES, document_storage, gallery_document, put_stored_file  # noqa: F401
from tests.factories import make_tenant

service = FileService()


def _document(db, stored_file_id: int) -> Document | None:
    return document_service.document_for_original(db, stored_file_id)


def test_document_upload_in_files_tab_creates_document_and_jobs(db, document_storage):
    tenant = make_tenant(db)
    docx = (FIXTURES / "sample.docx").read_bytes()
    items, errors = asyncio.run(
        service.save_document_uploads(
            db, tenant_id=tenant.id, files=[("bericht.docx", docx), ("archiv.zip", b"PK\x03\x04" + b"\x00" * 30)],
            tags=[], created_by=None,
        )
    )
    assert errors == []
    by_name = {item.original_name: public_id_service.get_by_public_id(db, StoredFile, item.id) for item in items}
    document = _document(db, by_name["bericht.docx"].id)
    assert document is not None and document.display_name == "bericht.docx" and document.tenant_id == tenant.id
    kinds = set(db.scalars(select(DocumentJob.kind).where(DocumentJob.document_version_id == document.current_version_id)))
    assert kinds == {"pdf", "extract"}
    # ZIP bleibt eine normale Datei ohne Dokumentebene.
    assert _document(db, by_name["archiv.zip"].id) is None


def test_word_import_upload_creates_document_without_touching_import(db, document_storage):
    tenant = make_tenant(db)
    stored_file = service.save_word_import_document(
        db, tenant_id=tenant.id, filename="hock.docx", content=(FIXTURES / "sample.docx").read_bytes()
    )
    document = _document(db, stored_file.id)
    assert document is not None and document.display_name == "hock.docx"


def test_deleting_a_direct_upload_removes_its_document(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.pdf")
    document = document_service.register_upload(db, stored_file)
    deleted, errors = service.delete_gallery_images(db, tenant.id, [stored_file.public_id])
    db.flush()
    assert errors == [] and deleted == [stored_file.public_id]
    assert db.scalar(select(Document.id).where(Document.id == document.id)) is None


def test_tenant_cleanup_of_documents_removes_documents_and_generated_files(db, document_storage):
    tenant = make_tenant(db)
    # Ohne Herkunftszeile: der Orphan-Sweep der Bereinigung darf Original und PDF entfernen.
    stored_file = put_stored_file(db, tenant.id, "sample.md", (FIXTURES / "sample.md").read_bytes())
    document = document_service.register_upload(db, stored_file)
    version = db.get(DocumentVersion, document.current_version_id)
    generated = put_stored_file(db, tenant.id, "erzeugt.pdf", b"%PDF-1.4 x")
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=generated.id, role="pdf", is_generated=True))
    db.flush()

    TenantCleanupService()._cleanup_documents(db, tenant.id)
    db.flush()
    assert db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id)) == 0
    assert db.scalar(select(StoredFile.id).where(StoredFile.id == generated.id)) is None
