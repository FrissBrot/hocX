"""Datenschutz-Audit F (Umsetzungsplan Paket 7): Korrekturweg abgeschlossener Protokolle.
Abschliessen -> zurückstufen -> ändern -> abschliessen: alte Fassung und alte PDFs verschwinden,
die Registereinträge behalten nur den Hash (ohne Titel)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import date

import pytest
from sqlalchemy import select

from app.core.storage import MAIN, get_object_store
from app.models import DocumentExport, DocumentRegistry, ProtocolText, StoredFile
from app.schemas.protocol import ProtocolUpdate
from app.services.protocol_service import ProtocolService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))


def _closed_pdf(db, protocol, status: str) -> tuple[DocumentExport, StoredFile]:
    data = secrets.token_bytes(32)
    key = f"exports/generated/{secrets.token_hex(6)}.pdf"
    get_object_store().put_bytes(db, MAIN, key, data, content_type="application/pdf")
    stored = StoredFile(tenant_id=protocol.tenant_id, original_name="p.pdf", mime_type="application/pdf", storage_path=key, scan_status="clean")
    db.add(stored)
    db.flush()
    export = DocumentExport(tenant_id=protocol.tenant_id, protocol_id=protocol.id, document_type="protocol", title=protocol.title, stored_file_id=stored.id)
    db.add(export)
    db.flush()
    db.add(DocumentRegistry(public_id=export.public_id, tenant_id=protocol.tenant_id, sha256=hashlib.sha256(data).hexdigest(), document_type="protocol",
                            title=protocol.title, status_code=status, source_public_id=protocol.public_id))
    db.flush()
    return export, stored


def test_reclosing_after_a_correction_removes_old_version_and_old_pdf(db):
    tenant = make_tenant(db, "Korrektur")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="K-1", protocol_date=date(2026, 3, 1), status="durchgeführt")
    protocol.title = "Sitzung mit Fehler"
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, configuration_snapshot_json={})
    text = make_protocol_text(db, block.id, content="Falscher Name")
    service = ProtocolService()
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    old_export, old_file = _closed_pdf(db, protocol, "abgeschlossen")
    old_file_id = old_file.id

    service.update_protocol(db, protocol.id, ProtocolUpdate(status="durchgeführt"))
    draft_export, draft_file = _closed_pdf(db, protocol, "durchgeführt")
    text = db.get(ProtocolText, text.id)
    text.tracked_baseline_content, text.tracked_dirty, text.content = "Falscher Name", True, "Richtiger Name"
    db.flush()
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))

    text = db.get(ProtocolText, text.id)
    assert text.tracked_baseline_content is None and text.tracked_dirty is False
    assert db.get(StoredFile, old_file_id) is None
    assert db.scalar(select(DocumentExport.stored_file_id).where(DocumentExport.id == old_export.id)) is None
    old_entry = db.scalar(select(DocumentRegistry).where(DocumentRegistry.public_id == old_export.public_id))
    assert old_entry is not None and old_entry.title is None and old_entry.sha256
    # Das während der Korrektur erzeugte PDF bleibt, bis ein neues es ersetzt.
    assert db.get(StoredFile, draft_file.id) is not None
    assert db.scalar(select(DocumentRegistry.title).where(DocumentRegistry.public_id == draft_export.public_id)) == "Sitzung mit Fehler"


def test_first_close_keeps_existing_pdfs(db):
    tenant = make_tenant(db, "Erstabschluss")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="E-1", protocol_date=date(2026, 3, 1), status="durchgeführt")
    _export, stored = _closed_pdf(db, protocol, "durchgeführt")

    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))

    assert db.get(StoredFile, stored.id) is not None
