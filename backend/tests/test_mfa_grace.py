"""MFA je Rolle und 3-Tage-Frist für bestehende Konten (Migration 0192, Entscheid 18.11.2026).

- Neue Konten (noch nie angemeldet): keine Frist, MFA beim ersten Login.
- Bestehende Konten: Frist ab dem ersten Erkennen, fest gespeichert, danach Pflicht.
- Pflicht wegen Administrationsrechten: nie Frist.
- tenant_role.require_mfa macht MFA für alle mit dieser Rolle zur Pflicht.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.mfa_policy import MFA_GRACE, account_requires_mfa, mfa_grace_until
from app.models import TenantRole, UserRole
from tests.factories import make_participant, make_tenant

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
READER = frozenset({"meetings.read", "todos.complete_own"})


def _club(db, *, require_mfa: bool = True):
    tenant = make_tenant(db, "MFA Frist")
    tenant.require_mfa = require_mfa
    db.flush()
    return tenant


def test_new_account_gets_no_grace(db):
    tenant = _club(db)
    person = make_participant(db, tenant.id, "Neu")
    assert person.first_login_at is None
    assert mfa_grace_until(db, person.id, permissions=READER, tenant_id=tenant.id, now=NOW) is None


def test_existing_account_gets_three_days_once(db):
    tenant = _club(db)
    person = make_participant(db, tenant.id, "Bestehend")
    person.first_login_at = NOW - timedelta(days=100)
    db.flush()
    deadline = mfa_grace_until(db, person.id, permissions=READER, tenant_id=tenant.id, now=NOW)
    assert deadline == NOW + MFA_GRACE
    # Spätere Prüfungen verlängern nicht
    assert mfa_grace_until(db, person.id, permissions=READER, tenant_id=tenant.id, now=NOW + timedelta(days=1)) == deadline
    # Nach Ablauf: keine Frist mehr -> Pflicht greift
    assert mfa_grace_until(db, person.id, permissions=READER, tenant_id=tenant.id, now=NOW + timedelta(days=4)) is None


def test_admin_rights_never_get_grace(db):
    tenant = _club(db)
    person = make_participant(db, tenant.id, "Admin")
    person.first_login_at = NOW - timedelta(days=100)
    db.flush()
    admin_rights = READER | {"settings.manage"}
    assert mfa_grace_until(db, person.id, permissions=admin_rights, tenant_id=tenant.id, now=NOW) is None


def test_no_requirement_no_grace(db):
    tenant = _club(db, require_mfa=False)
    person = make_participant(db, tenant.id, "Frei")
    person.first_login_at = NOW - timedelta(days=100)
    db.flush()
    assert mfa_grace_until(db, person.id, permissions=READER, tenant_id=tenant.id, now=NOW) is None
    assert person.mfa_grace_until is None


def test_role_flag_requires_mfa(db):
    tenant = _club(db, require_mfa=False)
    person = make_participant(db, tenant.id, "Rolle")
    reader_role = db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant.id, TenantRole.system_key == "reader"))
    if not db.scalar(select(UserRole).where(UserRole.user_id == person.id, UserRole.role_id == reader_role.id)):
        db.add(UserRole(tenant_id=tenant.id, user_id=person.id, role_id=reader_role.id))
    db.flush()
    assert not account_requires_mfa(db, person.id, permissions=READER, tenant_id=tenant.id)
    reader_role.require_mfa = True
    db.flush()
    assert account_requires_mfa(db, person.id, permissions=READER, tenant_id=tenant.id)
