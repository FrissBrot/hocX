"""Sicherheit & Anmeldungen (Admin-Redesign Phase E): Recht security.read, Vereins-Ansicht,
Sitzungen beenden, Plattform-Endpunkte (Warnungen, Richtlinien ohne Geheimnisse)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import admin_auth_security, auth_security
from app.core.admin_security import require_admin_owner
from app.core.permissions import P, SYSTEM_ROLE_PERMISSIONS
from app.models import Permission, TenantRolePermission
from app.models.auth_security_entities import AuthEvent
from tests.factories import assign_roles, make_app_user, make_current_user, make_tenant, system_role

FORBIDDEN_FIELDS = ("ip", "src_ip_hash", "src_net_hash", "device_hash", "subject_hash", "risk_score")


def test_security_read_exists_and_only_admin_role_has_it(db):
    assert db.scalar(select(Permission).where(Permission.key == "security.read")) is not None
    assert P.SECURITY_READ not in SYSTEM_ROLE_PERMISSIONS.get("writer", frozenset())
    assert P.SECURITY_READ not in SYSTEM_ROLE_PERMISSIONS.get("kassier", frozenset())
    assert P.SECURITY_READ not in SYSTEM_ROLE_PERMISSIONS.get("reader", frozenset())
    assert make_current_user(1, "admin").can(P.SECURITY_READ)
    # Neuer Mandant (Seed-Trigger): keine Standardrolle ausser admin (= alle Rechte) bekommt eine Zeile
    tenant = make_tenant(db, "Seed-Test")
    for code in ("writer", "kassier", "reader"):
        role = system_role(db, tenant.id, code)
        keys = set(db.scalars(select(TenantRolePermission.permission_key).where(TenantRolePermission.role_id == role.id)))
        assert "security.read" not in keys


@pytest.mark.parametrize("role", ["writer", "kassier", "reader"])
def test_activity_requires_security_read(db, role):
    tenant = make_tenant(db, "Ohne Recht")
    with pytest.raises(HTTPException) as exc:
        auth_security.tenant_login_activity(limit=10, db=db, user=make_current_user(tenant.id, role))
    assert exc.value.status_code == 403


def test_access_manage_alone_is_no_longer_enough(db):
    tenant = make_tenant(db, "Nur Zugänge")
    user = make_current_user(tenant.id, permissions=frozenset({"access.manage", "meetings.read"}))
    with pytest.raises(HTTPException) as exc:
        auth_security.tenant_login_activity(limit=10, db=db, user=user)
    assert exc.value.status_code == 403


def _event(db, **values) -> None:
    db.add(AuthEvent(**values))
    db.flush()


def test_activity_shows_only_own_tenant_without_network_data(db):
    own = make_tenant(db, "Eigener Verein")
    other = make_tenant(db, "Fremder Verein")
    member = make_app_user(db, f"own-{uuid.uuid4().hex[:6]}@example.com", tenant_id=own.id, role_code="admin")
    stranger = make_app_user(db, f"other-{uuid.uuid4().hex[:6]}@example.com", tenant_id=other.id, role_code="admin")
    for _ in range(12):
        _event(db, event_type="login.password", outcome="failure", actor_user_id=member.id, tenant_id=own.id,
               subject_hash="s-own", src_net_hash="n-secret", src_ip_hash="ip-secret", device_hash="d-secret")
        _event(db, event_type="login.password", outcome="failure", actor_user_id=stranger.id, tenant_id=other.id, subject_hash="s-other")
    _event(db, event_type="mfa.remove", outcome="success", actor_user_id=member.id, tenant_id=own.id)
    _event(db, event_type="login.locked", outcome="blocked", tenant_id=own.id, subject_hash="s-own")
    _event(db, event_type="login.success", outcome="success", actor_user_id=member.id, tenant_id=own.id, details={"new_device": True})

    result = auth_security.tenant_login_activity(limit=50, db=db, user=make_current_user(own.id, "admin"))

    kinds = {warning["kind"] for warning in result["warnings"]}
    assert {"account_attack", "mfa_removed", "account_locked", "privileged_new_device"} <= kinds
    user_ids = {str(item["user_id"]) for item in result["warnings"] + result["accounts"] + result["events"] if item.get("user_id")}
    assert str(stranger.public_id) not in user_ids
    assert str(member.public_id) in user_ids
    flat = repr(result)
    for secret in ("n-secret", "ip-secret", "d-secret", "s-own"):
        assert secret not in flat
    for item in result["events"] + result["accounts"] + result["warnings"]:
        assert not set(item) & set(FORBIDDEN_FIELDS)


def test_revoke_sessions_needs_access_manage_and_own_tenant(db):
    own = make_tenant(db, "Revoke eigen")
    other = make_tenant(db, "Revoke fremd")
    target_other = make_app_user(db, f"t-{uuid.uuid4().hex[:6]}@example.com", tenant_id=other.id)
    target_own = make_app_user(db, f"o-{uuid.uuid4().hex[:6]}@example.com", tenant_id=own.id)

    with pytest.raises(HTTPException) as exc:
        auth_security.revoke_account_sessions(target_own.public_id, db=db, user=make_current_user(own.id, "writer"))
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        auth_security.revoke_account_sessions(target_other.public_id, db=db, user=make_current_user(own.id, "admin"))
    assert exc.value.status_code == 404

    stale = make_current_user(own.id, "admin")
    stale.auth_time = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(HTTPException) as exc:
        auth_security.revoke_account_sessions(target_own.public_id, db=db, user=stale)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "step_up_required"

    result = auth_security.revoke_account_sessions(target_own.public_id, db=db, user=make_current_user(own.id, "admin"))
    assert result == {"revoked": 0}
    db.refresh(target_own)
    assert target_own.session_revoke_at is not None


def test_revoke_sessions_respects_protection_rule_and_not_self(db):
    """Security-Review M1: access.manage allein genügt nicht, um einen Admin abzumelden (Schutzregel 1),
    und das eigene Konto geht über «Andere Sitzungen abmelden» (behält die aktuelle Sitzung)."""
    tenant = make_tenant(db, "Revoke Schutz")
    admin_target = assign_roles(db, make_app_user(db, f"a-{uuid.uuid4().hex[:6]}@example.com", tenant_id=tenant.id), "admin")
    limited = make_current_user(tenant.id, permissions=frozenset({"access.manage"}))
    with pytest.raises(HTTPException) as exc:
        auth_security.revoke_account_sessions(admin_target.public_id, db=db, user=limited)
    assert exc.value.status_code == 403

    me = make_current_user(tenant.id, "admin", user_id=admin_target.id)
    with pytest.raises(HTTPException) as exc:
        auth_security.revoke_account_sessions(admin_target.public_id, db=db, user=me)
    assert exc.value.status_code == 400


def test_policy_has_no_secrets():
    policy = admin_auth_security.auth_security_policy(_admin=None)
    names = [name for group in policy.values() for name in group]
    assert names, "Richtlinien leer"
    for name in names:
        # Bekannte Nicht-Geheimnisse: Passkey-Grenzen und die Leak-Prüfung (Modus/Schwelle/Timeout)
        lowered = name.lower().replace("passkey", "")
        if lowered in ("password_leak_check", "password_leak_min_count", "password_leak_timeout_seconds"):
            lowered = "leak_check"
        for word in ("secret", "key", "token", "password", "cookie"):
            assert word not in lowered, name
    for group in policy.values():
        for value in group.values():
            assert isinstance(value, (int, float, bool, str))


def test_new_platform_endpoints_are_owner_only():
    from fastapi.routing import APIRoute

    owner_only = {"/auth-security/overview", "/auth-security/alerts", "/auth-security/policy", "/auth-security/summary", "/auth-security/events", "/auth-security/blocks"}
    found = set()
    for route in admin_auth_security.router.routes:
        if isinstance(route, APIRoute) and route.path in owner_only and "GET" in route.methods:
            calls = {dep.call for dep in route.dependant.dependencies}
            assert require_admin_owner in calls, route.path
            found.add(route.path)
    assert found == owner_only


def test_overview_and_alerts_shape(db):
    overview = admin_auth_security.auth_security_overview(db=db, _admin=None)
    for key in ("failures_24h", "failures_prev_24h", "admin_logins_24h", "active_alerts", "open_incidents", "active_blocks"):
        assert key in overview
    alerts = admin_auth_security.auth_security_alerts(db=db, _admin=None)
    assert isinstance(alerts, list)
