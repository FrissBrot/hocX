"""Datenschutz-Audit G (Umsetzungsplan Paket 8): Aufbewahrungsfristen je Verein. Standardmässig aus,
Vorschläge per Job, ehemalige Mitglieder nur deaktivieren, Galeriebilder nur vorschlagen."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, text

from app.api.routes import retention as routes
from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models import AppUser, GalleryImage, RetentionProposal, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, Tenant
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
    assert routes.get_retention_policy(db, make_current_user(tenant.id, role="admin")).former_members_years is None


def test_former_members_are_only_deactivated(db):
    tenant = make_tenant(db, "Ehemalige")
    admin = make_app_user(db, email="ehemalige-admin@example.com", tenant_id=tenant.id, role_code="admin")
    former = make_app_user(db, email="ehemalig@example.com", tenant_id=tenant.id, password="ein langes passwort 123")
    former.login_enabled, former.left_at = True, date.today() - timedelta(days=4 * 365)
    recent = make_app_user(db, email="neulich@example.com", tenant_id=tenant.id)
    recent.left_at = date.today() - timedelta(days=100)
    db.flush()
    user = make_current_user(tenant.id, role="admin", user_id=admin.id)
    routes.update_retention_policy(routes.RetentionPolicyUpdate(former_members_years=3), db, user)

    proposals = routes.refresh_retention_proposals(db, user)
    assert [(p.kind, p.label) for p in proposals] == [("former_member", former.display_name)]
    result = routes.decide_retention_proposals(routes.RetentionDecision(ids=[proposals[0].id], action="apply"), db, user)

    person = db.get(AppUser, former.id)
    assert result.applied == 1 and person is not None
    assert person.is_active is False and person.login_enabled is False and person.session_revoke_at is not None
    assert db.get(AppUser, recent.id).is_active is True


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
    person = make_app_user(db, email="fremd-alt@example.com", tenant_id=other.id)
    person.left_at = date(2015, 1, 1)
    db.flush()
    retention.save_policy(db, other.id, {"former_members_years": 1})
    retention.refresh_proposals(db, other.id)
    foreign = next(iter(_proposals(db, other.id).values()))

    result = routes.decide_retention_proposals(routes.RetentionDecision(ids=[foreign.id], action="apply"), db, make_current_user(tenant.id, role="admin"))

    assert result.missing == 1 and db.get(AppUser, person.id).is_active is True
    with pytest.raises(HTTPException) as denied:
        routes.list_retention_proposals(db, make_current_user(tenant.id, role="writer"))
    assert denied.value.status_code == 403


def test_offboarding_reports_tenants_after_contract_end_and_grace_period(db):
    tenant = make_tenant(db, "Gekündigt")
    db.get(Tenant, tenant.id).contract_ends_on = date.today() - timedelta(days=100)
    db.flush()

    due = retention.offboarding_due(db, grace_days=90)
    not_yet = retention.offboarding_due(db, grace_days=120)

    assert tenant.public_id in {row["public_id"] for row in due}
    assert tenant.public_id not in {row["public_id"] for row in not_yet}
