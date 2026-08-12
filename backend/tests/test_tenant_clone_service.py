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

from app.models.entities import Participant, Protocol, Template
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import make_participant, make_protocol, make_template, make_tenant


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
