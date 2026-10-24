"""Audit MAIN-BE-004 (aus main übernommen, auf die Dokument-Engine portiert): Ein Protokoll
behält nur die Datei seines neuesten Exports; der Retention-Job gibt alte Dateien samt
StoredFile frei, ausser dem neuesten Export abgeschlossener Protokolle. Exportverlauf und
Dokumentenregister bleiben vollständig. Seit Release 1.2.0 gehören Protokollexporte zudem als
Versionen zu logischen Dokumenten (Dateien-Tab); deren Dateien gibt die Aufbewahrung nie frei,
siehe tests/documents/test_protocol_export_documents.py. (MAIN-BE-013 - LaTeX-Export erhöhte die PDF-Version -
entfällt mit dem TeX-Export; die Engine versioniert über den Inhalts-Hash, siehe TYPST-010.)"""
from __future__ import annotations

import asyncio

import pytest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.storage import get_object_store
from app.documents import service
from app.documents.service import DocumentRequest
from app.models import DocumentExport, DocumentRegistry, StoredFile
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


@pytest.fixture(autouse=True)
def _system_templates(db):
    """Systemvorlagen wie beim App-Start in der Testtransaktion (sonst reihenfolgeabhängig)."""
    from app.documents.system_templates import sync_system_templates

    sync_system_templates(db)
    db.flush()


def _protocol(db, number: str, status: str = "durchgeführt"):
    tenant = make_tenant(db, f"Retention {number}")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=number, protocol_date=date(2026, 5, 1), status=status)
    element = make_protocol_element(db, protocol.id, section_name="Traktandum")
    block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    make_protocol_text(db, block.id, "Inhalt")
    return tenant, protocol


def _render(db, tenant, protocol):
    return asyncio.run(service.render(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")))


def _path(stored: StoredFile) -> Path:
    return Path(settings.storage_root) / stored.storage_path


def test_repeated_protocol_export_keeps_only_the_newest_file(db):
    tenant, protocol = _protocol(db, "RT-1")
    first = _render(db, tenant, protocol)
    first_path, first_file_id = _path(first.stored_file), first.stored_file.id

    second = _render(db, tenant, protocol)
    # S3-008: physisch entfernt erst der Purge-Job nach dem Commit.
    get_object_store().purge_deleted(db)

    assert not first_path.exists() and db.get(StoredFile, first_file_id) is None
    assert _path(second.stored_file).exists()
    exports = db.scalars(select(DocumentExport).where(DocumentExport.protocol_id == protocol.id)).all()
    assert len(exports) == 2 and [export.stored_file_id for export in exports].count(None) == 1
    assert len(db.scalars(select(DocumentRegistry).where(DocumentRegistry.tenant_id == tenant.id)).all()) == 2


def test_sweep_frees_old_files_but_keeps_the_final_pdf_of_closed_protocols(db):
    tenant, open_protocol = _protocol(db, "RT-2")
    closed_tenant, closed_protocol = _protocol(db, "RT-3", status="abgeschlossen")
    old_open = _render(db, tenant, open_protocol)
    final = _render(db, closed_tenant, closed_protocol)
    # Export ohne Protokollbezug: kein logisches Dokument, fällt unter die Frist.
    old_list = asyncio.run(service.render(db, None, tenant.id, DocumentRequest(document_type="todos")))
    long_ago = datetime.now(UTC) - timedelta(days=400)
    for result in (old_open, final, old_list):
        result.export.created_at = long_ago
    db.flush()
    open_path, final_path, list_path = _path(old_open.stored_file), _path(final.stored_file), _path(old_list.stored_file)

    result = service.cleanup_old_generated_exports(db, retention_days=30)
    get_object_store().purge_deleted(db)

    assert result["released"] == 1
    assert not list_path.exists() and db.get(DocumentExport, old_list.export.id).stored_file_id is None
    assert final_path.exists() and db.get(DocumentExport, final.export.id).stored_file_id is not None
    # Aktuelle Version des Protokoll-Dokuments (Dateien-Tab) bleibt trotz Frist.
    assert open_path.exists() and db.get(DocumentExport, old_open.export.id).stored_file_id is not None
