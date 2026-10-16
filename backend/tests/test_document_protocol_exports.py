"""Protokollexporte als versionierte logische Dokumente: Identität (Protokoll, Exportart),
neue Version nur bei neuem Inhalt, aktuelle Version, Backfill bestehender Exporte in der
richtigen Reihenfolge und Schutz vor der Export-Aufbewahrung."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.storage import MAIN, get_object_store
from app.models import ProtocolExportCache, StoredFile
from app.models.document_entities import Document, DocumentFile, DocumentVersion
from app.services import document_service, protocol_export_document_service, public_id_service
from app.services.export_service import ExportService
from tests.factories import make_protocol_element, make_protocol_element_block, make_protocol_text
from tests.test_export_service import _protocol_with_template_dir

service = ExportService()


def _versions(db, document: Document) -> list[DocumentVersion]:
    return list(
        db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number))
    )


def _protocol_document(db, protocol_id: int, kind: str = "protocol") -> Document | None:
    return db.scalar(select(Document).where(Document.protocol_id == protocol_id, Document.export_kind == kind))


def _pdf_of(db, version: DocumentVersion) -> StoredFile:
    row = db.scalar(select(DocumentFile).where(DocumentFile.document_version_id == version.id, DocumentFile.role == "pdf"))
    return db.get(StoredFile, row.stored_file_id)


def _export(db, protocol):
    return asyncio.run(service.export_pdf(db, protocol.id))


def test_repeated_exports_form_versions_of_one_document(db):
    tenant, _template, protocol = _protocol_with_template_dir(db)
    element = make_protocol_element(db, protocol.id, section_name="Traktandum 1")
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="text")
    text = make_protocol_text(db, block.id, content="Erster Stand.")

    first = _export(db, protocol)
    document = _protocol_document(db, protocol.id)
    assert document is not None and document.tenant_id == tenant.id and document.source_kind == "protocol_export"
    assert [version.version_number for version in _versions(db, document)] == [1]

    # Gleicher Inhalt: keine neue Version, nur die Darstellung wird ersetzt.
    second = _export(db, protocol)
    db.refresh(document)
    versions = _versions(db, document)
    assert len(versions) == 1
    assert _pdf_of(db, versions[0]).public_id == second.generated_file_id

    # Neuer Inhalt: neue Version, die aktuell wird; die alte bleibt in der Historie.
    text.content = "Zweiter Stand mit Beschluss."
    db.flush()
    third = _export(db, protocol)
    db.refresh(document)
    versions = _versions(db, document)
    assert [version.version_number for version in versions] == [1, 2]
    assert document.current_version_id == versions[1].id
    assert versions[0].label is None and versions[1].label == "v0.1"
    assert _pdf_of(db, versions[0]).public_id == second.generated_file_id
    assert _pdf_of(db, versions[1]).public_id == third.generated_file_id
    # Der Export räumt ältere Caches ab (MAIN-BE-004) - die Datei der alten Version bleibt.
    assert get_object_store().exists(MAIN, _pdf_of(db, versions[0]).storage_path)
    assert first.generated_file_id != third.generated_file_id
    # Ein Dokument je Protokoll und Exportart - nicht je Datei.
    assert db.scalar(select(Document.id).where(Document.protocol_id == protocol.id).limit(2).offset(1)) is None


def test_export_version_compares_only_against_same_export_format(db):
    """Ein dazwischen erzeugter LaTeX-Export (anderer Body) darf die Protokollversion nicht hochzählen."""
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    make_protocol_element(db, protocol.id, section_name="Traktandum 1")
    _export(db, protocol)
    service.export_latex(db, protocol.id)
    result = _export(db, protocol)
    assert (result.version_major, result.version_minor) == (0, 0)
    assert len(_versions(db, _protocol_document(db, protocol.id))) == 1


def test_standalone_export_formats_are_accepted_and_kept_apart(db, tmp_path):
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    files = {}
    for export_format in ("pdf-todos", "pdf-todos-open", "pdf-events"):
        key = f"exports/generated/test-{export_format}-{protocol.id}.pdf"
        get_object_store().put_bytes(db, MAIN, key, b"%PDF-1.4 " + export_format.encode(), content_type="application/pdf")
        stored_file = StoredFile(tenant_id=protocol.tenant_id, original_name=f"{export_format}.pdf", mime_type="application/pdf", storage_path=key)
        db.add(stored_file)
        db.flush()
        # Migration 0116: diese Formate scheiterten vorher am CHECK.
        db.add(ProtocolExportCache(protocol_id=protocol.id, export_format=export_format, latex_source="body", generated_file_id=stored_file.id))
        db.flush()
        protocol_export_document_service.record_export(
            db, protocol=protocol, export_format=export_format, stored_file=stored_file, body="body", label=None, created_by=None,
        )
        files[export_format] = stored_file
    kinds = set(db.scalars(select(Document.export_kind).where(Document.protocol_id == protocol.id)))
    assert kinds == {"todos", "todos_open", "events"}


def _legacy_export(db, protocol, body: str, *, minutes_ago: int) -> StoredFile:
    key = f"exports/generated/legacy-{protocol.id}-{minutes_ago}.pdf"
    get_object_store().put_bytes(db, MAIN, key, b"%PDF-1.4 legacy", content_type="application/pdf")
    stored_file = StoredFile(tenant_id=protocol.tenant_id, original_name=f"alt-{minutes_ago}.pdf", mime_type="application/pdf", storage_path=key)
    db.add(stored_file)
    db.flush()
    cache = ProtocolExportCache(protocol_id=protocol.id, export_format="pdf", latex_source=body, generated_file_id=stored_file.id)
    db.add(cache)
    db.flush()
    cache.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db.flush()
    return stored_file


def test_backfill_maps_existing_exports_in_order_and_is_repeatable(db):
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    oldest = _legacy_export(db, protocol, "A", minutes_ago=30)
    same = _legacy_export(db, protocol, "A", minutes_ago=20)
    newest = _legacy_export(db, protocol, "B", minutes_ago=10)

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
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    make_protocol_element(db, protocol.id, section_name="Traktandum 1")
    legacy = _legacy_export(db, protocol, "alter Inhalt", minutes_ago=60)

    result = _export(db, protocol)
    document = _protocol_document(db, protocol.id)
    versions = _versions(db, document)
    assert [_pdf_of(db, version).id for version in versions] == [
        legacy.id, public_id_service.get_by_public_id(db, StoredFile, result.generated_file_id).id
    ]
    assert document.current_version_id == versions[-1].id


def test_backfill_skips_exports_whose_file_is_gone(db):
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    gone = _legacy_export(db, protocol, "A", minutes_ago=10)
    get_object_store().delete(db, MAIN, gone.storage_path)
    protocol_export_document_service.backfill(db, limit=10_000)
    assert _protocol_document(db, protocol.id) is None


def test_export_retention_keeps_files_that_are_document_versions(db):
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    kept = _legacy_export(db, protocol, "A", minutes_ago=5)
    protocol_export_document_service.backfill(db, limit=10_000)
    unreferenced_key = f"exports/generated/unreferenced-{protocol.id}.pdf"
    get_object_store().put_bytes(db, MAIN, unreferenced_key, b"%PDF-1.4 x", content_type="application/pdf")

    store = get_object_store()
    old = time.time() - 400 * 86400
    for key in (kept.storage_path, unreferenced_key):
        os.utime(store.local_path(MAIN, key), (old, old))
    service.cleanup_old_generated_exports(db, retention_days=1)

    assert store.exists(MAIN, kept.storage_path)
    assert not store.exists(MAIN, unreferenced_key)


def test_deleting_an_export_file_removes_only_that_version(db):
    _tenant, _template, protocol = _protocol_with_template_dir(db)
    first = _legacy_export(db, protocol, "A", minutes_ago=20)
    _legacy_export(db, protocol, "B", minutes_ago=10)
    protocol_export_document_service.backfill(db, limit=10_000)
    document = _protocol_document(db, protocol.id)

    document_service.release_original(db, first.id)
    db.flush()
    versions = _versions(db, document)
    assert [version.version_number for version in versions] == [2]
    assert document.current_version_id == versions[0].id
