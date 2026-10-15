"""Dokumentenregister: jeder Export (nicht die Vorschau) ergibt genau einen Eintrag mit dem SHA-256
der ausgelieferten Bytes; Dokument-ID und Prüf-URL stehen im PDF und im XMP; der Retention-Job
löscht nie Register-Einträge."""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
from datetime import date
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import settings
from app.documents import service
from app.documents.service import DocumentRequest, short_document_id
from app.documents.xmp import HOCX_XMP_NAMESPACE
from app.models import DocumentExport, DocumentRegistry, StoredFile
from tests.documents.conftest import pdf_text
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Registerverein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="R-1", protocol_date=date(2026, 5, 1), status="durchgeführt")
    element = make_protocol_element(db, protocol.id, section_name="Traktandum")
    block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    make_protocol_text(db, block.id, "Inhalt")
    return tenant, protocol


def _render(db, tenant, protocol):
    return asyncio.run(service.render(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")))


def _pdf_bytes(stored: StoredFile) -> bytes:
    return (Path(settings.storage_root) / stored.storage_path).read_bytes()


def test_each_export_registers_the_delivered_bytes(db):
    tenant, protocol = _setup(db)
    result = _render(db, tenant, protocol)
    pdf = _pdf_bytes(result.stored_file)
    entries = db.scalars(select(DocumentRegistry).where(DocumentRegistry.tenant_id == tenant.id)).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.sha256 == hashlib.sha256(pdf).hexdigest() == result.stored_file.checksum_sha256
    assert entry.public_id == result.export.public_id
    assert entry.status_code == "durchgeführt" and entry.document_type == "protocol" and entry.source_public_id == protocol.public_id

    # Kurz-ID und Prüf-URL im sichtbaren Text, volle ID und Prüf-URL im XMP
    text = pdf_text(pdf)
    assert short_document_id(entry.public_id) in text
    assert settings.verify_base_url.split("://", 1)[1] in text
    xmp = PdfReader(io.BytesIO(pdf)).trailer["/Root"]["/Metadata"].get_object().get_data().decode()
    assert HOCX_XMP_NAMESPACE in xmp and f"<hocx:documentId>{entry.public_id}</hocx:documentId>" in xmp
    assert f"<hocx:verifyUrl>{settings.verify_base_url}?id={entry.public_id}</hocx:verifyUrl>" in xmp
    assert "<pdfaid:part>2</pdfaid:part>" in xmp and "<pdfaSchema:prefix>hocx</pdfaSchema:prefix>" in xmp
    # TYPST-011: ohne freigegebene Anzeige keine Mandanten-ID im PDF
    assert not tenant.verify_show_identity and str(tenant.public_id) not in xmp

    tenant.verify_show_identity = True
    db.flush()
    shown = _pdf_bytes(_render(db, tenant, protocol).stored_file)
    shown_xmp = PdfReader(io.BytesIO(shown)).trailer["/Root"]["/Metadata"].get_object().get_data().decode()
    assert f"<hocx:tenantId>{tenant.public_id}</hocx:tenantId>" in shown_xmp


def test_rerender_with_same_content_is_a_separate_entry(db):
    tenant, protocol = _setup(db)
    first = _render(db, tenant, protocol)
    second = _render(db, tenant, protocol)
    assert first.export.version_label == second.export.version_label
    hashes = db.scalars(select(DocumentRegistry.sha256).where(DocumentRegistry.tenant_id == tenant.id)).all()
    assert len(hashes) == 2 and len(set(hashes)) == 2


def test_preview_creates_no_entry(db):
    tenant, protocol = _setup(db)
    pages = asyncio.run(service.preview(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id), max_pages=1))
    assert pages
    assert db.scalar(select(DocumentRegistry).where(DocumentRegistry.tenant_id == tenant.id)) is None
    assert db.scalar(select(DocumentExport).where(DocumentExport.tenant_id == tenant.id)) is None


def test_retention_deletes_files_but_never_registry_entries(db):
    tenant, protocol = _setup(db)
    result = _render(db, tenant, protocol)
    path = Path(settings.storage_root) / result.stored_file.storage_path
    old = path.stat().st_mtime - 400 * 86400
    os.utime(path, (old, old))
    service.cleanup_old_generated_exports(retention_days=30)
    assert not path.exists()
    assert db.scalar(select(DocumentRegistry).where(DocumentRegistry.public_id == result.export.public_id)) is not None


def test_failed_registration_leaves_neither_file_nor_rows(db, monkeypatch):
    tenant, protocol = _setup(db)
    generated = Path(settings.export_root) / service.GENERATED_DIR
    before = set(generated.iterdir()) if generated.is_dir() else set()
    monkeypatch.setattr(service, "DocumentRegistry", lambda **_: (_ for _ in ()).throw(RuntimeError("kaputt")))
    # Der Rollback im Fehlerpfad würde sonst die äussere Testtransaktion beenden.
    monkeypatch.setattr(db, "rollback", lambda: None)
    try:
        _render(db, tenant, protocol)
        raise AssertionError("Render hätte scheitern müssen")
    except RuntimeError as exc:
        assert "kaputt" in str(exc)
    after = set(generated.iterdir()) if generated.is_dir() else set()
    assert after == before
