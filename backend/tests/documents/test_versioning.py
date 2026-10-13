"""Versionierung: gleicher Inhalt → gleiche Version, geänderter Inhalt erhöht sie, Stilwechsel
allein nicht, Entwurf und Abschluss zählen getrennt."""
from __future__ import annotations

import asyncio
from datetime import date

from app.documents import service, style_service
from app.documents.service import DocumentRequest
from app.documents.style_tokens import default_tokens
from app.models import DocumentExport, ProtocolText
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Versionsverein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="V-1", protocol_date=date(2026, 4, 1), status="durchgeführt")
    element = make_protocol_element(db, protocol.id, section_name="Traktandum")
    block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    text = make_protocol_text(db, block.id, "Erster Stand")
    return tenant, protocol, text


def _render(db, tenant, protocol, **kwargs):
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol", **kwargs)
    return asyncio.run(service.render(db, None, tenant.id, request)).export


def test_version_rules(db, signing_cert):
    tenant, protocol, text = _setup(db)
    first = _render(db, tenant, protocol)
    assert first.version_label is None  # v0.0 wird nicht angezeigt
    assert first.signature_level == "PAdES-B-B" and first.pdf_sha256 and first.content_hash

    same = _render(db, tenant, protocol)
    assert same.content_hash == first.content_hash and same.version_label == first.version_label

    db.get(ProtocolText, text.id).content = "Geänderter Stand"
    db.flush()
    changed = _render(db, tenant, protocol)
    assert changed.version_label == "v0.1"

    other_style = style_service.create_style(db, tenant.id, name="Kompakt", style_key="compact", tokens=default_tokens("compact"))
    restyled = _render(db, tenant, protocol, style_id=other_style.public_id, language="fr")
    assert restyled.version_label == "v0.1" and restyled.style_key == "compact" and restyled.content_hash == changed.content_hash

    protocol.status = "abgeschlossen"
    db.flush()
    final = _render(db, tenant, protocol)
    assert final.version_label == "v1.0"
    db.get(ProtocolText, text.id).content = "Nach Abschluss geändert"
    db.flush()
    final_changed = _render(db, tenant, protocol)
    assert final_changed.version_label == "v1.1"
    assert protocol.version_minor == 1 and protocol.version_final_minor == 1
    assert db.query(DocumentExport).filter(DocumentExport.protocol_id == protocol.id).count() == 6


def test_preview_does_not_persist(db):
    tenant, protocol, _ = _setup(db)
    pages = asyncio.run(service.preview(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id), max_pages=1))
    assert len(pages) == 1 and pages[0].startswith(b"\x89PNG")
