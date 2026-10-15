"""Versionierung: gleicher Inhalt → gleiche Version, geänderter Inhalt erhöht sie, Stilwechsel
allein nicht, Entwurf und Abschluss zählen getrennt."""
from __future__ import annotations

import asyncio
from datetime import date

from app.documents import service, style_service
from app.documents.catalog import BlockSpec
from app.documents.service import DocumentRequest
from app.documents.style_tokens import ExportOptions, default_tokens
from app.models import DocumentExport, DocumentRegistry, ProtocolText
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


def test_explicit_default_blocks_count_as_canonical(db):
    """Der Export-Dialog schickt die Standardblöcke ausdrücklich mit (auch mit Vorgabewerten
    und dem Kontext-Protokoll) – das bleibt ein versionierter Protokoll-Export."""
    tenant, protocol, text = _setup(db)
    first = _render(db, tenant, protocol, blocks=[BlockSpec(type="protocol_element")])
    db.get(ProtocolText, text.id).content = "Geändert"
    db.flush()
    explicit = BlockSpec(type="protocol_element", params={"protocol_id": str(protocol.public_id), "include_session_todos": True, "titles_only": False})
    changed = _render(db, tenant, protocol, blocks=[explicit])
    assert first.document_type == changed.document_type == "protocol"
    assert changed.version_label == "v0.1"


def test_custom_blocks_or_title_do_not_touch_versioning(db):
    """TYPST-001: eigene Blöcke oder ein eigener Titel ergeben einen Protokollauszug ohne
    Version, ohne Quellverweis im Register und ohne Einfluss auf die Versionszähler."""
    tenant, protocol, _ = _setup(db)
    protocol.status = "abgeschlossen"
    db.flush()
    real = _render(db, tenant, protocol)
    assert real.version_label == "v1.0"

    forged = _render(db, tenant, protocol, blocks=[BlockSpec(type="richtext", params={"markdown": "Beschluss: alles anders"})])
    retitled = _render(db, tenant, protocol, options=ExportOptions(title="Eigener Titel"))
    for export in (forged, retitled):
        assert export.document_type == service.PROTOCOL_EXCERPT_TYPE
        assert export.version_label is None and export.version_major is None
        entry = db.query(DocumentRegistry).filter(DocumentRegistry.public_id == export.public_id).one()
        assert entry.document_type == service.PROTOCOL_EXCERPT_TYPE
        assert entry.source_public_id is None and entry.status_code is None and entry.version_label is None
    assert (protocol.version_major, protocol.version_minor, protocol.version_final_minor) == (1, 0, 0)

    # Der nächste echte Export vergleicht weiter mit der echten Fassung: keine neue Version.
    again = _render(db, tenant, protocol)
    assert again.version_label == "v1.0" and again.content_hash == real.content_hash
    newer = db.query(DocumentRegistry).filter(
        DocumentRegistry.source_public_id == protocol.public_id, DocumentRegistry.version_minor > 0
    ).count()
    assert newer == 0


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
