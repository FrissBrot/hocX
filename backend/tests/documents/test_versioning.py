"""Versionierung: gleicher Inhalt → gleiche Version, geänderter Inhalt erhöht sie, eine reine
Designänderung (andere Vorlage, anderes Brand-Profil, andere Sprache) nicht; Entwurf und
Abschluss zählen getrennt. Der Design-Hash ändert sich dagegen bei jeder Gestaltungsänderung."""
from __future__ import annotations

import asyncio
from datetime import date

from app.documents import brand_service, service
from app.documents.brand import preset_tokens
from app.documents.service import DocumentRequest
from app.models import DocumentExport, DocumentTemplate, ProtocolText
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


def test_version_rules(db):
    tenant, protocol, text = _setup(db)
    first = _render(db, tenant, protocol)
    assert first.version_label is None  # v0.0 wird nicht angezeigt
    assert first.content_hash

    same = _render(db, tenant, protocol)
    assert same.content_hash == first.content_hash and same.version_label == first.version_label

    db.get(ProtocolText, text.id).content = "Geänderter Stand"
    db.flush()
    changed = _render(db, tenant, protocol)
    assert changed.version_label == "v0.1"

    brand = brand_service.create_brand(db, tenant.id, name="Kompakt", tokens=preset_tokens("compact"))
    formal = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "protocol_formal").one()
    restyled = _render(db, tenant, protocol, brand_id=brand.public_id, template_id=formal.public_id, language="fr")
    assert restyled.version_label == "v0.1" and restyled.content_hash == changed.content_hash
    assert restyled.design_hash != changed.design_hash
    assert restyled.template_id == formal.id and restyled.brand_revision_id == brand_service.current_revision(db, brand).id

    # Eigene Vorlage mit nur einem Teil des Inhalts: Version und Inhalts-Hash bleiben
    short = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "protocol_short").one()
    partial = _render(db, tenant, protocol, template_id=short.public_id)
    assert partial.version_label == "v0.1" and partial.content_hash == changed.content_hash

    protocol.status = "abgeschlossen"
    db.flush()
    final = _render(db, tenant, protocol)
    assert final.version_label == "v1.0"
    db.get(ProtocolText, text.id).content = "Nach Abschluss geändert"
    db.flush()
    final_changed = _render(db, tenant, protocol)
    assert final_changed.version_label == "v1.1"
    assert protocol.version_minor == 1 and protocol.version_final_minor == 1
    assert db.query(DocumentExport).filter(DocumentExport.protocol_id == protocol.id).count() == 7


def test_preview_does_not_persist(db):
    tenant, protocol, _ = _setup(db)
    result = asyncio.run(service.preview(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id), max_pages=1))
    assert result.page_count == 1 and result.pages[0].startswith(b"\x89PNG")
    assert db.query(DocumentExport).filter(DocumentExport.protocol_id == protocol.id).count() == 0
    assert protocol.version_minor == 0


def test_first_final_export_is_v1_0_even_after_content_change(db):
    """TYPST-010: Inhalt nach dem letzten Entwurfs-Export geändert, dann abgeschlossen → v1.0."""
    tenant, protocol, text = _setup(db)
    _render(db, tenant, protocol)
    db.get(ProtocolText, text.id).content = "Kurz vor Abschluss geändert"
    protocol.status = "abgeschlossen"
    db.flush()
    final = _render(db, tenant, protocol)
    assert final.version_label == "v1.0"
    assert protocol.version_final_minor == 0


def test_prepare_does_not_block_event_loop(db, monkeypatch):
    """TYPST-004: prepare() (DB-Abfragen, Bildverarbeitung) läuft im Threadpool; die
    Event-Loop bedient währenddessen andere Aufgaben."""
    import time

    tenant, protocol, _ = _setup(db)
    ticks = 0
    ticks_during_prepare = []

    def slow_prepare(*_args, **_kwargs):
        time.sleep(0.3)
        ticks_during_prepare.append(ticks)
        raise ValueError("unknown_document_type")

    monkeypatch.setattr(service, "prepare", slow_prepare)

    async def ticker():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    async def scenario():
        results = await asyncio.gather(
            service.preview(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id)),
            ticker(),
            return_exceptions=True,
        )
        return results[0]

    outcome = asyncio.run(scenario())
    assert isinstance(outcome, ValueError)
    # Blockierte prepare() die Loop, stünde der Zähler hier noch bei 0.
    assert ticks_during_prepare and ticks_during_prepare[0] >= 10
