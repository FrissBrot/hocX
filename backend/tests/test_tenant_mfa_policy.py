"""MFA-Pflicht je Mandant (tenant.require_mfa, Migration 0188).

Durchsetzung zentral in app/core/security.py (get_optional_current_user/get_current_user) und
beim Login über mfa_service.prepare_login (status «setup_required»)."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.requests import Request

from app.api.routes.users import get_mfa_policy, put_mfa_policy
from app.core.config import settings
from app.core.db import get_db
from app.core.security import MFA_SETUP_REQUIRED, build_current_user, create_session_token, get_current_user, get_optional_current_user
from app.main import app
from app.schemas.mfa import TenantMfaPolicyUpdate
from app.services.mfa_service import MfaService
from tests.factories import make_app_user, make_current_user, make_mfa_enrolled_user, make_tenant


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _resolve(db, user_id: int, *, mfa: bool = False):
    request = _request()
    user = get_optional_current_user(request=request, db=db, session_cookie=create_session_token(user_id, mfa_verified=mfa))
    return request, user


def _require(db, tenant, value: bool = True):
    tenant.require_mfa = value
    db.flush()


def test_policy_off_changes_nothing(db):
    tenant = make_tenant(db)
    writer = make_app_user(db, email="writer-off@example.com", tenant_id=tenant.id, role_code="writer")

    _, user = _resolve(db, writer.id)

    assert user is not None and user.tenant_require_mfa is False
    assert MfaService().user_requires_mfa(db, writer.id) is False


def test_policy_on_blocks_user_without_mfa_with_clear_error(db):
    tenant = make_tenant(db)
    writer = make_app_user(db, email="writer-on@example.com", tenant_id=tenant.id, role_code="writer")
    _require(db, tenant)

    request, user = _resolve(db, writer.id)

    assert user is None
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == MFA_SETUP_REQUIRED


def test_policy_on_login_leads_into_mfa_setup(db):
    tenant = make_tenant(db)
    writer = make_app_user(db, email="writer-login@example.com", tenant_id=tenant.id, role_code="writer")
    _require(db, tenant)

    pending = MfaService().prepare_login(db, user=writer, current_user=build_current_user(db, writer), request_host=None)

    assert pending is not None
    assert pending.status == "setup_required"
    assert pending.required is True and pending.required_by_tenant is True


def test_policy_on_user_with_mfa_works_normally(db):
    tenant = make_tenant(db)
    writer, _ = make_mfa_enrolled_user(db, email="writer-mfa@example.com", tenant_id=tenant.id, role_code="writer")
    _require(db, tenant)

    request, user = _resolve(db, writer.id, mfa=True)
    assert user is not None and user.current_tenant_id == tenant.id
    assert get_current_user(request, user) is user

    # Faktor vorhanden, aber Session ohne MFA-Bestätigung: wie bisher keine Session (401).
    request, user = _resolve(db, writer.id, mfa=False)
    assert user is None
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, user)
    assert exc_info.value.status_code == 401


def test_policy_on_cannot_remove_last_own_factor(db):
    tenant = make_tenant(db)
    writer, _ = make_mfa_enrolled_user(db, email="writer-keep@example.com", tenant_id=tenant.id, role_code="writer")
    _require(db, tenant)

    assert MfaService().user_requires_mfa(db, writer.id) is True


def test_other_tenant_is_not_affected(db):
    strict = make_tenant(db, "Strict")
    relaxed = make_tenant(db, "Relaxed")
    make_app_user(db, email="strict@example.com", tenant_id=strict.id, role_code="writer")
    other = make_app_user(db, email="relaxed@example.com", tenant_id=relaxed.id, role_code="writer")
    _require(db, strict)

    _, user = _resolve(db, other.id)

    assert user is not None and user.current_tenant_id == relaxed.id
    assert MfaService().user_requires_mfa(db, other.id) is False


def test_api_answers_mfa_setup_required(db):
    tenant = make_tenant(db)
    writer = make_app_user(db, email="writer-api@example.com", tenant_id=tenant.id, role_code="writer")
    _require(db, tenant)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(settings.auth_session_cookie, create_session_token(writer.id))
        response = client.get("/api/users/me")
        session = client.get("/api/auth/session")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == MFA_SETUP_REQUIRED
    # Endpunkte mit optionalem Login behandeln das Konto als abgemeldet.
    assert session.status_code == 200 and session.json()["authenticated"] is False


def test_switching_requires_access_manage(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        put_mfa_policy(TenantMfaPolicyUpdate(require_mfa=True), db=db, user=writer)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException) as exc_info:
        get_mfa_policy(db=db, user=writer)
    assert exc_info.value.status_code == 403
    db.refresh(tenant)
    assert tenant.require_mfa is False


def test_admin_switches_policy_with_count_and_audit(db):
    tenant = make_tenant(db)
    admin, _ = make_mfa_enrolled_user(db, email="admin-policy@example.com", tenant_id=tenant.id, role_code="admin")
    make_app_user(db, email="no-mfa@example.com", tenant_id=tenant.id, role_code="reader")
    actor = build_current_user(db, admin, mfa_verified=True)

    before = get_mfa_policy(db=db, user=actor)
    assert (before.require_mfa, before.logins_total, before.logins_without_mfa) == (False, 2, 1)

    result = put_mfa_policy(TenantMfaPolicyUpdate(require_mfa=True), db=db, user=actor)

    assert result.require_mfa is True and result.logins_without_mfa == 1
    db.refresh(tenant)
    assert tenant.require_mfa is True
    audit_rows = db.execute(
        text("SELECT details_json FROM audit_log WHERE tenant_id = :tenant_id AND action = 'tenant.mfa_policy_updated'"),
        {"tenant_id": tenant.id},
    ).all()
    assert len(audit_rows) == 1 and audit_rows[0].details_json["require_mfa"] is True

    # Nochmals dasselbe: keine Änderung, kein zweiter Audit-Eintrag.
    put_mfa_policy(TenantMfaPolicyUpdate(require_mfa=True), db=db, user=actor)
    assert db.scalar(
        text("SELECT count(*) FROM audit_log WHERE tenant_id = :tenant_id AND action = 'tenant.mfa_policy_updated'"),
        {"tenant_id": tenant.id},
    ) == 1


def test_enabling_requires_own_factor(db):
    """Einschalten sperrt den Einschaltenden nie aus: ohne eigenen Faktor wird abgelehnt."""
    tenant = make_tenant(db)
    admin = make_app_user(db, email="admin-nomfa@example.com", tenant_id=tenant.id, role_code="admin")
    actor = build_current_user(db, admin, mfa_verified=True)

    with pytest.raises(HTTPException) as exc_info:
        put_mfa_policy(TenantMfaPolicyUpdate(require_mfa=True), db=db, user=actor)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "mfa_policy_own_mfa_missing"
    db.refresh(tenant)
    assert tenant.require_mfa is False
