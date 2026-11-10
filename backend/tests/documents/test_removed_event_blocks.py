"""Im Editor entfernte Termine einer Serie (manually_hidden) erscheinen nicht im PDF.

«Termin entfernen» blendet die Blöcke nur aus (is_visible_snapshot=False, manually_hidden),
export_visible_snapshot bleibt gesetzt - der Export prüfte nur das und druckte die entfernten
Termine mit ihren leeren Vorgaben (Rückmeldung 2026-11-10, «Rückblick Scharanlass»)."""

from __future__ import annotations

from app.documents.context import BuildContext
from app.documents.providers.protocol import element_blocks
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _event_block(db, element_id: int, *, event_id: int, label: str, text: str, hidden: bool, sort_index: int):
    config = {"repeat_source_type": "event", "repeat_source_id": event_id, "repeat_source_label": label}
    if hidden:
        config["manually_hidden"] = True
    block = make_protocol_element_block(db, element_id, configuration_snapshot_json=config, sort_index=sort_index, element_type_code="text")
    block.title_snapshot = label
    block.is_visible_snapshot = not hidden
    make_protocol_text(db, block.id, content=text)
    return block


def test_removed_event_blocks_are_not_exported(db):
    tenant = make_tenant(db, "Entfernte Termine Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="RT-1")
    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Rückblick Scharanlass")
    _event_block(db, element.id, event_id=1, label="Skills Park", text="Positiv: entfernt", hidden=True, sort_index=0)
    _event_block(db, element.id, event_id=2, label="Aufnahme mit Fightgame", text="Positiv: hat Kindern gefallen", hidden=False, sort_index=1)
    db.flush()

    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    [section] = element_blocks(ctx, protocol)

    exported = str([child.model_dump() for child in section.children])
    assert "Aufnahme mit Fightgame" in exported
    assert "hat Kindern gefallen" in exported
    assert "Skills Park" not in exported
    assert "entfernt" not in exported
