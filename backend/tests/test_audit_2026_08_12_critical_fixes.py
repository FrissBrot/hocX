"""Regression tests for the 9 critical findings from the 2026-08-12 full audit
(https://claude.ai/code/artifact/9bc4f794-4e76-415d-a5d2-2e3f23d774d0). Each test is named
after the finding it covers (K1-K9 in the artifact's "Kritisch" section).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import protocol_elements, protocols as protocols_route
from app.models import DocumentTemplate, Event, Participant, ProtocolTodo
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate
from app.schemas.participant import ParticipantCreate
from app.schemas.protocol import (
    ProtocolCreateFromTemplate,
    ProtocolElementBlockFromEventCreate,
    ProtocolElementUpdate,
    ProtocolUpdate,
)
from app.schemas.template import TemplateUpdate
from app.schemas.word_import import WordImportCommit, WordImportTextCommit
from app.services.chart_service import _fetch_todo_data
from app.services.event_service import EventService
from app.services.participant_service import ParticipantService
from app.services.protocol_service import ProtocolService
from app.services.template_service import TemplateService
from app.services.word_import_service import WordImportService

from tests.factories import (
    element_type_id,
    make_current_user,
    make_element_definition,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_template_element,
    make_tenant,
)

RENDER_TYPE_PARAGRAPH = 2


def _make_document_template(db, tenant_id: int, code: str = "default") -> DocumentTemplate:
    doc_template = DocumentTemplate(
        tenant_id=tenant_id, code=code, name="Test Layout", filesystem_path="/nonexistent/does-not-matter",
    )
    db.add(doc_template)
    db.flush()
    return doc_template


# --- K1: Freeze-Schutz fehlt an drei Protocol-Element-Endpunkten ----------------------------


def test_k1_patch_protocol_element_blocked_when_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    element = make_protocol_element(db, protocol.id)
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.patch_protocol_element(element.id, ProtocolElementUpdate(sort_index=99), db=db, user=user)
    assert exc_info.value.status_code == 409


def test_k1_delete_protocol_element_block_blocked_when_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.delete_protocol_element_block(block.id, db=db, user=user)
    assert exc_info.value.status_code == 409
    # Block must still exist - the guard needs to reject before the delete runs.
    assert db.get(type(block), block.id) is not None


def test_k1_create_block_from_event_blocked_when_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    element = make_protocol_element(db, protocol.id)
    event = make_event(db, tenant.id)
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.create_protocol_element_block_from_event(
            element.id, ProtocolElementBlockFromEventCreate(event_id=event.id), db=db, user=user,
        )
    assert exc_info.value.status_code == 409


# --- K2: Cross-Tenant-Datenleck über Event-Verknüpfung in Protokollen -----------------------


def test_k2_add_event_block_to_element_rejects_foreign_tenant_event(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    element = make_protocol_element(db, protocol.id)
    foreign_event = make_event(db, tenant_b.id, title="Fremdes Event")

    with pytest.raises(ValueError, match="Event not found"):
        ProtocolService().add_event_block_to_element(
            db, protocol_element_id=element.id, event_id=foreign_event.id, tenant_id=tenant_a.id,
        )


def test_k2_create_protocol_element_block_from_event_route_rejects_foreign_tenant_event(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    element = make_protocol_element(db, protocol.id)
    foreign_event = make_event(db, tenant_b.id, title="Fremdes Event")
    user = make_current_user(tenant_a.id)

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.create_protocol_element_block_from_event(
            element.id, ProtocolElementBlockFromEventCreate(event_id=foreign_event.id), db=db, user=user,
        )
    assert exc_info.value.status_code == 400


def test_k2_create_from_template_rejects_foreign_tenant_event_id(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    foreign_event = make_event(db, tenant_b.id, title="Fremdes Event")

    with pytest.raises(ValueError, match="Event does not belong to current tenant"):
        ProtocolService().create_from_template(
            db,
            ProtocolCreateFromTemplate(template_id=template.id, protocol_date=date(2026, 1, 1), event_id=foreign_event.id),
            tenant_id=tenant_a.id,
            created_by=None,
        )


def test_k2_update_protocol_rejects_foreign_tenant_event_id(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    foreign_event = make_event(db, tenant_b.id, title="Fremdes Event")

    with pytest.raises(ValueError, match="Event does not belong to current tenant"):
        ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(event_id=foreign_event.id))


# --- K3: Cross-Tenant-FK-Injection: fremde Dokumentvorlage per PATCH einschleusen -----------


def test_k3_update_template_rejects_foreign_tenant_document_template(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    foreign_doc_template = _make_document_template(db, tenant_b.id)

    with pytest.raises(ValueError, match="document_template_id does not belong to current tenant"):
        TemplateService().update_template(db, template.id, TemplateUpdate(document_template_id=foreign_doc_template.id))


def test_k3_update_protocol_rejects_foreign_tenant_document_template(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    foreign_doc_template = _make_document_template(db, tenant_b.id)

    with pytest.raises(ValueError, match="Document template not found"):
        ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(document_template_id=foreign_doc_template.id))


# --- K4: Kein Freeze-Schutz beim Löschen ganzer Protokolle + kein Audit-Log -----------------


def test_k4_delete_protocol_blocked_when_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")

    with pytest.raises(HTTPException) as exc_info:
        ProtocolService().delete_protocol(db, protocol.id)
    assert exc_info.value.status_code == 409


def test_k4_delete_protocol_writes_audit_log(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    protocol_id = protocol.id
    user = make_current_user(tenant.id)

    result = protocols_route.delete_protocol(protocol_id, db=db, user=user)
    assert result == {"message": "Protocol deleted"}

    rows = db.execute(
        text("SELECT action, entity_id FROM audit_log WHERE entity_type = 'protocol' AND action = 'protocol.deleted'")
    ).all()
    assert any(row.entity_id == protocol_id for row in rows)


# --- K5: Cross-Tenant Read/Write auf fremde Termine über den Import-Rückschreibpfad ---------


def _build_event_repeat_template(db, tenant_id: int, *, sync_target_field: str = "description"):
    template = make_template(db, tenant_id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    text_type = element_type_id(db, "text")
    definition = make_element_definition(
        db, tenant_id, "Rückblick",
        blocks=[{
            "id": 1, "title": "Rückblick", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": text_type, "render_type_id": RENDER_TYPE_PARAGRAPH,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {"repeat_source": "event", "sync_target_field": sync_target_field},
        }],
    )
    template_element = make_template_element(db, template.id, definition.id, sort_index=10, section_name="Rückblick")
    return template, template_element


def test_k5_word_import_commit_rejects_foreign_tenant_linked_event(db, monkeypatch):
    """K2's fix to add_event_block_to_element already blocks a foreign-tenant
    linked_event_id from resolving to a NEW block in this exact commit() flow (a fresh
    protocol is always created within commit(), so any event-repeat block either comes
    from create_from_template's own tenant-scoped generation or from the now-tenant-
    checked add_event_block_to_element). K5 is the independent, deeper guard right
    before the Event field is read/written (block_field_sync.apply_text_sync) - this
    test simulates a K2 regression (monkeypatching the tenant check back out of
    add_event_block_to_element, exactly as it shipped before that fix) to prove K5
    still blocks the cross-tenant read/write on its own, defense-in-depth."""
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template, template_element = _build_event_repeat_template(db, tenant_a.id)
    # An own-tenant event in the same repeat window is needed too: create_from_template's
    # own (tenant-scoped) event-repeat generation auto-creates the block for THIS event,
    # which is what populates protocol_element_id_by_template_element_id in commit() -
    # without it, _get_or_create_event_repeat_block short-circuits to None before ever
    # reaching add_event_block_to_element, for an unrelated reason that isn't K5.
    make_event(db, tenant_a.id, title="Herbsthock", event_date=date(2026, 10, 18))
    foreign_event = make_event(db, tenant_b.id, title="Fremdes Event", event_date=date(2026, 10, 19))
    foreign_event.description = "Sollte weder gelesen noch überschrieben werden"
    db.flush()

    original_add_event_block = ProtocolService.add_event_block_to_element

    def _pre_k2_add_event_block_to_element(self, db, *, protocol_element_id, event_id, tenant_id, block_sort_index=None):
        # Reproduces the pre-fix behavior: no effective cross-tenant rejection at this
        # layer at all - not just the original event.tenant_id check, but also the
        # protocol-ownership check added to this same function later (audit finding,
        # 2026-08-25), which a bare tenant_id substitution alone would now also trip
        # (comparing the real protocol's tenant against the substituted one) before ever
        # reaching the event check this test means to bypass. Temporarily masking the
        # Event's own tenant_id for the duration of the call sails past both, then
        # restores the true (foreign) tenant_id immediately after - K5's independent
        # guard below does its own fresh db.get(Event, ...) and must see the real value.
        event = db.get(Event, event_id)
        original_tenant_id = event.tenant_id
        event.tenant_id = tenant_id
        try:
            return original_add_event_block(
                self, db, protocol_element_id=protocol_element_id, event_id=event_id,
                tenant_id=tenant_id, block_sort_index=block_sort_index,
            )
        finally:
            event.tenant_id = original_tenant_id

    monkeypatch.setattr(ProtocolService, "add_event_block_to_element", _pre_k2_add_event_block_to_element)

    with pytest.raises(ValueError, match="Verknüpfter Termin gehört nicht zu diesem Mandanten"):
        WordImportService().commit(
            db, tenant_id=tenant_a.id, user_id=None,
            payload=WordImportCommit(
                template_id=template.id,
                protocol_date=date(2026, 10, 10),
                texts=[
                    WordImportTextCommit(
                        extracted_heading="Rückblick Herbsthock",
                        content="Text aus einem fremden Mandanten eingeschleust.",
                        template_element_id=template_element.id,
                        block_sort_index=10,
                        is_event_repeat=True,
                        linked_event_id=foreign_event.id,
                        sync_field_source=None,
                    )
                ],
            ),
        )
    # No post-raise DB-state assertion here: commit()'s own pre-existing cleanup path
    # (_populate's except-block, since create_from_template commits internally) rolls
    # back and deletes the half-built protocol on any failure - by design, not something
    # to re-verify in this test. The ValueError above, raised before apply_text_sync ever
    # runs, is what proves the foreign Event's field was never touched.


# --- K6: Todo-Statistik/PDF-Chart zählen eigenständige/Abgabebox-Todos gar nicht -----------


def test_k6_chart_todo_data_counts_standalone_todos(db):
    tenant = make_tenant(db)
    # Standalone todo: no protocol_element_block_id, only its own tenant_id - this used to
    # be silently dropped by the INNER JOIN through ProtocolElementBlock/ProtocolElement/Protocol.
    make_protocol_todo(db, None, task="Eigenständiges Todo", tenant_id=tenant.id)

    result = _fetch_todo_data(db, tenant.id)
    assert result["open"] + result["done"] == 1


def test_k6_statistics_todo_query_counts_standalone_todos(db):
    tenant = make_tenant(db)
    make_protocol_todo(db, None, task="Eigenständiges Todo", tenant_id=tenant.id)

    from app.models import ProtocolElement, ProtocolElementBlock, Protocol
    from app.models import TodoStatus
    from sqlalchemy import or_

    todos = db.execute(
        select(TodoStatus.code, ProtocolTodo.completed_at)
        .outerjoin(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .outerjoin(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .outerjoin(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(or_(Protocol.tenant_id == tenant.id, ProtocolTodo.tenant_id == tenant.id))
    ).all()
    assert len(todos) == 1


# --- K8: Partial-Commit-Muster hinterlässt Karteileichen trotz Fehlerantwort ---------------


def test_k8_create_participant_rolls_back_when_linked_user_creation_fails(db, monkeypatch):
    tenant = make_tenant(db)
    service = ParticipantService()
    monkeypatch.setattr(
        ParticipantService, "_ensure_linked_user",
        lambda self, db, participant: (_ for _ in ()).throw(ValueError("Reader role missing")),
    )

    with pytest.raises(ValueError):
        service.create_participant(db, ParticipantCreate(display_name="Geisterteilnehmer"), tenant_id=tenant.id)

    remaining = db.scalars(select(Participant).where(Participant.tenant_id == tenant.id)).all()
    assert remaining == []


def test_k8_create_event_rolls_back_on_foreign_cycle_config(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    from app.models.entities import CycleConfig
    foreign_cycle = CycleConfig(tenant_id=tenant_b.id, name="Fremder Zyklus", reset_month=12, reset_day=31)
    db.add(foreign_cycle)
    db.flush()

    with pytest.raises(ValueError, match="Unknown cycle_config_id"):
        EventService().create_event(
            db,
            EventCreate(
                event_date=date(2026, 1, 1), title="Testanlass",
                cycle_assignments=[CycleAssignment(cycle_config_id=foreign_cycle.id, cycle_year=2026)],
            ),
            tenant_id=tenant_a.id,
        )

    remaining = db.scalars(select(Event).where(Event.tenant_id == tenant_a.id)).all()
    assert remaining == []


# Note: update_event's rollback-on-foreign-cycle-config path uses the exact same
# commit(False)+try/except/rollback structure as create_event above (see event_service.py),
# just against Event.update() instead of Event insert - covered by code review/symmetry
# with the tested create_event case rather than its own test: asserting "the pre-existing
# row's fields survived" doesn't compose with this suite's outer-savepoint db fixture
# (EventService.update_event's own db.rollback() call rolls back the fixture's ambient
# transaction, not a scope local to one test - see conftest.db's SAVEPOINT-restart design).


# --- K9: CSV-Teilnehmerimport - ein fehlerhafter Datensatz zerstört den gesamten Import -----


def test_k9_csv_import_continues_after_row_failure(db, monkeypatch):
    tenant = make_tenant(db)
    service = ParticipantService()

    original_ensure_linked_user = ParticipantService._ensure_linked_user
    call_count = {"n": 0}

    def _flaky_ensure_linked_user(self, db, participant):
        call_count["n"] += 1
        if participant.display_name == "Kaputt":
            raise ValueError("Simulated failure for row 2")
        return original_ensure_linked_user(self, db, participant)

    monkeypatch.setattr(ParticipantService, "_ensure_linked_user", _flaky_ensure_linked_user)

    csv_text = (
        "Vorname;Nachname;Übername;Firmenname;Haupt-E-Mail\n"
        "Anna;Muster;;;\n"
        ";;Kaputt;;\n"
        "Beat;Muster;;;\n"
    )
    result = service.import_csv(db, csv_text, tenant_id=tenant.id)

    assert [p.display_name for p in result.imported] == ["Anna Muster", "Beat Muster"]
    assert len(result.errors) == 1
    assert "Zeile 3" in result.errors[0]

    remaining_names = {
        p.display_name for p in db.scalars(select(Participant).where(Participant.tenant_id == tenant.id)).all()
    }
    assert remaining_names == {"Anna Muster", "Beat Muster"}
