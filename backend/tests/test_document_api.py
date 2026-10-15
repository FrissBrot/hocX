"""Dokument-API und Dateien-Tab: Details/Versionen, Dateien je Rolle, extrahierter Text, erneute
Verarbeitung, Mandantentrennung, Rollen, Virenstatus und die Darstellung im Dateien-Tab
(genau ein Eintrag je Dokument)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, update

from app.api.routes import documents as routes
from app.core.storage import MAIN, get_object_store
from app.models import ProtocolExportCache, StoredFile
from app.models.document_entities import DocumentFile, DocumentJob
from app.services import document_processing_service as processing
from app.services import document_service, protocol_export_document_service
from app.services.file_service import FileService
from tests.document_support import FIXTURES, document_storage, gallery_document, savepoint_rollback, submission_document  # noqa: F401
from tests.factories import make_current_user, make_protocol, make_template, make_tenant

pytestmark = pytest.mark.usefixtures("savepoint_rollback")


def _process_all(db, document) -> None:
    for job in db.scalars(select(DocumentJob).where(DocumentJob.document_version_id == document.current_version_id)).all():
        db.execute(
            update(DocumentJob).where(DocumentJob.id == job.id).values(
                status="running", lease_owner="t", lease_expires_at=datetime.now(UTC) + timedelta(minutes=5), attempts=1,
            )
        )
        db.commit()
        processing.process_job(db, job.id, "t")


def _setup(db, name="sample.md"):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, name)
    document = document_service.register_upload(db, stored_file)
    return tenant, stored_file, document


# ── Details und Inhalte ──────────────────────────────────────────────────────


def test_detail_shows_versions_files_jobs_and_status(db, document_storage):
    tenant, stored_file, document = _setup(db, "sample.pdf")
    user = make_current_user(tenant.id, role="writer")
    detail = routes.get_document(document.public_id, db=db, user=user)
    assert detail.display_name == "sample.pdf" and detail.status == "processing"
    assert len(detail.versions) == 1 and detail.versions[0].is_current
    version = detail.versions[0]
    assert version.original.name == "sample.pdf" and version.pdf.url.endswith("/files/pdf")
    assert version.extract_job.status == "queued" and version.pdf_job.status == "none"

    _process_all(db, document)
    detail = routes.get_document(document.public_id, db=db, user=user)
    assert detail.status == "ready"
    assert detail.versions[0].extraction.status == "ready" and detail.versions[0].extraction.text_url


def test_text_endpoint_returns_plain_markdown_and_structured_content(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.md")
    _process_all(db, document)
    user = make_current_user(tenant.id, role="writer")
    detail = routes.get_document(document.public_id, db=db, user=user)
    version_id = detail.versions[0].id
    plain = routes.get_document_text(document.public_id, version_id, format="plain", db=db, user=user)
    markdown = routes.get_document_text(document.public_id, version_id, format="markdown", db=db, user=user)
    structured = routes.get_document_text(document.public_id, version_id, format="json", db=db, user=user)
    assert plain.text.startswith("Lagerplanung\n\nEinleitung mit **Markdown**.")
    assert markdown.text.startswith("# Lagerplanung\n")
    assert structured.content["schema"] == "hocx.document-content"


def test_file_endpoint_serves_pdf_inline_and_original_as_download(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.pdf")
    user = make_current_user(tenant.id, role="writer")
    version_id = routes.get_document(document.public_id, db=db, user=user).versions[0].id
    inline = routes.get_document_file(document.public_id, version_id, "pdf", request=None, download=False, db=db, user=user)
    assert isinstance(inline, FileResponse)
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.headers["x-content-type-options"] == "nosniff"
    download = routes.get_document_file(document.public_id, version_id, "original", request=None, download=True, db=db, user=user)
    assert download.headers["content-disposition"].startswith("attachment")


def test_non_pdf_original_is_never_served_inline(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.md")
    user = make_current_user(tenant.id, role="writer")
    version_id = routes.get_document(document.public_id, db=db, user=user).versions[0].id
    response = routes.get_document_file(document.public_id, version_id, "original", request=None, download=False, db=db, user=user)
    assert response.headers["content-disposition"].startswith("attachment")
    with pytest.raises(HTTPException) as info:
        routes.get_document_file(document.public_id, version_id, "pdf", request=None, download=False, db=db, user=user)
    assert info.value.status_code == 404  # PDF noch nicht erzeugt


# ── Berechtigungen ───────────────────────────────────────────────────────────


def test_other_tenant_cannot_see_document_files_or_text(db, document_storage):
    _tenant, _stored_file, document = _setup(db, "sample.md")
    _process_all(db, document)
    version_id = document_service.document_for_original(db, _stored_file.id).current_version_id
    from app.models.document_entities import DocumentVersion

    version_public = db.get(DocumentVersion, version_id).public_id
    other = make_tenant(db, name="Fremder Verein")
    intruder = make_current_user(other.id, role="admin")
    for call in (
        lambda: routes.get_document(document.public_id, db=db, user=intruder),
        lambda: routes.get_document_text(document.public_id, version_public, format="plain", db=db, user=intruder),
        lambda: routes.get_document_file(document.public_id, version_public, "original", request=None, download=True, db=db, user=intruder),
        lambda: routes.reprocess_document(document.public_id, db=db, user=intruder),
    ):
        with pytest.raises(HTTPException) as info:
            call()
        assert info.value.status_code == 404


def test_reader_role_gets_no_more_than_on_the_original(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.md")
    reader = make_current_user(tenant.id, role="reader")
    with pytest.raises(HTTPException) as info:
        routes.get_document(document.public_id, db=db, user=reader)
    assert info.value.status_code == 403


def test_abgabebox_documents_require_the_abgabebox_feature(db, document_storage):
    tenant = make_tenant(db)
    _assignment, _upload, stored_file = submission_document(db, tenant.id, "sample.md")
    document = document_service.register_upload(db, stored_file)
    without_feature = make_current_user(tenant.id, role="admin", features=frozenset())
    with pytest.raises(HTTPException) as info:
        routes.get_document(document.public_id, db=db, user=without_feature)
    assert info.value.status_code == 403
    assert routes.get_document(document.public_id, db=db, user=make_current_user(tenant.id, role="writer")).display_name == "sample.md"


def test_version_of_another_document_is_not_reachable(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.md")
    _t2, _s2, other_document = None, None, document_service.register_upload(db, gallery_document(db, tenant.id, "sample.csv"))
    user = make_current_user(tenant.id, role="writer")
    foreign_version = routes.get_document(other_document.public_id, db=db, user=user).versions[0].id
    with pytest.raises(HTTPException) as info:
        routes.get_document_text(document.public_id, foreign_version, format="plain", db=db, user=user)
    assert info.value.status_code == 404


def test_infected_or_unscanned_original_blocks_files_and_text(db, document_storage):
    tenant, stored_file, document = _setup(db, "sample.pdf")
    user = make_current_user(tenant.id, role="writer")
    version_id = routes.get_document(document.public_id, db=db, user=user).versions[0].id
    for scan_status, expected in (("pending", 425), ("infected", 403), ("error", 422)):
        stored_file.scan_status = scan_status
        db.flush()
        with pytest.raises(HTTPException) as info:
            routes.get_document_file(document.public_id, version_id, "pdf", request=None, download=False, db=db, user=user)
        assert info.value.status_code == expected


def test_reprocess_requires_writer_and_requeues_failed_jobs(db, document_storage):
    tenant, _stored_file, document = _setup(db, "sample.md")
    db.execute(update(DocumentJob).where(DocumentJob.document_version_id == document.current_version_id).values(status="failed"))
    db.flush()
    with pytest.raises(HTTPException) as info:
        routes.reprocess_document(document.public_id, db=db, user=make_current_user(tenant.id, role="kassier"))
    assert info.value.status_code == 403
    # PDF- und Extraktionsauftrag waren fehlgeschlagen.
    assert routes.reprocess_document(document.public_id, db=db, user=make_current_user(tenant.id, role="writer")).requeued == 2


def test_every_document_route_requires_authentication():
    from app.core.security import get_current_user

    for route in routes.router.routes:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        assert get_current_user in dependencies, route.path


# ── Dateien-Tab ──────────────────────────────────────────────────────────────


def test_files_tab_lists_one_entry_per_document_with_pdf_preview(db, document_storage):
    tenant, stored_file, document = _setup(db, "sample.pdf")
    gallery_document(db, tenant.id, "archiv.zip", b"PK\x03\x04" + b"\x00" * 30)
    # Eine erzeugte Datei (wie das PDF eines DOCX) darf nie als eigener Eintrag erscheinen.
    generated = StoredFile(tenant_id=tenant.id, original_name="erzeugt.pdf", mime_type="application/pdf", storage_path="documents/x.pdf")
    db.add(generated)
    db.flush()
    db.add(DocumentFile(document_version_id=document.current_version_id, stored_file_id=generated.id, role="pdf", is_generated=True))
    db.execute(
        DocumentFile.__table__.delete().where(
            DocumentFile.document_version_id == document.current_version_id, DocumentFile.role == "pdf",
            DocumentFile.stored_file_id == stored_file.id,
        )
    )
    db.flush()

    items = FileService().list_tenant_files(db, tenant.id, exclude_images=True, limit=100)
    names = sorted(item.original_name for item in items)
    assert names == ["archiv.zip", "sample.pdf"]
    by_name = {item.original_name: item for item in items}
    summary = by_name["sample.pdf"].document
    assert summary is not None and summary.id == document.public_id
    assert summary.pdf_url.endswith("/files/pdf") and summary.version_count == 1
    assert by_name["archiv.zip"].document is None


def test_files_tab_shows_current_protocol_export_once(db, document_storage):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="9/2026")
    files = []
    for body in ("A", "B"):
        key = f"exports/generated/{protocol.id}-{body}.pdf"
        get_object_store().put_bytes(db, MAIN, key, b"%PDF-1.4 " + body.encode(), content_type="application/pdf")
        stored_file = StoredFile(tenant_id=tenant.id, original_name="Protokoll-9-2026.pdf", mime_type="application/pdf", storage_path=key)
        db.add(stored_file)
        db.flush()
        db.add(ProtocolExportCache(protocol_id=protocol.id, export_format="pdf", latex_source=body, generated_file_id=stored_file.id))
        db.flush()
        protocol_export_document_service.record_export(
            db, protocol=protocol, export_format="pdf", stored_file=stored_file, body=body, label=None, created_by=None,
        )
        files.append(stored_file)

    items = FileService().list_tenant_files(db, tenant.id, exclude_images=True, source="protocol_export", limit=100)
    assert [item.id for item in items] == [files[1].public_id]
    item = items[0]
    assert item.source == "protocol_export" and item.ref_label == "9/2026" and item.ref_href == f"/protocols/{protocol.public_id}"
    assert item.document.version_count == 2 and item.document.current_version_number == 2
