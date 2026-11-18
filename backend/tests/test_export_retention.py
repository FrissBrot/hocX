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

from sqlalchemy import select

from app.core.storage import MAIN, get_object_store
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


def _change_text(db, protocol, text: str = "Geänderter Inhalt") -> None:
    from app.models import ProtocolElement, ProtocolElementBlock, ProtocolText

    block_ids = select(ProtocolElementBlock.id).join(ProtocolElement).where(ProtocolElement.protocol_id == protocol.id)
    for row in db.scalars(select(ProtocolText).where(ProtocolText.protocol_element_block_id.in_(block_ids))):
        row.content = text
    db.flush()


def _render(db, tenant, protocol):
    return asyncio.run(service.render(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")))


class _StoredObject:
    """Physischer Zustand eines Exports im Bucket (am Register vorbei, wie vorher der Dateipfad)."""

    def __init__(self, key: str) -> None:
        self.key = key

    def exists(self) -> bool:
        return get_object_store().active_backend().head(MAIN, self.key) is not None


def _path(stored: StoredFile) -> _StoredObject:
    return _StoredObject(stored.storage_path)


def test_repeated_protocol_export_never_piles_up_files(db):
    """Seit 1.4.0: ohne Änderung kommt dasselbe PDF zurück (keine zweite Datei); mit Änderung
    entsteht eine neue Version des Protokoll-Dokuments (Dateien-Tab), die frühere bleibt als
    Version erhalten - nichts wächst unkontrolliert, nichts aus dem Versionsverlauf verschwindet."""
    tenant, protocol = _protocol(db, "RT-1")
    first = _render(db, tenant, protocol)
    first_path, first_file_id = _path(first.stored_file), first.stored_file.id

    again = _render(db, tenant, protocol)
    assert again.export.public_id == first.export.public_id and again.stored_file.id == first_file_id

    _change_text(db, protocol)
    second = _render(db, tenant, protocol)
    assert second.export.public_id != first.export.public_id
    get_object_store().purge_deleted(db)

    # Frühere Version gehört zum Versionsverlauf des Dokuments und bleibt
    assert first_path.exists() and db.get(StoredFile, first_file_id) is not None
    assert _path(second.stored_file).exists()
    exports = db.scalars(select(DocumentExport).where(DocumentExport.protocol_id == protocol.id)).all()
    assert len(exports) == 2
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
