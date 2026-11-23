"""Login-E-Mail ändern = Konto-Übernahme (SEC-AUTH-010, Step-up).

Wer die Login-E-Mail eines Kontos auf eine eigene Adresse ändert, kann danach über «Passwort
vergessen» ein neues Passwort setzen - dieselbe Wirkung wie «Passwort setzen», das eine frische
Anmeldung verlangt. Ohne Step-up genügte ein gestohlenes Admin-Cookie (älter als
``auth_step_up_admin_minutes``), um ein fremdes Konto des Vereins bzw. das eigene dauerhaft zu
übernehmen. Gilt für /users und /participants; Personen ohne Login betrifft es nicht.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import participants as participants_route
from app.core.security import build_current_user
from app.models import AppUser
from app.schemas.participant import ParticipantUpdate
from app.schemas.user import UserUpdate
from app.services.user_service import UserService
from tests.factories import make_app_user, make_tenant


def _stale_admin(db, tenant_id: int, email: str):
    admin = make_app_user(db, email=email, tenant_id=tenant_id, role_code="admin")
    actor = build_current_user(db, admin)
    actor.auth_time = datetime.now(UTC) - timedelta(hours=1)
    return admin, actor


def _assert_step_up(exc: pytest.ExceptionInfo) -> None:
    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict) and exc.value.detail["code"] == "step_up_required"


def test_changing_login_email_of_member_via_users_needs_step_up(db):
    tenant = make_tenant(db)
    _admin, actor = _stale_admin(db, tenant.id, "mail-admin@example.com")
    member = make_app_user(db, email="mail-member@example.com", tenant_id=tenant.id, role_code="writer")
    with pytest.raises(HTTPException) as exc:
        UserService().update_user(db, member.id, UserUpdate(email="angreifer@example.net"), actor)
    _assert_step_up(exc)
    db.expire_all()
    assert db.get(AppUser, member.id).email == "mail-member@example.com"
    # Frisch bestätigt: erlaubt
    actor.auth_time = datetime.now(UTC)
    UserService().update_user(db, member.id, UserUpdate(email="neu@example.com"), actor)
    db.expire_all()
    assert db.get(AppUser, member.id).email == "neu@example.com"


def test_changing_own_login_email_via_users_needs_step_up(db):
    tenant = make_tenant(db)
    admin, actor = _stale_admin(db, tenant.id, "self-mail-admin@example.com")
    with pytest.raises(HTTPException) as exc:
        UserService().update_user(db, admin.id, UserUpdate(email="angreifer@example.net"), actor)
    _assert_step_up(exc)


def test_unchanged_email_and_other_fields_need_no_step_up(db):
    tenant = make_tenant(db)
    _admin, actor = _stale_admin(db, tenant.id, "same-mail-admin@example.com")
    member = make_app_user(db, email="same-mail@example.com", tenant_id=tenant.id, role_code="reader")
    # Gleiche Adresse (nur Gross-/Kleinschreibung/Leerzeichen) und Name: keine Konto-Übernahme
    UserService().update_user(db, member.id, UserUpdate(email=" Same-Mail@example.com ", display_name="Neu"), actor)


def test_changing_login_email_via_participants_needs_step_up(db):
    tenant = make_tenant(db)
    _admin, actor = _stale_admin(db, tenant.id, "part-mail-admin@example.com")
    member = make_app_user(db, email="part-mail-member@example.com", tenant_id=tenant.id, role_code="writer")
    with pytest.raises(HTTPException) as exc:
        participants_route.patch_participant(member.public_id, ParticipantUpdate(email="angreifer@example.net"), db=db, user=actor)
    _assert_step_up(exc)
    db.expire_all()
    assert db.get(AppUser, member.id).email == "part-mail-member@example.com"


def test_email_of_person_without_login_needs_no_step_up(db):
    tenant = make_tenant(db)
    _admin, actor = _stale_admin(db, tenant.id, "nologin-admin@example.com")
    person = make_app_user(db, email="ohne-login@example.com", tenant_id=tenant.id, role_code="reader")
    person.login_enabled = False
    db.flush()
    participants_route.patch_participant(person.public_id, ParticipantUpdate(email="andere@example.com"), db=db, user=actor)
    db.expire_all()
    assert db.get(AppUser, person.id).email == "andere@example.com"
