"""Regression tests for TenantCloneService - previously zero test coverage despite doing
the same id-remapping work as TenantExportService/TenantImportService (see
test_tenant_export_import.py), just within a single database instead of via a zip file.

Covers:
- clone_full copies core entities (participant, template, protocol) into a brand new
  tenant with fresh ids that never collide with the source tenant's
- clone_structure copies only config (template) - no participants/protocols
- cloning tenant A never touches an uninvolved tenant B's data
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.entities import (
    ElementDefinition,
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolTodo,
    Template,
)
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import (
    make_element_definition,
    make_event,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def test_clone_full_creates_new_tenant_with_fresh_ids_and_core_content(db):
    source = make_tenant(db, "Quelle")
    template = make_template(db, source.id, name="Vorstandssitzung")
    protocol = make_protocol(db, source.id, template.id, protocol_number="P-1")
    participant = make_participant(db, source.id, display_name="Anna Muster")

    cloned = TenantCloneService().clone_full(db, source.id, "Quelle (Kopie)")

    assert cloned.id != source.id
    assert cloned.name == "Quelle (Kopie)"

    cloned_template = db.scalar(select(Template).where(Template.tenant_id == cloned.id))
    assert cloned_template is not None
    assert cloned_template.id != template.id
    assert cloned_template.name == "Vorstandssitzung"

    cloned_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == cloned.id))
    assert cloned_protocol is not None
    assert cloned_protocol.id != protocol.id
    assert cloned_protocol.protocol_number == "P-1"
    # Must point at the CLONED template's id, not the source tenant's.
    assert cloned_protocol.template_id == cloned_template.id

    cloned_participant = db.scalar(select(Participant).where(Participant.tenant_id == cloned.id))
    assert cloned_participant is not None
    assert cloned_participant.id != participant.id
    assert cloned_participant.display_name == "Anna Muster"

    # The source tenant's own rows are completely untouched by the clone.
    assert db.get(Template, template.id).tenant_id == source.id
    assert db.get(Protocol, protocol.id).tenant_id == source.id
    assert db.get(Participant, participant.id).tenant_id == source.id


def test_clone_structure_copies_config_but_not_operational_data(db):
    source = make_tenant(db, "Quelle")
    make_template(db, source.id, name="Vorstandssitzung")
    make_participant(db, source.id, display_name="Anna Muster")

    cloned = TenantCloneService().clone_structure(db, source.id, "Quelle (Struktur-Kopie)")

    cloned_template = db.scalar(select(Template).where(Template.tenant_id == cloned.id))
    assert cloned_template is not None
    assert cloned_template.name == "Vorstandssitzung"

    # "structure" scope must never copy participants (operational data).
    assert db.scalar(select(Participant).where(Participant.tenant_id == cloned.id)) is None


def test_clone_does_not_affect_an_uninvolved_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    make_template(db, tenant_a.id, name="A-Template")

    bystander = make_tenant(db, "Unbeteiligter Verein")
    bystander_template = make_template(db, bystander.id, name="Bystander Template")
    bystander_protocol = make_protocol(db, bystander.id, bystander_template.id, protocol_number="BYSTANDER-1")
    bystander_participant = make_participant(db, bystander.id, display_name="Bystander Person")

    TenantCloneService().clone_full(db, tenant_a.id, "Tenant A Klon")

    db.expire_all()
    assert db.get(Template, bystander_template.id).name == "Bystander Template"
    assert db.get(Protocol, bystander_protocol.id).protocol_number == "BYSTANDER-1"
    assert db.get(Participant, bystander_participant.id).display_name == "Bystander Person"

    # No stray template ended up attached to the bystander tenant as a side effect.
    assert db.scalar(
        select(Template).where(Template.tenant_id == bystander.id, Template.id != bystander_template.id)
    ) is None


def test_clone_full_of_tenant_with_no_data_still_succeeds(db):
    """Edge case: an essentially empty tenant (no template/protocol/participant at all)
    must still clone cleanly instead of erroring out on an empty id_map somewhere."""
    source = make_tenant(db, "Leerer Verein")

    cloned = TenantCloneService().clone_full(db, source.id, "Leerer Verein (Kopie)")

    assert cloned.id != source.id
    assert db.scalar(select(Template).where(Template.tenant_id == cloned.id)) is None
    assert db.scalar(select(Participant).where(Participant.tenant_id == cloned.id)) is None


def test_clone_full_remaps_matrix_block_list_links(db):
    """A Matrix/Table block's list link lives in element_definition.configuration_json
    ["blocks"][].configuration_json - both the block-level "Quelle: Liste" source
    (auto_source.list_id) and a per-row "Zeile aus Liste" link
    (rows[].row_config.linked_list_id/linked_list_entry_id). Must be re-pointed at the
    cloned list/entry, not left pointing at the source tenant's ids."""
    source = make_tenant(db, "Quelle")
    source_list = make_list_definition(db, source.id, name="Leitende")
    source_entry = make_list_entry(db, source_list.id, column_one_value={"text_value": "Anna"})
    make_element_definition(
        db, source.id, "Matrix",
        blocks=[{
            "id": 1,
            "element_type_id": 11,
            "configuration_json": {
                "mode": "auto",
                "auto_source": {"type": "list", "list_id": source_list.id, "event_tag_filter": None},
                "rows": [{
                    "id": "1",
                    "row_type": "list_entry",
                    "row_config": {"linked_list_id": source_list.id, "linked_list_entry_id": source_entry.id},
                }],
            },
        }],
    )

    cloned = TenantCloneService().clone_full(db, source.id, "Quelle (Kopie)")

    cloned_list = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == cloned.id))
    cloned_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == cloned_list.id))
    cloned_definition = db.scalar(select(ElementDefinition).where(ElementDefinition.tenant_id == cloned.id))
    block_config = cloned_definition.configuration_json["blocks"][0]["configuration_json"]

    assert block_config["auto_source"]["list_id"] == cloned_list.id
    assert block_config["auto_source"]["list_id"] != source_list.id
    row_config = block_config["rows"][0]["row_config"]
    assert row_config["linked_list_id"] == cloned_list.id
    assert row_config["linked_list_entry_id"] == cloned_entry.id
    assert row_config["linked_list_id"] != source_list.id
    assert row_config["linked_list_entry_id"] != source_entry.id


def test_clone_full_remaps_responsible_assignments_and_block_repeat_sources(db):
    """protocol_element.responsible_assignments_snapshot and a block's repeat_source_id
    (Event or ProtocolTodo) used to be copied verbatim - the clone's protocols kept
    pointing at the source tenant's participants/list entries/events/todos."""
    source = make_tenant(db, "Quelle")
    participant = make_participant(db, source.id, "Anna")
    definition = make_list_definition(db, source.id, column_one_value_type="participant")
    entry = make_list_entry(db, definition.id, column_one_value={"participant_id": participant.id})
    event = make_event(db, source.id, title="Lager")
    template = make_template(db, source.id)
    protocol = make_protocol(db, source.id, template.id)
    element = make_protocol_element(db, protocol.id)
    element.responsible_assignments_snapshot = [
        {"participant_id": participant.id, "list_definition_id": definition.id, "list_entry_id": entry.id}
    ]
    todo_block = make_protocol_element_block(db, element.id, {}, sort_index=0, element_type_code="todo")
    todo = make_protocol_todo(db, todo_block.id, tenant_id=source.id)
    make_protocol_element_block(db, element.id, {"repeat_source_type": "event", "repeat_source_id": event.id}, sort_index=1)
    make_protocol_element_block(db, element.id, {"repeat_source_type": "todo", "repeat_source_id": todo.id}, sort_index=2)

    cloned = TenantCloneService().clone_full(db, source.id, "Quelle (Kopie)")

    cloned_element = db.scalar(select(ProtocolElement).join(Protocol).where(Protocol.tenant_id == cloned.id))
    cloned_participant = db.scalar(select(Participant).where(Participant.tenant_id == cloned.id))
    cloned_definition = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == cloned.id))
    cloned_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == cloned_definition.id))
    cloned_event = db.scalar(select(Event).where(Event.tenant_id == cloned.id))
    cloned_todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.tenant_id == cloned.id))
    blocks = db.scalars(
        select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id == cloned_element.id)
        .order_by(ProtocolElementBlock.sort_index)
    ).all()
    assert cloned_element.responsible_assignments_snapshot == [
        {"participant_id": cloned_participant.id, "list_definition_id": cloned_definition.id, "list_entry_id": cloned_entry.id}
    ]
    assert blocks[1].configuration_snapshot_json["repeat_source_id"] == cloned_event.id != event.id
    assert blocks[2].configuration_snapshot_json["repeat_source_id"] == cloned_todo.id != todo.id


def test_clone_full_rewrites_abgabe_element_refs_to_the_cloned_rows(db):
    """element_ref stores "event-<public_id>" - every cloned row gets a fresh public_id, so
    the clone's upload log and todos have to point at the CLONED event."""
    from app.models.entities import SubmissionAssignment, SubmissionUploadLog, TodoStatus

    source = make_tenant(db, "Quelle")
    event = make_event(db, source.id, title="Lager")
    assignment = SubmissionAssignment(
        tenant_id=source.id, title="Fotos", public_slug="fotos", source_type="events", tag_filter="lager",
    )
    db.add(assignment)
    db.flush()
    element_ref = f"event-{event.public_id}"
    db.add_all([
        SubmissionUploadLog(assignment_id=assignment.id, element_ref=element_ref, status="success"),
        ProtocolTodo(
            tenant_id=source.id, task="Fotos hochladen", element_ref=element_ref, submission_assignment_id=assignment.id,
            todo_status_id=db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open")),
        ),
    ])
    db.flush()

    cloned = TenantCloneService().clone_full(db, source.id, "Quelle (Kopie)")

    cloned_event = db.scalar(select(Event).where(Event.tenant_id == cloned.id))
    expected = f"event-{cloned_event.public_id}"
    assert cloned_event.public_id != event.public_id
    assert db.scalar(
        select(SubmissionUploadLog.element_ref).join(SubmissionAssignment).where(SubmissionAssignment.tenant_id == cloned.id)
    ) == expected
    assert db.scalar(select(ProtocolTodo.element_ref).where(ProtocolTodo.tenant_id == cloned.id)) == expected


def test_clone_copies_document_studio_data(db, tmp_path, monkeypatch):
    """Assets (mit Datei), Brand-Profile samt Revisionen, Mandantenvorlagen samt Revisionen,
    Komponenten und Zuweisungen reisen beim Klon mit; alle Verweise zeigen danach auf die
    Kopien, nie auf den Quellmandanten. Systemvorlagen bleiben geteilt."""
    from app.core.config import settings
    from app.documents import brand_service, template_service
    from app.documents.brand import BrandTokens
    from app.documents.layout import TemplateContent
    from app.models import DocumentAsset, DocumentBrand, DocumentComponent, DocumentTemplate, DocumentTemplateAssignment, DocumentTemplateRevision, Template

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    source = make_tenant(db, "Stilquelle")
    template = make_template(db, source.id)
    logo_file = tmp_path / "document_assets" / "src.png"
    logo_file.parent.mkdir(parents=True)
    logo_file.write_bytes(b"logo")
    logo = DocumentAsset(tenant_id=source.id, kind="image", category="logo", name="Logo", storage_path="document_assets/src.png")
    db.add(logo)
    db.flush()
    brand = brand_service.create_brand(db, source.id, name="Vereinsstil", tokens=BrandTokens.model_validate({"assets": {"logo": str(logo.public_id)}}), is_default=True)
    component = DocumentComponent(tenant_id=source.id, name="Kopf", schema_version=1, node_json={"type": "image", "id": "k", "source": {"kind": "asset", "asset_id": str(logo.public_id)}})
    db.add(component)
    db.flush()
    content = TemplateContent.model_validate({"masters": [{"id": "default"}], "body": [{"type": "component_ref", "id": "ref", "component_id": str(component.public_id)}]})
    document_template, _revision = template_service.create_template(db, source.id, name="Jahresbericht", document_type="custom", content=content)
    template_service.publish(db, document_template, user_id=None)
    db.add(DocumentTemplateAssignment(tenant_id=source.id, document_type="protocol", protocol_template_id=template.id, brand_id=brand.id))
    db.flush()

    cloned = TenantCloneService().clone_structure(db, source.id, "Stilquelle (Kopie)")

    new_brand = db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == cloned.id))
    new_logo = db.scalar(select(DocumentAsset).where(DocumentAsset.tenant_id == cloned.id))
    new_template = db.scalar(select(Template).where(Template.tenant_id == cloned.id))
    new_component = db.scalar(select(DocumentComponent).where(DocumentComponent.tenant_id == cloned.id))
    new_document_template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.tenant_id == cloned.id))
    new_assignment = db.scalar(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.tenant_id == cloned.id))
    assert new_brand.id != brand.id and new_brand.is_default
    assert brand_service.tokens_of(brand_service.current_revision(db, new_brand)).assets.logo == new_logo.public_id != logo.public_id
    assert (tmp_path / new_logo.storage_path).read_bytes() == b"logo"
    assert new_component.node_json["source"]["asset_id"] == str(new_logo.public_id)
    published = db.get(DocumentTemplateRevision, new_document_template.published_revision_id)
    assert published.template_id == new_document_template.id
    assert published.content_json["body"][0]["component_id"] == str(new_component.public_id)
    assert new_assignment.protocol_template_id == new_template.id and new_assignment.brand_id == new_brand.id
