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

from app.models.entities import ElementDefinition, ListDefinition, ListEntry, Participant, Protocol, Template
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import (
    make_element_definition,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
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
