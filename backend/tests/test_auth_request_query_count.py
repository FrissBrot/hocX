"""Grundlast je angemeldeter Anfrage (Performance-Audit Protokoll-Editor 2026-11-22, B2).

Konto, Mandant, Session, MFA-Faktor und Features kommen in einer Abfrage, Rollen samt
Rollen-MFA-Pflicht in einer zweiten, danach setzt die Session den RLS-Kontext. Die Prüfungen
selbst bleiben unverändert und werden nicht zwischengespeichert: jede Anfrage sieht Widerruf,
Deaktivierung, Austritt und neue MFA-Pflicht sofort (Tests unten).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import event, text, update

from app.auth_security import sessions
from app.core.security import create_session_token, get_optional_current_user
from app.core.tenant_scope import bound_tenant_id
from app.models import AuthSession, TenantRole, UserMfaFactor
from tests.factories import make_app_user, make_tenant

# Konto+Mandant+Session+Faktor+Features, Rollen, set_config (RLS)
MAX_STATEMENTS = 3


def _statements(db, call):
    seen: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        seen.append(statement)

    db.flush()
    db.expire_all()
    engine = db.connection().engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return seen, result


def _user_with_session(db, email: str, *, role_code: str = "writer"):
    tenant = make_tenant(db, f"Grundlast {email}")
    user = make_app_user(db, email=email, tenant_id=tenant.id, role_code=role_code)
    record = sessions.create(db, user_id=user.id, tenant_id=tenant.id, mfa=False, amr=["pwd"])
    db.flush()
    return tenant, user, record, create_session_token(user.id, sid=str(record.id))


def _resolve(db, token):
    return get_optional_current_user(request=None, db=db, session_cookie=token)


def test_session_lookup_needs_three_statements(db):
    tenant, user, _record, token = _user_with_session(db, "grundlast@example.com")
    statements, current = _statements(db, lambda: _resolve(db, token))
    assert current is not None and current.user_id == user.id
    assert current.current_tenant_id == tenant.id
    assert current.current_tenant_features, "Features müssen aus der kombinierten Abfrage kommen"
    assert current.role_requires_mfa is False
    assert bound_tenant_id(db) == tenant.id
    assert len(statements) <= MAX_STATEMENTS, statements
    assert "set_config" in statements[-1]


def test_checks_still_apply_on_every_request(db):
    _tenant, user, record, token = _user_with_session(db, "grundlast-widerruf@example.com")
    assert _resolve(db, token) is not None

    # Einzelne Session widerrufen
    db.execute(update(AuthSession).where(AuthSession.id == record.id).values(revoked_at=datetime.now(UTC)))
    db.expire_all()
    assert _resolve(db, token) is None
    db.execute(update(AuthSession).where(AuthSession.id == record.id).values(revoked_at=None))
    db.expire_all()
    assert _resolve(db, token) is not None

    # Alle Sessions des Kontos widerrufen (session_revoke_at)
    user.session_revoke_at = datetime.now(UTC) + timedelta(seconds=1)
    db.flush()
    db.expire_all()
    assert _resolve(db, token) is None
    user.session_revoke_at = None

    # Deaktiviert, Login entzogen, ausgetreten
    for change, reset in (
        ({"is_active": False}, {"is_active": True}),
        ({"login_enabled": False}, {"login_enabled": True}),
        ({"left_at": date.today() - timedelta(days=2)}, {"left_at": None}),
    ):
        for key, value in change.items():
            setattr(user, key, value)
        db.flush()
        db.expire_all()
        assert _resolve(db, token) is None, change
        for key, value in reset.items():
            setattr(user, key, value)
        db.flush()
    db.expire_all()
    assert _resolve(db, token) is not None


def test_session_of_other_account_is_rejected(db):
    _tenant, _user, record, _token = _user_with_session(db, "grundlast-a@example.com")
    _tenant_b, other, _record_b, _token_b = _user_with_session(db, "grundlast-b@example.com")
    forged = create_session_token(other.id, sid=str(record.id))
    assert _resolve(db, forged) is None


def test_mfa_factor_and_role_mfa_still_enforced(db):
    _tenant, user, _record, token = _user_with_session(db, "grundlast-mfa@example.com")
    # Faktor vorhanden, Session ohne MFA-Bestätigung: abgelehnt
    db.add(UserMfaFactor(user_id=user.id, factor_type="totp", label="t", secret_encrypted="x", totp_last_counter=0))
    db.flush()
    db.expire_all()
    assert _resolve(db, token) is None
    db.execute(text("DELETE FROM user_mfa_factor WHERE user_id = :id"), {"id": user.id})
    db.expire_all()
    assert _resolve(db, token) is not None

    # Rolle verlangt MFA, Konto ohne Faktor und ohne Frist (neues Konto): abgelehnt
    db.execute(update(TenantRole).where(TenantRole.tenant_id == user.tenant_id).values(require_mfa=True))  # rbac-ok: Testaufbau
    db.expire_all()
    assert _resolve(db, token) is None


def test_invalid_sid_is_rejected(db):
    _tenant, user, _record, _token = _user_with_session(db, "grundlast-sid@example.com")
    assert _resolve(db, create_session_token(user.id, sid="keine-uuid")) is None
    assert _resolve(db, create_session_token(user.id, sid="0190a000-0000-7000-8000-000000000000")) is None


def test_role_without_permissions_can_require_mfa(db):
    """Rollen-MFA kommt aus den Rollenzeilen (Outer-Join auf die Rechte): auch eine Rolle ohne
    ein einziges Recht zählt."""
    from app.models import TenantRolePermission, UserRole

    _tenant, user, _record, token = _user_with_session(db, "grundlast-leer@example.com")
    role_ids = [row.role_id for row in db.query(UserRole).filter(UserRole.user_id == user.id)]
    db.query(TenantRolePermission).filter(TenantRolePermission.role_id.in_(role_ids)).delete(synchronize_session=False)  # rbac-ok: Testaufbau, leere Rolle
    db.execute(update(TenantRole).where(TenantRole.id.in_(role_ids)).values(require_mfa=True))  # rbac-ok: Testaufbau
    db.expire_all()
    assert _resolve(db, token) is None


def test_websocket_path_uses_same_checks(db):
    from app.api.routes.collaboration_ws import _authenticate_in

    _tenant, user, _record, token = _user_with_session(db, "grundlast-ws@example.com")
    assert _authenticate_in(db, token) is not None
    db.add(UserMfaFactor(user_id=user.id, factor_type="totp", label="t", secret_encrypted="x", totp_last_counter=0))
    db.flush()
    db.expire_all()
    assert _authenticate_in(db, token) is None
    db.execute(text("DELETE FROM user_mfa_factor WHERE user_id = :id"), {"id": user.id})
    db.execute(update(TenantRole).where(TenantRole.tenant_id == user.tenant_id).values(require_mfa=True))  # rbac-ok: Testaufbau
    db.expire_all()
    assert _authenticate_in(db, token) is None
