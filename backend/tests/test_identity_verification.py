"""Verifizierung der Organisation: Antrag (Mandanten-Admin), Bestätigung/Ablehnung/Entzug
(Plattform-Admin), automatisches Aufheben bei Namensänderung; Einstellungen der Prüfseite."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.routes import admin_identity_verification as admin_routes
from app.api.routes import document_verification as routes
from app.core.admin_security import CurrentAdmin
from sqlalchemy import text

from app.models import IdentityVerificationRequest, Tenant
from app.models.entities import PlatformAdmin
from app.schemas.user import TenantUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.tenant_service import TenantService
from tests.factories import make_current_user, make_tenant


def _audit_count(db, action: str) -> int:
    return db.scalar(text("SELECT count(*) FROM audit_log WHERE action = :action"), {"action": action})


def _audit_actions(db) -> set[str]:
    return set(db.scalars(text("SELECT action FROM audit_log")).all())


@pytest.fixture
def setup(db, monkeypatch):
    tenant = make_tenant(db, "Musikverein Beispiel")
    admin_row = PlatformAdmin(email="ops@hocx.example", display_name="Ops", password_hash="x", role="owner")
    db.add(admin_row)
    db.flush()
    # Routen committen; der Test läuft in einer äusseren Transaktion
    monkeypatch.setattr(db, "rollback", lambda: None)
    admin = CurrentAdmin(admin_id=admin_row.id, admin_public_id=admin_row.public_id, email=admin_row.email, display_name="Ops")
    return tenant, make_current_user(tenant.id, role="admin"), admin


def test_settings_default_and_update_are_audited(db, setup):
    tenant, user, _ = setup
    state = routes.get_document_verification(db=db, user=user)
    assert state.show_identity is False and state.show_newer_version is True and state.verified_at is None
    assert state.verify_base_url.endswith("/verify")
    state = routes.update_document_verification(routes.DocumentVerificationWrite(show_identity=True), db=db, user=user)
    assert state.show_identity is True and state.show_newer_version is True
    assert _audit_count(db, "document_verification.settings_updated") == 1


def test_only_admins_change_settings_or_request(db, setup):
    tenant, _, _ = setup
    writer = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException):
        routes.update_document_verification(routes.DocumentVerificationWrite(show_identity=True), db=db, user=writer)
    with pytest.raises(HTTPException):
        routes.request_identity_verification(routes.VerificationRequestWrite(message="bitte"), db=db, user=writer)


def test_request_approve_and_reject_flow(db, setup):
    tenant, user, admin = setup
    state = routes.request_identity_verification(routes.VerificationRequestWrite(message="Vereinsregister CHE-123"), db=db, user=user)
    assert state.request.status == "pending" and state.request.tenant_name == "Musikverein Beispiel"
    with pytest.raises(HTTPException) as exc:
        routes.request_identity_verification(routes.VerificationRequestWrite(), db=db, user=user)
    assert exc.value.status_code == 409

    pending = admin_routes.list_identity_verification_requests(status="pending", db=db, _=admin)
    assert [row.tenant_id for row in pending] == [tenant.public_id]
    assert pending[0].message == "Vereinsregister CHE-123"

    # Ablehnen braucht eine Begründung
    with pytest.raises(HTTPException):
        admin_routes.reject_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(note=""), db=db, admin=admin)
    rejected = admin_routes.reject_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(note="Kein Nachweis"), db=db, admin=admin)
    assert rejected.verified_at is None and rejected.requests[0].status == "rejected"
    assert routes.get_document_verification(db=db, user=user).request.decision_note == "Kein Nachweis"

    routes.request_identity_verification(routes.VerificationRequestWrite(message="Statuten angehängt"), db=db, user=user)
    approved = admin_routes.approve_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(note="Statuten geprüft"), db=db, admin=admin)
    assert approved.verified_at is not None and approved.verified_by_email == "ops@hocx.example" and approved.note == "Statuten geprüft"
    actions = _audit_actions(db)
    assert {"identity_verification.requested", "admin.identity_verification_rejected", "admin.identity_verification_approved"} <= actions


def test_withdraw_and_admin_revoke(db, setup):
    tenant, user, admin = setup
    routes.request_identity_verification(routes.VerificationRequestWrite(), db=db, user=user)
    assert routes.withdraw_identity_verification(db=db, user=user).request.status == "withdrawn"
    with pytest.raises(HTTPException):
        routes.withdraw_identity_verification(db=db, user=user)
    admin_routes.approve_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(note="telefonisch"), db=db, admin=admin)
    revoked = admin_routes.revoke_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(note="Missbrauch"), db=db, admin=admin)
    assert revoked.verified_at is None and revoked.revoked_reason == "admin"
    with pytest.raises(HTTPException):
        admin_routes.revoke_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(), db=db, admin=admin)


@pytest.mark.parametrize("by_platform_admin", [False, True])
def test_renaming_a_verified_tenant_revokes_the_verification(db, setup, by_platform_admin):
    tenant, user, admin = setup
    routes.request_identity_verification(routes.VerificationRequestWrite(), db=db, user=user)
    admin_routes.approve_identity_verification(tenant.public_id, admin_routes.AdminVerificationDecision(), db=db, admin=admin)
    if by_platform_admin:
        asyncio.run(AdminTenantService().update_tenant(db, tenant.id, TenantUpdate(name="Ganz anderer Verein"), admin_email=admin.email))
    else:
        result = asyncio.run(TenantService().update_tenant(db, tenant.id, user, TenantUpdate(name="Ganz anderer Verein")))
        assert result.identity_verification_revoked is True
    db.refresh(tenant)
    assert tenant.identity_verified_at is None and tenant.identity_verification_revoked_reason == "name_changed"
    assert _audit_count(db, "identity_verification.revoked") == 1


def test_rename_withdraws_a_pending_request_and_same_name_changes_nothing(db, setup):
    tenant, user, _ = setup
    routes.request_identity_verification(routes.VerificationRequestWrite(), db=db, user=user)
    result = asyncio.run(TenantService().update_tenant(db, tenant.id, user, TenantUpdate(name="Musikverein Beispiel")))
    assert result.identity_verification_revoked is False
    assert db.query(IdentityVerificationRequest).filter_by(tenant_id=tenant.id, status="pending").count() == 1
    asyncio.run(TenantService().update_tenant(db, tenant.id, user, TenantUpdate(name="Neuer Name")))
    assert db.query(IdentityVerificationRequest).filter_by(tenant_id=tenant.id, status="pending").count() == 0
    assert db.get(Tenant, tenant.id).identity_verified_at is None
