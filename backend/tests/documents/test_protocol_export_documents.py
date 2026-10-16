"""Protokollexporte der Dokument-Engine als versionierte logische Dokumente (Dateien-Tab,
feature/document-management, im Release 1.2.0 von protocol_export_cache auf document_export
portiert): Identität (Protokoll, Dokumenttyp), neue Version nur bei neuem Inhalt, Backfill
bestehender Exporte in der richtigen Reihenfolge und Schutz vor der Export-Aufbewahrung."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.storage import MAIN, get_object_store
from app.documents import service
from app.documents.service import DocumentRequest
from app.models import DocumentExport, ProtocolText, StoredFile
from app.models.document_entities import Document, DocumentFile, DocumentVersion
from app.services import document_service, protocol_export_document_service
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Dokumentverein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="D-1", protocol_date=date(2026, 5, 1), status="durchgeführt")
    element = make_protocol_element(db, protocol.id, section_name="Traktandum 1")
    block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    text = make_protocol_text(db, block.id, "Erster Stand.")
    return tenant, protocol, text


def _render(db, tenant, protocol, **kwargs):
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol", **kwargs)
    return asyncio.run(service.render(db, None, tenant.id, request))


def _versions(db, document: Document) -> list[DocumentVersion]:
    return list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number)))


def _protocol_document(db, protocol_id: int, kind: str = "protocol") -> Document | None:
    return db.scalar(select(Document).where(Document.protocol_id == protocol_id, Document.export_kind == kind))


def _pdf_of(db, version: DocumentVersion) -> StoredFile:
    row = db.scalar(select(DocumentFile).where(DocumentFile.document_version_id == version.id, DocumentFile.role == "pdf"))
    return db.get(StoredFile, row.stored_file_id)


def test_repeated_exports_form_versions_of_one_document(db):
    tenant, protocol, text = _setup(db)
    first = _render(db, tenant, protocol)
    document = _protocol_document(db, protocol.id)
    assert document is not None and document.tenant_id == tenant.id and document.source_kind == "protocol_export"
    assert [version.version_number for version in _versions(db, document)] == [1]

    # Gleicher Inhalt: keine neue Version, nur die Darstellung wird ersetzt.
    second = _render(db, tenant, protocol)
    db.refresh(document)
    versions = _versions(db, document)
    assert len(versions) == 1
    assert _pdf_of(db, versions[0]).id == second.stored_file.id

    # Neuer Inhalt: neue Version, die aktuell wird; die alte bleibt in der Historie.
    db.get(ProtocolText, text.id).content = "Zweiter Stand mit Beschluss."
    db.flush()
    third = _render(db, tenant, protocol)
    db.refresh(document)
    versions = _versions(db, document)
    assert [version.version_number for version in versions] == [1, 2]
    assert document.current_version_id == versions[1].id
    assert versions[1].label == "v0.1"
    assert _pdf_of(db, versions[0]).id == second.stored_file.id
    assert _pdf_of(db, versions[1]).id == third.stored_file.id
    # MAIN-BE-004 gibt ältere Exportdateien frei - die Datei der alten Version bleibt erhalten.
    get_object_store().purge_deleted(db)
    assert get_object_store().exists(MAIN, _pdf_of(db, versions[0]).storage_path)
    assert db.get(DocumentExport, second.export.id).stored_file_id == second.stored_file.id
    # Die erste Datei gehört zu keiner Version mehr (ersetzt) und ist freigegeben.
    assert db.get(StoredFile, first.stored_file.id) is None
    # Ein Dokument je Protokoll und Dokumenttyp - nicht je Datei.
    assert db.scalar(select(Document.id).where(Document.protocol_id == protocol.id).limit(2).offset(1)) is None


def test_design_change_does_not_create_a_version(db):
    """Eine andere Sprache (wie Vorlage/Brand-Profil) ändert den kanonischen Protokoll-Hash nicht."""
    tenant, protocol, _ = _setup(db)
    _render(db, tenant, protocol)
    _render(db, tenant, protocol, language="en")
    assert len(_versions(db, _protocol_document(db, protocol.id))) == 1


def _legacy_export(db, tenant, protocol, content_hash: str, *, minutes_ago: int) -> StoredFile:
    key = f"exports/generated/legacy-{protocol.id}-{minutes_ago}.pdf"
    get_object_store().put_bytes(db, MAIN, key, b"%PDF-1.4 legacy", content_type="application/pdf")
    stored_file = StoredFile(tenant_id=tenant.id, original_name=f"alt-{minutes_ago}.pdf", mime_type="application/pdf", storage_path=key)
    db.add(stored_file)
    db.flush()
    export = DocumentExport(
        tenant_id=tenant.id, protocol_id=protocol.id, document_type="protocol", title="Alt", content_hash=content_hash,
        stored_file_id=stored_file.id, options_json={},
    )
    db.add(export)
    db.flush()
    export.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db.flush()
    return stored_file


def test_backfill_maps_existing_exports_in_order_and_is_repeatable(db):
    tenant, protocol, _ = _setup(db)
    oldest = _legacy_export(db, tenant, protocol, "a" * 64, minutes_ago=30)
    same = _legacy_export(db, tenant, protocol, "a" * 64, minutes_ago=20)
    newest = _legacy_export(db, tenant, protocol, "b" * 64, minutes_ago=10)

    protocol_export_document_service.backfill(db, limit=10_000)
    protocol_export_document_service.backfill(db, limit=10_000)

    document = _protocol_document(db, protocol.id)
    versions = _versions(db, document)
    # A, A (gleicher Inhalt -> ersetzt), B
    assert [version.version_number for version in versions] == [1, 2]
    assert _pdf_of(db, versions[0]).id == same.id
    assert _pdf_of(db, versions[1]).id == newest.id
    assert document.current_version_id == versions[1].id
    assert oldest.id not in {_pdf_of(db, version).id for version in versions}


def test_first_new_export_backfills_history_before_appending(db):
    tenant, protocol, _ = _setup(db)
    legacy = _legacy_export(db, tenant, protocol, "c" * 64, minutes_ago=60)

    result = _render(db, tenant, protocol)
    document = _protocol_document(db, protocol.id)
    versions = _versions(db, document)
    assert [_pdf_of(db, version).id for version in versions] == [legacy.id, result.stored_file.id]
    assert document.current_version_id == versions[-1].id


def test_backfill_skips_exports_whose_file_is_gone(db):
    tenant, protocol, _ = _setup(db)
    gone = _legacy_export(db, tenant, protocol, "d" * 64, minutes_ago=10)
    get_object_store().delete(db, MAIN, gone.storage_path)
    get_object_store().purge_deleted(db)
    protocol_export_document_service.backfill(db, limit=10_000)
    assert _protocol_document(db, protocol.id) is None


def test_export_retention_keeps_files_that_are_document_versions(db):
    tenant, protocol, _ = _setup(db)
    kept = _legacy_export(db, tenant, protocol, "e" * 64, minutes_ago=5)
    protocol_export_document_service.backfill(db, limit=10_000)
    export = db.scalar(select(DocumentExport).where(DocumentExport.stored_file_id == kept.id))
    export.created_at = datetime.now(UTC) - timedelta(days=400)
    db.flush()

    result = service.cleanup_old_generated_exports(db, retention_days=1)
    get_object_store().purge_deleted(db)

    assert result["released"] == 0
    assert get_object_store().exists(MAIN, kept.storage_path)
    assert db.get(DocumentExport, export.id).stored_file_id == kept.id


def test_deleting_an_export_file_removes_only_that_version(db):
    tenant, protocol, _ = _setup(db)
    first = _legacy_export(db, tenant, protocol, "f" * 64, minutes_ago=20)
    _legacy_export(db, tenant, protocol, "0" * 64, minutes_ago=10)
    protocol_export_document_service.backfill(db, limit=10_000)
    document = _protocol_document(db, protocol.id)

    document_service.release_original(db, first.id)
    db.flush()
    versions = _versions(db, document)
    assert [version.version_number for version in versions] == [2]
    assert document.current_version_id == versions[0].id
