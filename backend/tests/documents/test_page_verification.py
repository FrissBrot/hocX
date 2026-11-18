"""Prüfseite, Zuordnung über die Dokument-ID (Migration 0185): Seiten-Fingerabdrücke beim Export
und die Funktion verify_document_pages() als restricted Rolle der Abgabebox."""
from __future__ import annotations

import asyncio
import io
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.storage import MAIN, get_object_store
from app.documents import page_fingerprints, service
from app.documents.service import DocumentRequest
from app.models import DocumentRegistry
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant

ROLE = "hocx_abgabebox"
# Gemeinsame Probe mit dem Browser (abgabebox-frontend/lib/pdf-fingerprints.test.ts): ein echtes
# hocX-PDF und die erwarteten Fingerabdrücke - beide Seiten müssen dieselben Werte rechnen.
FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "documents"


def _pages(db, document_id, fingerprints):
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        return db.execute(
            text("SELECT * FROM verify_document_pages(CAST(:id AS uuid), CAST(:fp AS text[]))"), {"id": str(document_id), "fp": fingerprints}
        ).mappings().first()
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


def _entry(db, tenant, fingerprints):
    entry = DocumentRegistry(tenant_id=tenant.id, sha256="e" * 64, document_type="protocol", title="Vorstand", page_fingerprints=fingerprints)
    db.add(entry)
    db.flush()
    return entry


def test_normalization_ignores_spacing_case_and_punctuation():
    assert page_fingerprints.normalize("Seite 1 –\n Größe:  ﬁnal") == page_fingerprints.normalize("seite1größefinal")
    assert page_fingerprints.fingerprint("ID", "Text") == page_fingerprints.fingerprint("id", " text ")
    assert page_fingerprints.fingerprint("id-a", "Text") != page_fingerprints.fingerprint("id-b", "Text")
    assert len(page_fingerprints.fingerprint("id", "x")) == 16


def test_function_answers_only_match_or_mismatch_per_page(db):
    tenant = make_tenant(db, "Seitenprüfung")
    entry = _entry(db, tenant, ["a" * 16, "b" * 16, "c" * 16])

    row = _pages(db, entry.public_id, ["a" * 16, "f" * 16])
    assert row["page_count"] == 3 and row["page_matches"] == [True, False, False]
    assert row["document_id"] == entry.public_id
    # Ohne freigegebene Anzeige der Organisation nur die Zuordnung: kein Titel, Status, Datum,
    # keine Version (es gab keinen Hash-Treffer, die ID allein darf nichts verraten)
    assert row["title"] is None and row["tenant_name"] is None
    assert row["status_code"] is None and row["version_label"] is None and row["created_at"] is None
    assert "sha256" not in row and "page_fingerprints" not in row

    tenant.verify_show_identity = True
    db.flush()
    assert _pages(db, entry.public_id, [])["title"] == "Vorstand"


def test_unknown_id_and_pdfs_without_fingerprints(db):
    tenant = make_tenant(db, "Ältere PDFs")
    old = _entry(db, tenant, None)
    assert _pages(db, uuid.uuid4(), ["a" * 16]) is None
    row = _pages(db, old.public_id, ["a" * 16])
    assert row["document_id"] == old.public_id and row["page_matches"] is None and row["page_count"] is None


def test_restricted_role_cannot_read_the_fingerprints(db):
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        with pytest.raises(Exception, match="permission denied"):
            db.execute(text("SELECT page_fingerprints FROM document_registry LIMIT 1"))
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


def test_export_stores_fingerprints_that_survive_resaving(db):
    from pypdf import PdfReader, PdfWriter

    tenant = make_tenant(db, "Neu gespeichert")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-7", protocol_date=date(2026, 5, 1), status="durchgeführt")
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id, section_name="Traktandum").id, {}, element_type_code="text")
    make_protocol_text(db, block.id, "Die Jahresrechnung wurde einstimmig genehmigt. Größere Ausgaben: keine.")
    result = asyncio.run(service.render(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")))
    entry = db.scalar(select(DocumentRegistry).where(DocumentRegistry.public_id == result.export.public_id))
    pdf = get_object_store().get_bytes(MAIN, result.stored_file.storage_path)

    assert entry.page_fingerprints and entry.page_fingerprints == page_fingerprints.compute(str(entry.public_id), pdf)

    # Neu gespeichert (andere Bytes, gleicher Text): andere Prüfsumme, gleiche Seiten
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    buffer = io.BytesIO()
    writer.write(buffer)
    resaved = buffer.getvalue()
    assert resaved != pdf
    assert page_fingerprints.compute(str(entry.public_id), resaved) == entry.page_fingerprints


def test_shared_fixture_matches_the_browser_rule():
    expected = json.loads((FIXTURE_DIR / "verify-fingerprints.json").read_text())
    pdf = (FIXTURE_DIR / "verify-sample.pdf").read_bytes()
    assert page_fingerprints.compute(expected["document_id"], pdf) == expected["fingerprints"]
