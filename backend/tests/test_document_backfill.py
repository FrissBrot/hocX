"""Migration bestehender Dateien: Backfill über alle Herkunftstabellen, wiederholbar ohne
Duplikate, ohne Bilder/ZIP/infizierte Dateien, Betriebswerkzeug und Speicherkategorie."""

from __future__ import annotations

from sqlalchemy import func, select, update

from app.models import StoredFile, WordImportDocument
from app.models.document_entities import DocumentFile, DocumentJob
from app.services import document_service, document_sync_service
from app.services.storage_service import StorageService
from app.workers import document_admin
from tests.document_support import FIXTURES, document_storage, gallery_document, put_stored_file, submission_document  # noqa: F401
from tests.factories import make_template, make_tenant


def _originals(db, stored_file: StoredFile) -> int:
    return db.scalar(
        select(func.count()).select_from(DocumentFile).where(DocumentFile.stored_file_id == stored_file.id, DocumentFile.role == "original")
    )


def test_backfill_covers_every_origin_and_skips_non_documents(db, document_storage):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    word = put_stored_file(db, tenant.id, "sample.docx", (FIXTURES / "sample.docx").read_bytes())
    db.add(WordImportDocument(
        tenant_id=tenant.id, template_id=template.id, stored_file_id=word.id, original_filename="sample.docx",
        display_name="sample.docx", status="eingelesen",
    ))
    db.flush()
    upload = gallery_document(db, tenant.id, "sample.odt")
    _a, _u, submission = submission_document(db, tenant.id, "sample.rtf")
    infected = gallery_document(db, tenant.id, "virus.pdf", b"%PDF-1.4", scan_status="infected")
    photo = gallery_document(db, tenant.id, "foto.png", b"\x89PNG\r\n\x1a\n")
    archive = gallery_document(db, tenant.id, "archiv.zip", b"PK\x03\x04")
    orphan = put_stored_file(db, tenant.id, "ohne-herkunft.pdf", b"%PDF-1.4")  # unklare Zuordnung

    for _ in range(2):
        document_sync_service.register_missing_documents(db, limit=10_000)

    assert [_originals(db, f) for f in (word, upload, submission)] == [1, 1, 1]
    assert [_originals(db, f) for f in (infected, photo, archive, orphan)] == [0, 0, 0, 0]


def test_admin_backfill_and_requeue(db, document_storage, capsys, monkeypatch):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.md")
    monkeypatch.setattr(document_admin, "SessionLocal", lambda: _NoClose(db))

    document_admin.main(["backfill", "--batches", "1"])
    document = document_service.document_for_original(db, stored_file.id)
    assert document is not None

    db.execute(update(DocumentJob).where(DocumentJob.document_version_id == document.current_version_id).values(status="failed"))
    db.flush()
    document_admin.main(["requeue", "--kind", "extract", "--tenant", str(tenant.id)])
    statuses = dict(db.execute(
        select(DocumentJob.kind, DocumentJob.status).where(DocumentJob.document_version_id == document.current_version_id)
    ).all())
    assert statuses == {"extract": "queued", "pdf": "failed"}
    document_admin.main(["status"])
    assert "Dokumente:" in capsys.readouterr().out


def test_generated_pdfs_count_as_files_in_storage_usage(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, stored_file)
    generated = put_stored_file(db, tenant.id, "sample.pdf", b"%PDF-1.4 " + b"x" * 1000)
    db.add(DocumentFile(document_version_id=document.current_version_id, stored_file_id=generated.id, role="pdf", is_generated=True))
    db.flush()
    usage = {category.key: category.bytes for category in StorageService().breakdown_for_tenant(db, tenant.id).categories}
    assert usage["files"] == stored_file.file_size_bytes + generated.file_size_bytes
    assert usage["other"] == 0


class _NoClose:
    """SessionLocal-Ersatz: liefert die Test-Session, ohne sie am Ende zu schliessen."""

    def __init__(self, db) -> None:
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_exc) -> None:
        return None
