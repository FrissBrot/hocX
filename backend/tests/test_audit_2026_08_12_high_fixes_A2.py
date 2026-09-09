"""Regression test for the H10 follow-up finding: _freeze_responsible_titles()
(backend/app/services/protocol_service.py) had the same N+1 per-element db.get() anti-pattern
as export_service.py's title resolution (fixed separately as H10 /
test_audit_2026_08_12_high_fixes_D.py), just for responsible-name labels instead of section
titles. Fixed via the new resolve_responsible_labels_batch() in responsible_label_service.py,
which mirrors resolve_display_section_titles_batch()'s batch IN(...) query pattern."""
from unittest.mock import patch

from app.models.entities import ProtocolElement
from app.services.protocol_service import ProtocolService
from app.services import responsible_label_service
from app.services.responsible_label_service import resolve_responsible_labels_batch
from app.schemas.protocol import ProtocolUpdate
from tests.factories import (
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_tenant,
    make_template,
)


def _make_protocol_with_responsible_elements(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")

    definition = make_list_definition(
        db, tenant.id, column_one_value_type="participant", column_two_value_type="text"
    )
    p1 = make_participant(db, tenant.id, display_name="Alice Muster")
    p2 = make_participant(db, tenant.id, display_name="Bob Beispiel")
    entry1 = make_list_entry(db, definition.id, column_one_value={"participant_id": p1.id})
    entry2 = make_list_entry(db, definition.id, column_one_value={"participant_id": p2.id})

    el1 = make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum 1 (stale)")
    el1.element_title_snapshot = "Traktandum 1"
    el1.responsible_name_display_mode = "display_name"
    el1.responsible_assignments_snapshot = [
        {"list_definition_id": definition.id, "list_entry_id": entry1.id}
    ]

    el2 = make_protocol_element(db, protocol.id, sort_index=1, section_name="Traktandum 2 (stale)")
    el2.element_title_snapshot = "Traktandum 2"
    el2.responsible_name_display_mode = "display_name"
    el2.responsible_assignments_snapshot = [
        {"list_definition_id": definition.id, "list_entry_id": entry2.id}
    ]

    # An element with no responsible assignment must be left completely alone.
    el3 = make_protocol_element(db, protocol.id, sort_index=2, section_name="Traktandum 3 (unaffected)")

    db.add_all([el1, el2, el3])
    db.commit()
    return protocol, el1, el2, el3


def test_freeze_responsible_titles_resolves_correct_labels_and_avoids_per_element_db_get(db):
    protocol, el1, el2, el3 = _make_protocol_with_responsible_elements(db)
    service = ProtocolService()

    with patch(
        "app.services.protocol_service.resolve_responsible_labels_batch",
        wraps=resolve_responsible_labels_batch,
    ) as spy:
        service._freeze_responsible_titles(db, protocol.id, protocol.tenant_id, commit=True)
        # Exactly one batch call for all elements, not one resolve call (and one or more
        # db.get() calls inside it) per element.
        assert spy.call_count == 1
        called_elements = spy.call_args_list[0].args[1]
        assert {e.id for e in called_elements} == {el1.id, el2.id}

    db.refresh(el1)
    db.refresh(el2)
    db.refresh(el3)
    assert el1.section_name_snapshot == "Traktandum 1 (Alice Muster)"
    assert el2.section_name_snapshot == "Traktandum 2 (Bob Beispiel)"
    assert el3.section_name_snapshot == "Traktandum 3 (unaffected)"


def test_status_transition_to_abgeschlossen_freezes_responsible_labels_via_full_flow(db):
    protocol, el1, el2, el3 = _make_protocol_with_responsible_elements(db)
    service = ProtocolService()

    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))

    refreshed = db.get(ProtocolElement, el1.id)
    assert refreshed.section_name_snapshot == "Traktandum 1 (Alice Muster)"
    refreshed2 = db.get(ProtocolElement, el2.id)
    assert refreshed2.section_name_snapshot == "Traktandum 2 (Bob Beispiel)"
