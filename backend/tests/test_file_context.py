"""Datei-Kontexte (Migration 0189, Plan «Berechtigungen» Phase 2): die Datenbank ordnet jede Datei
einem Kontext zu (abgabe > protokoll > album > ablage) und hält ihn beim Verknüpfen aktuell; der
Probelauf-Bericht zeigt die Zuordnung, ohne zu schreiben."""
from __future__ import annotations

from sqlalchemy import select

from app.models import GalleryImage, ProtocolImage, StoredFile, SubmissionAssignment
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services import file_context_service
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


def _file(db, tenant_id: int, name: str) -> StoredFile:
    stored = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=f"uploads/{name}")
    db.add(stored)
    db.flush()
    return stored


def _context(db, stored: StoredFile) -> tuple[str, int | None]:
    db.refresh(stored)
    return stored.context_type, stored.context_id


def test_new_file_is_storage_and_links_set_the_context(db):
    tenant = make_tenant(db, "Kontext")
    loose = _file(db, tenant.id, "lose.pdf")
    assert _context(db, loose) == ("ablage", None)

    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, {})
    in_protocol = _file(db, tenant.id, "protokoll.jpg")
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=in_protocol.id, sort_index=0))
    db.flush()
    assert _context(db, in_protocol) == ("protokoll", protocol.id)

    photo = _file(db, tenant.id, "galerie.jpg")
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=photo.id))
    db.flush()
    assert _context(db, photo) == ("album", None)

    # Dasselbe Galerie-Foto zusätzlich im Protokoll: primärer Kontext wird protokoll
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=photo.id, sort_index=1))
    db.flush()
    assert _context(db, photo) == ("protokoll", protocol.id)


def test_submitted_photo_belongs_to_the_submission(db):
    tenant = make_tenant(db, "Abgabe-Kontext")
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    created = SubmissionService().create_assignment(
        db, SubmissionAssignmentCreate(title="Fotos", public_slug="fotos", source_type="manual", link_ids=[link.id]), tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    photo = _file(db, tenant.id, "abgabe.jpg")
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=photo.id, submission_assignment_id=assignment.id))
    db.flush()
    assert _context(db, photo) == ("abgabe", assignment.id)


def test_report_counts_without_writing_and_finds_no_mismatch(db):
    tenant = make_tenant(db, "Bericht")
    other = make_tenant(db, "Fremd")
    _file(db, tenant.id, "a.pdf")
    _file(db, tenant.id, "b.pdf")
    _file(db, other.id, "fremd.pdf")
    result = file_context_service.report(db, tenant_id=tenant.id)
    assert result.counts["ablage"] == 2 and result.mismatched == 0
    assert {name for _id, name in result.storage_files} == {"a.pdf", "b.pdf"}
    assert file_context_service.context_of(db, result.storage_files[0][0]) == ("ablage", None)
