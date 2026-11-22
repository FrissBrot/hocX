"""Datenschutz-Audit G (Umsetzungsplan Paket 8): Aufbewahrungsfristen je Verein. Standardmässig aus,
Vorschläge per Job, Galeriebilder nur vorschlagen. (Ehemalige Mitglieder sind seit 1.4.0 ab dem
Austritt gesperrt - die frühere Regel «nach X Jahren deaktivieren» entfällt, Migration 0193.)"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, text

from app.api.routes import retention as routes
from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models import GalleryImage, RetentionProposal, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, Tenant
from app.core.trash_scope import include_trashed
from app.services import tenant_retention_service as retention
from tests.factories import make_app_user, make_current_user, make_event, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _proposals(db, tenant_id):
    return {(p.kind, p.subject_id): p for p in db.scalars(select(RetentionProposal).where(RetentionProposal.tenant_id == tenant_id))}


def test_nothing_happens_without_a_policy(db):
    tenant = make_tenant(db, "Ohne Regeln")
    make_app_user(db, email="alt-ohne@example.com", tenant_id=tenant.id).left_at = date(2010, 1, 1)
    db.flush()

    assert retention.refresh_proposals(db, tenant.id) == 0
    assert routes.get_retention_policy(db, make_current_user(tenant.id, role="admin")).unlinked_gallery_years is None


def test_old_submissions_are_deleted_and_gallery_images_stay_a_suggestion(db):
    tenant = make_tenant(db, "Fristen")
    event = make_event(db, tenant.id, title="Altes Lager", event_date=date.today() - timedelta(days=500))
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Lagerfotos", public_slug="frist-fotos", source_type="events", tag_filter="lager", offset_days_after=7)
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted")
    db.add(upload)
    db.flush()
    get_object_store().put_bytes(db, ABGABEBOX, "frist/foto.png", _png(), content_type="image/png")
    submitted = StoredFile(tenant_id=tenant.id, original_name="foto.png", mime_type="image/png", storage_path="frist/foto.png", scan_status="clean")
    get_object_store().put_bytes(db, MAIN, "uploads/frist/alt.png", _png(), content_type="image/png")
    old_image = StoredFile(tenant_id=tenant.id, original_name="alt.png", mime_type="image/png", storage_path="uploads/frist/alt.png", scan_status="clean")
    db.add_all([submitted, old_image])
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=submitted.id))
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=old_image.id))
    db.flush()
    db.execute(text("UPDATE stored_file SET created_at = now() - interval '6 years' WHERE id = :id"), {"id": old_image.id})
    retention.save_policy(db, tenant.id, {"submissions_months": 12, "unlinked_gallery_years": 5, "auto_apply": True})
    db.commit()
    upload_id, submitted_id, image_id = upload.id, submitted.id, old_image.id

    result = retention.run_job(db)

    assert result["applied"] >= 1
    proposals = _proposals(db, tenant.id)
    assert proposals[("submission_upload", upload_id)].status == "applied"
    assert proposals[("gallery_image", image_id)].status == "open"
    assert db.get(SubmissionUpload, upload_id) is None and db.get(StoredFile, submitted_id) is None
    assert db.get(StoredFile, image_id) is not None


def test_proposals_of_another_tenant_cannot_be_decided(db):
    tenant = make_tenant(db, "Eigen")
    other = make_tenant(db, "Fremd")
    get_object_store().put_bytes(db, MAIN, "uploads/fremd/alt.png", _png(), content_type="image/png")
    image = StoredFile(tenant_id=other.id, original_name="alt.png", mime_type="image/png", storage_path="uploads/fremd/alt.png", scan_status="clean")
    db.add(image)
    db.flush()
    db.add(GalleryImage(tenant_id=other.id, stored_file_id=image.id))
    db.flush()
    db.execute(text("UPDATE stored_file SET created_at = now() - interval '6 years' WHERE id = :id"), {"id": image.id})
    retention.save_policy(db, other.id, {"unlinked_gallery_years": 1})
    retention.refresh_proposals(db, other.id)
    foreign = next(iter(_proposals(db, other.id).values()))

    result = routes.decide_retention_proposals(routes.RetentionDecision(ids=[foreign.id], action="apply"), db, make_current_user(tenant.id, role="admin"))

    assert result.missing == 1 and db.get(StoredFile, image.id) is not None


def test_offboarding_reports_tenants_after_contract_end_and_grace_period(db):
    tenant = make_tenant(db, "Gekündigt")
    db.get(Tenant, tenant.id).contract_ends_on = date.today() - timedelta(days=100)
    db.flush()

    due = retention.offboarding_due(db, grace_days=90)
    not_yet = retention.offboarding_due(db, grace_days=120)

    assert tenant.public_id in {row["public_id"] for row in due}
    assert tenant.public_id not in {row["public_id"] for row in not_yet}


def _old_gallery_image(db, tenant_id, key):
    get_object_store().put_bytes(db, MAIN, key, _png(), content_type="image/png")
    image = StoredFile(tenant_id=tenant_id, original_name="alt.png", mime_type="image/png", storage_path=key, scan_status="clean")
    db.add(image)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=image.id))
    db.flush()
    db.execute(text("UPDATE stored_file SET created_at = now() - interval '6 years' WHERE id = :id"), {"id": image.id})
    return image


def test_open_proposal_is_not_applied_after_the_rule_was_relaxed(db):
    """Vorschlag unter einer strengeren Regel entstanden, Regel danach gelockert und Automatik
    eingeschaltet: der Job setzte den veralteten Vorschlag trotzdem um (endgültig gelöscht)."""
    tenant = make_tenant(db, "Gelockert")
    event = make_event(db, tenant.id, title="Lager", event_date=date.today() - timedelta(days=500))
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Berichte", public_slug="gelockert-berichte", source_type="events", tag_filter="lager", offset_days_after=7)
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted")
    db.add(upload)
    db.flush()
    retention.save_policy(db, tenant.id, {"submissions_months": 12, "auto_apply": False})
    retention.refresh_proposals(db, tenant.id)
    assert ("submission_upload", upload.id) in _proposals(db, tenant.id)
    retention.save_policy(db, tenant.id, {"submissions_months": 36, "auto_apply": True})
    db.commit()
    upload_id = upload.id

    retention.run_job(db)

    assert db.get(SubmissionUpload, upload_id) is not None, "Einreichung trotz gelockerter Regel gelöscht"
    assert _proposals(db, tenant.id).get(("submission_upload", upload_id)) is None or (
        _proposals(db, tenant.id)[("submission_upload", upload_id)].status != "applied"
    )


def test_proposal_for_an_image_linked_meanwhile_is_not_applied(db):
    """Bild nach dem Vorschlag einem Termin zugeordnet: «Umsetzen» aus der (veralteten) Liste
    löschte es trotzdem endgültig."""
    tenant = make_tenant(db, "Verknüpft")
    image = _old_gallery_image(db, tenant.id, "uploads/verknuepft/alt.png")
    retention.save_policy(db, tenant.id, {"unlinked_gallery_years": 5})
    retention.refresh_proposals(db, tenant.id)
    proposal = _proposals(db, tenant.id)[("gallery_image", image.id)]
    event = make_event(db, tenant.id, title="Jubiläum", event_date=date.today() - timedelta(days=2200))
    db.execute(text("UPDATE gallery_image SET event_id = :e WHERE stored_file_id = :id"), {"e": event.id, "id": image.id})
    db.commit()
    image_id = image.id

    result = routes.decide_retention_proposals(routes.RetentionDecision(ids=[proposal.id], action="apply"), db, make_current_user(tenant.id, role="admin"))

    assert result.applied == 0
    assert db.get(StoredFile, image_id) is not None, "inzwischen verknüpftes Bild gelöscht"


def test_still_due_proposal_is_applied_even_if_trashed_meanwhile(db):
    tenant = make_tenant(db, "Weiterhin fällig")
    image = _old_gallery_image(db, tenant.id, "uploads/faellig/alt.png")
    retention.save_policy(db, tenant.id, {"unlinked_gallery_years": 5})
    retention.refresh_proposals(db, tenant.id)
    proposal = _proposals(db, tenant.id)[("gallery_image", image.id)]
    db.execute(text("UPDATE stored_file SET deleted_at = now() WHERE id = :id"), {"id": image.id})
    db.commit()
    image_id = image.id

    result = routes.decide_retention_proposals(routes.RetentionDecision(ids=[proposal.id], action="apply"), db, make_current_user(tenant.id, role="admin"))

    assert result.applied == 1
    with include_trashed(db):
        assert db.get(StoredFile, image_id) is None
