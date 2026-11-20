"""Ausgetretene Personen (Austrittsdatum vor heute): Login immer gesperrt, in Auswahllisten und in
der Login-Verwaltung ausgeblendet. Am Austrittstag selbst ist die Person noch Mitglied."""
from datetime import timedelta

import pytest
from fastapi import HTTPException, Response

from app.api.routes.participants import invite_participant, list_participants
from app.core.security import create_session_token, get_optional_current_user
from app.schemas.user import LoginRequest
from app.services import user_limit_service
from app.services.auth_service import AuthService
from app.services.todo_fine_service import today
from app.services.user_service import UserService
from tests.factories import make_app_user, make_current_user, make_tenant

PASSWORD = "correct horse battery staple"


def _person(db, tenant, email, *, left_days_ago: int | None):
    user = make_app_user(db, email=email, password=PASSWORD, tenant_id=tenant.id, role_code="writer")
    user.left_at = None if left_days_ago is None else today() - timedelta(days=left_days_ago)
    db.flush()
    return user


def _admin(tenant):
    actor = make_current_user(tenant.id, role="admin", user_id=999999)
    actor.current_tenant_public_id = tenant.public_id
    return actor


def test_has_left_from_the_day_after_the_exit_date(db):
    tenant = make_tenant(db)
    assert not _person(db, tenant, "noch@example.com", left_days_ago=None).has_left
    assert not _person(db, tenant, "heute@example.com", left_days_ago=0).has_left  # Austrittstag: noch dabei
    assert _person(db, tenant, "weg@example.com", left_days_ago=1).has_left


def test_former_member_cannot_log_in_and_old_sessions_end(db):
    tenant = make_tenant(db)
    person = _person(db, tenant, "ehemalig@example.com", left_days_ago=None)
    token = create_session_token(person.id)
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is not None

    person.left_at = today() - timedelta(days=1)
    db.flush()
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None
    with pytest.raises(HTTPException) as exc_info:
        AuthService().login(db, Response(), LoginRequest(email="ehemalig@example.com", password=PASSWORD), request_host=None)
    # Wie ein falsches Passwort (Auth-Audit 2026-11-20, SEC-AUTH-016: kein Passwort-Orakel)
    assert exc_info.value.status_code == 401 and exc_info.value.detail["code"] == "invalid_credentials"

    # Austritt zurückgenommen: der Login gilt ohne weiteres Zutun wieder
    person.left_at = None
    db.flush()
    assert get_optional_current_user(request=None, db=db, session_cookie=create_session_token(person.id)) is not None


def test_former_members_are_hidden_from_pickers_but_not_from_the_member_list(db):
    tenant = make_tenant(db)
    current = _person(db, tenant, "aktiv@example.com", left_days_ago=None)
    leaving_today = _person(db, tenant, "letzter-tag@example.com", left_days_ago=0)
    former = _person(db, tenant, "ausgetreten@example.com", left_days_ago=30)
    actor = _admin(tenant)

    picker = {p.id for p in list_participants(active_only=False, include_former=False, skip=0, limit=100, db=db, user=actor)}
    everyone = {p.id for p in list_participants(active_only=False, include_former=True, skip=0, limit=100, db=db, user=actor)}
    # Die Route liefert die Mitgliederliste als ParticipantOverviewRead (public_id wie in der HTTP-Antwort)
    assert {current.public_id, leaving_today.public_id} <= picker and former.public_id not in picker
    assert former.public_id in everyone


def test_former_logins_are_hidden_and_not_counted(db):
    tenant = make_tenant(db)
    current = _person(db, tenant, "zaehlt@example.com", left_days_ago=None)
    former = _person(db, tenant, "zaehlt-nicht@example.com", left_days_ago=2)
    listed = {user.id for user in UserService().list_users(db, _admin(tenant))}  # public_id
    assert current.public_id in listed and former.public_id not in listed
    assert user_limit_service.login_account_count(db, tenant.id) == 1


def test_former_member_cannot_be_invited(db):
    tenant = make_tenant(db)
    former = make_app_user(db, email="kein-login@example.com", password=PASSWORD, tenant_id=tenant.id)
    former.login_enabled = False
    former.left_at = today() - timedelta(days=1)
    db.flush()
    with pytest.raises(HTTPException) as exc_info:
        invite_participant(participant_id=former.public_id, db=db, user=_admin(tenant))
    assert exc_info.value.status_code == 409 and exc_info.value.detail["code"] == "former_person"
