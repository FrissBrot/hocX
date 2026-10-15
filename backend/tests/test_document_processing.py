"""Dokumentanlage, Aufträge, Worker-Verarbeitung (echtes LibreOffice), Wiederholungen,
Sperren durch die Virenprüfung, Lease-Verlust, Aufräumen und document_sync (Abgabebox/Backfill)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core.storage import MAIN, get_object_store
from app.models import StoredFile
from app.models.document_entities import (
    Document,
    DocumentExtraction,
    DocumentFile,
    DocumentJob,
    DocumentVersion,
)
from app.services import document_processing_service as processing
from app.services import document_service, document_sync_service
from app.services.documents.convert import soffice_binary
from tests.document_support import FIXTURES, document_storage, gallery_document, put_stored_file, savepoint_rollback, submission_document  # noqa: F401
from tests.factories import make_tenant

OWNER = "test-worker"

pytestmark = pytest.mark.usefixtures("savepoint_rollback")
needs_soffice = pytest.mark.skipif(soffice_binary() is None, reason="LibreOffice nicht installiert")


def _jobs(db, document: Document) -> dict[str, DocumentJob]:
    return {
        job.kind: job
        for job in db.scalars(select(DocumentJob).where(DocumentJob.document_version_id == document.current_version_id))
    }


def _files(db, version_id: int) -> dict[str, DocumentFile]:
    return {row.role: row for row in db.scalars(select(DocumentFile).where(DocumentFile.document_version_id == version_id))}


def _run(db, job: DocumentJob) -> processing.JobOutcome:
    """Wie der Worker: Auftrag übernehmen (nur diesen) und verarbeiten."""
    db.execute(
        update(DocumentJob).where(DocumentJob.id == job.id).values(
            status="running", lease_owner=OWNER, lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            attempts=DocumentJob.attempts + 1,
        )
    )
    # Wie claim_next_job: die Übernahme ist committet, bevor verarbeitet wird (im Test nur der
    # Savepoint) - ein späteres rollback() im Fehlerpfad darf sie nicht zurücknehmen.
    db.commit()
    db.expire_all()
    return processing.process_job(db, job.id, OWNER)


# ── Anlage ────────────────────────────────────────────────────────────────────


def test_docx_upload_creates_one_document_with_version_original_and_two_jobs(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    document = document_service.register_upload(db, stored_file)

    assert document.display_name == "sample.docx" and document.source_kind == "upload"
    version = db.get(DocumentVersion, document.current_version_id)
    assert version.version_number == 1 and version.content_fingerprint == stored_file.checksum_sha256
    assert set(_files(db, version.id)) == {"original"}
    assert {kind: job.status for kind, job in _jobs(db, document).items()} == {"pdf": "queued", "extract": "queued"}
    # Idempotent: zweiter Aufruf legt nichts Neues an.
    assert document_service.register_upload(db, stored_file).id == document.id
    assert db.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == document.id)) == 1


def test_pdf_upload_is_its_own_pdf_and_needs_no_conversion(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.pdf")
    document = document_service.register_upload(db, stored_file)
    files = _files(db, document.current_version_id)
    assert files["pdf"].stored_file_id == stored_file.id and files["pdf"].is_generated is False
    # Der PDF-Auftrag erzeugt bei PDFs nur das Vorschaubild, keine neue PDF-Datei.
    assert set(_jobs(db, document)) == {"pdf", "extract"}


@needs_soffice
def test_pdf_job_for_uploaded_pdf_only_renders_preview(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.pdf")
    document = document_service.register_upload(db, stored_file)
    outcome = _run(db, _jobs(db, document)["pdf"])
    assert (outcome.status, outcome.result) == ("done", "already_pdf")
    files = _files(db, document.current_version_id)
    assert files["pdf"].stored_file_id == stored_file.id
    preview = db.get(StoredFile, files["preview"].stored_file_id)
    assert preview.mime_type == "image/png" and files["preview"].is_generated is True
    assert get_object_store().get_bytes(MAIN, preview.storage_path).startswith(b"\x89PNG")
    # Vorschaubilder sind keine Fotos - von Bildanalyse und Qualitäts-Backfill ausgenommen.
    assert preview.face_analyzed_at is not None and preview.quality_analyzed_at is not None


def test_spreadsheet_gets_pdf_job_but_extraction_is_unsupported(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "kasse.xlsx", b"PK\x03\x04 xlsx")
    document = document_service.register_upload(db, stored_file)
    assert set(_jobs(db, document)) == {"pdf"}
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "unsupported"


@pytest.mark.parametrize("name", ["bild.png", "archiv.zip"])
def test_images_and_archives_never_become_documents(db, document_storage, name):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, name, b"\x89PNG\r\n\x1a\n" if name.endswith(".png") else b"PK\x03\x04")
    assert document_service.register_upload(db, stored_file) is None


# ── Verarbeitung ──────────────────────────────────────────────────────────────


@needs_soffice
def test_pdf_job_converts_docx_and_stores_generated_pdf(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    document = document_service.register_upload(db, stored_file)
    outcome = _run(db, _jobs(db, document)["pdf"])

    assert (outcome.status, outcome.result) == ("done", "converted")
    files = _files(db, document.current_version_id)
    assert files["original"].stored_file_id == stored_file.id  # Original unverändert verknüpft
    pdf = db.get(StoredFile, files["pdf"].stored_file_id)
    assert files["pdf"].is_generated is True
    assert pdf.mime_type == "application/pdf" and pdf.original_name == "sample.pdf" and pdf.tenant_id == tenant.id
    assert pdf.storage_path.startswith(f"documents/tenant-{tenant.id}/{document.public_id}/")
    assert get_object_store().get_bytes(MAIN, pdf.storage_path).startswith(b"%PDF-")
    assert get_object_store().get_bytes(MAIN, stored_file.storage_path) == (FIXTURES / "sample.docx").read_bytes()
    assert files["preview"].is_generated is True


def test_extract_job_reads_original_and_stores_structured_content(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.docx"))
    outcome = _run(db, _jobs(db, document)["extract"])

    assert (outcome.status, outcome.result) == ("done", "extracted")
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "ready" and extraction.parser == "docx" and extraction.schema_version == 1
    assert extraction.content["blocks"][0] == {"type": "heading", "level": 1, "text": "Jahresbericht Pfadi Musterhausen"}
    assert extraction.plain_text.startswith("Jahresbericht Pfadi Musterhausen\n\nGrüße")
    assert extraction.char_count == len(extraction.plain_text)


def test_extraction_does_not_depend_on_pdf_job(db, document_storage):
    """Extraktion läuft direkt auf dem Original - auch wenn die Konvertierung scheitert."""
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    jobs = _jobs(db, document)
    db.execute(update(DocumentJob).where(DocumentJob.id == jobs["pdf"].id).values(status="failed", last_error="kaputt"))
    outcome = _run(db, jobs["extract"])
    assert outcome.result == "extracted"


@needs_soffice
def test_legacy_doc_is_extracted_via_docx_conversion(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.doc"))
    _run(db, _jobs(db, document)["extract"])
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "ready" and extraction.parser == "doc+libreoffice"


def test_scanned_pdf_without_ocr_ends_as_ocr_required(db, document_storage, monkeypatch):
    monkeypatch.setattr("app.services.documents.ocr.ocr_available", lambda: False)
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "scanned.pdf"))
    outcome = _run(db, _jobs(db, document)["extract"])
    assert outcome.result == "ocr_required"
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "ocr_required" and extraction.error == "ocr_unavailable"


def test_scanned_pdf_is_recognized_by_ocr_fallback(db, document_storage):
    from app.services.documents.ocr import ocr_available

    if not ocr_available():
        pytest.skip("Tesseract nicht installiert")
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "scanned.pdf"))
    _run(db, _jobs(db, document)["extract"])
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "ready" and extraction.ocr_applied is True and "Hauptversammlung" in extraction.plain_text


def test_pending_virus_scan_defers_without_counting_an_attempt(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md", scan_status="pending"))
    job = _jobs(db, document)["extract"]
    outcome = _run(db, job)
    db.refresh(job)
    assert outcome.result == "scan_pending"
    assert job.status == "queued" and job.attempts == 0 and job.run_after > datetime.now(UTC)


@pytest.mark.parametrize(("scan_status", "result"), [("infected", "infected"), ("error", "scan_error")])
def test_infected_or_unscannable_original_blocks_processing(db, document_storage, scan_status, result):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md", scan_status=scan_status))
    job = _jobs(db, document)["extract"]
    _run(db, job)
    db.refresh(job)
    assert (job.status, job.result) == ("blocked", result)
    assert db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id)) is None


def test_corrupt_file_is_retried_with_backoff_then_fails(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "kaputt.docx", b"PK\x03\x04 kaputt"))
    job = _jobs(db, document)["extract"]
    job.max_attempts = 2
    db.flush()

    first = _run(db, job)
    db.refresh(job)
    assert first.status == "queued" and job.attempts == 1 and job.run_after > datetime.now(UTC)
    assert job.last_error

    second = _run(db, job)
    db.refresh(job)
    assert second.status == "failed" and job.status == "failed"
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "failed"
    # Das Original bleibt verfügbar.
    assert _files(db, document.current_version_id)["original"].stored_file_id is not None


def test_missing_original_object_is_not_retried_forever(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, stored_file)
    get_object_store().delete(db, MAIN, stored_file.storage_path)
    job = _jobs(db, document)["extract"]
    job.max_attempts = 1
    db.flush()
    outcome = _run(db, job)
    assert outcome.status == "failed" and "fehlt" in outcome.error


def test_lost_lease_discards_result(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    job = _jobs(db, document)["extract"]
    db.execute(update(DocumentJob).where(DocumentJob.id == job.id).values(status="running", lease_owner="anderer-worker"))
    db.flush()
    assert processing.process_job(db, job.id, OWNER).status == "skipped"
    assert db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id)) is None


def test_lease_taken_over_meanwhile_is_detected_despite_loaded_job(db, document_storage):
    """Audit DOCMGMT-001: der Auftrag steckt bereits in der Identity-Map - die Sperrabfrage muss
    trotzdem den aktuellen Owner aus der Datenbank prüfen."""
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    job = _jobs(db, document)["extract"]
    job.status, job.lease_owner = "running", OWNER
    db.flush()
    assert db.get(DocumentJob, job.id).lease_owner == OWNER
    # Übernahme durch einen anderen Worker an der Identity-Map vorbei (wie aus einer anderen Session).
    db.connection().execute(text("UPDATE document_job SET lease_owner = 'anderer-worker' WHERE id = :id"), {"id": job.id})
    with pytest.raises(processing.JobLeaseLost):
        processing._lock_owned_job(db, job.id, OWNER)


def test_oversized_original_without_recorded_size_fails_instead_of_retrying(db, document_storage, monkeypatch):
    """Audit DOCMGMT-002: fehlt file_size_bytes, darf die Grössenüberschreitung nicht als
    vorübergehender Speicherfehler endlos neu versucht werden."""
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, stored_file)
    stored_file.file_size_bytes = None
    job = _jobs(db, document)["extract"]
    db.flush()
    monkeypatch.setattr(processing.settings, "document_max_input_mb", 0)

    outcome = _run(db, job)
    db.refresh(job)
    assert outcome.status == "done" and job.status == "done"
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document.current_version_id))
    assert extraction.status == "failed" and extraction.error == "input_too_large"


def test_claim_takes_queued_jobs_and_recovers_expired_leases(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    job = _jobs(db, document)["extract"]
    # Alle anderen fälligen Aufträge der Test-DB aus dem Weg räumen (Transaktion wird zurückgerollt).
    db.execute(update(DocumentJob).where(DocumentJob.id != job.id).values(status="done"))
    db.flush()

    assert processing.claim_next_job(db, OWNER) == job.id
    db.refresh(job)
    assert job.status == "running" and job.lease_owner == OWNER and job.attempts == 1
    assert processing.claim_next_job(db, "zweiter-worker") is None

    # Worker abgestürzt: Lease abgelaufen -> ein anderer Worker übernimmt.
    db.execute(update(DocumentJob).where(DocumentJob.id == job.id).values(lease_expires_at=datetime.now(UTC) - timedelta(hours=1)))
    db.flush()
    assert processing.claim_next_job(db, "zweiter-worker") == job.id
    db.refresh(job)
    assert job.lease_owner == "zweiter-worker" and job.attempts == 2
    assert processing.renew_lease(db, job.id, OWNER) is False
    assert processing.renew_lease(db, job.id, "zweiter-worker") is True


def test_job_that_keeps_crashing_the_worker_is_given_up(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    job = _jobs(db, document)["extract"]
    db.execute(update(DocumentJob).where(DocumentJob.id == job.id).values(attempts=job.max_attempts))
    db.flush()
    outcome = _run(db, job)
    assert (outcome.status, outcome.result) == ("failed", "too_many_attempts")


def test_tenant_mismatch_is_refused(db, document_storage):
    tenant = make_tenant(db)
    other = make_tenant(db, name="Anderer Verein")
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.md"))
    job = _jobs(db, document)["extract"]
    job.tenant_id = other.id
    job.max_attempts = 1
    db.flush()
    outcome = _run(db, job)
    assert outcome.status == "failed" and "Mandant" in outcome.error
    assert db.scalar(select(DocumentExtraction.status).where(DocumentExtraction.document_version_id == document.current_version_id)) == "failed"


def test_requeue_failed_resets_only_failed_jobs(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.docx"))
    jobs = _jobs(db, document)
    db.execute(update(DocumentJob).where(DocumentJob.id == jobs["pdf"].id).values(status="failed", attempts=5, last_error="x"))
    db.execute(update(DocumentJob).where(DocumentJob.id == jobs["extract"].id).values(status="done", result="extracted"))
    db.flush()
    assert document_service.requeue_failed(db, document) == 1
    db.expire_all()
    jobs = _jobs(db, document)
    assert (jobs["pdf"].status, jobs["pdf"].attempts, jobs["pdf"].last_error) == ("queued", 0, None)
    assert jobs["extract"].status == "done"


# ── Löschen und Aufräumen ─────────────────────────────────────────────────────


@needs_soffice
def test_reconversion_replaces_previous_generated_pdf(db, document_storage):
    tenant = make_tenant(db)
    document = document_service.register_upload(db, gallery_document(db, tenant.id, "sample.rtf"))
    _run(db, _jobs(db, document)["pdf"])
    first = db.get(StoredFile, _files(db, document.current_version_id)["pdf"].stored_file_id)
    first_id, first_key = first.id, first.storage_path
    document_service.enqueue_job(db, db.get(DocumentVersion, document.current_version_id), "pdf", tenant_id=tenant.id, reset=True)
    db.flush()
    _run(db, _jobs(db, document)["pdf"])
    second = _files(db, document.current_version_id)["pdf"]
    assert second.stored_file_id != first_id
    assert db.scalar(select(StoredFile.id).where(StoredFile.id == first_id)) is None
    assert not get_object_store().exists(MAIN, first_key)


@needs_soffice
def test_releasing_the_original_removes_document_and_generated_files(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    document = document_service.register_upload(db, stored_file)
    _run(db, _jobs(db, document)["pdf"])
    pdf = db.get(StoredFile, _files(db, document.current_version_id)["pdf"].stored_file_id)
    pdf_id, pdf_key = pdf.id, pdf.storage_path

    document_service.release_original(db, stored_file.id)
    db.flush()
    assert db.scalar(select(Document.id).where(Document.id == document.id)) is None
    assert db.scalar(select(StoredFile.id).where(StoredFile.id == pdf_id)) is None
    assert not get_object_store().exists(MAIN, pdf_key)
    # Das Original selbst gehört dem Uploadweg und bleibt.
    assert db.scalar(select(StoredFile.id).where(StoredFile.id == stored_file.id)) == stored_file.id


def test_deleting_the_original_directly_is_cleaned_up_by_document_sync(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, stored_file)
    db.flush()
    from app.models import GalleryImage
    from sqlalchemy import delete

    db.execute(delete(GalleryImage).where(GalleryImage.stored_file_id == stored_file.id))
    db.execute(delete(StoredFile).where(StoredFile.id == stored_file.id))  # Cascade auf document_file
    db.flush()
    document_sync_service.run_tick(db)
    assert db.scalar(select(Document.id).where(Document.id == document.id)) is None


def test_orphaned_generated_files_are_removed(db, document_storage):
    tenant = make_tenant(db)
    orphan = put_stored_file(db, tenant.id, "rest.pdf", b"%PDF-1.4 rest")
    orphan.storage_path = f"documents/tenant-{tenant.id}/x/y/rest.pdf"
    get_object_store().put_bytes(db, MAIN, orphan.storage_path, b"%PDF-1.4 rest")
    orphan.created_at = datetime.now(UTC) - timedelta(days=1)
    db.flush()
    removed = document_service.remove_orphaned_generated_files(db, limit=1000)
    assert removed >= 1
    assert db.scalar(select(StoredFile.id).where(StoredFile.id == orphan.id)) is None


# ── document_sync: Abgabebox und Bestand ──────────────────────────────────────


def test_sync_registers_abgabebox_documents_once_and_skips_non_documents(db, document_storage):
    tenant = make_tenant(db)
    _assignment, _upload, report = submission_document(db, tenant.id, "sample.odt")
    _a, _u, photo = submission_document(db, tenant.id, "foto.png", b"\x89PNG\r\n\x1a\n")
    _a, _u, withdrawn = submission_document(db, tenant.id, "sample.rtf", delete_comment="zurückgezogen")
    legacy = gallery_document(db, tenant.id, "sample.pdf")

    document_sync_service.run_tick(db)
    document_sync_service.run_tick(db)  # wiederholbar ohne Duplikate

    def originals(stored_file):
        return db.scalar(
            select(func.count()).select_from(DocumentFile).where(DocumentFile.stored_file_id == stored_file.id, DocumentFile.role == "original")
        )

    assert originals(report) == 1
    assert originals(legacy) == 1
    assert originals(photo) == 0
    assert originals(withdrawn) == 0
    # Die Abgabe-Zuordnung bleibt allein in submission_upload_file - nichts wird kopiert.
    document = document_service.document_for_original(db, report.id)
    assert document.tenant_id == tenant.id and document.display_name == "sample.odt"


def test_abgabebox_original_is_read_from_its_own_namespace(db, document_storage):
    tenant = make_tenant(db)
    _a, _u, report = submission_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, report)
    outcome = _run(db, _jobs(db, document)["extract"])
    assert outcome.result == "extracted"
