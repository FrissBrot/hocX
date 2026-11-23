"""Benutzerlimit des Abos: offene Einladungen zählen schon beim Einladen mit (Entscheid
18.11.2026) - die eigene Einladung der Person belegt aber keinen zusätzlichen Platz."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import AccountToken
from app.services import user_limit_service
from tests.factories import make_app_user, make_participant, make_tenant


def _invite(db, tenant_id: int, person) -> AccountToken:
    token = AccountToken(
        tenant_id=tenant_id, user_id=person.id, purpose="invite", token_hash=f"hash-{person.id}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(token)
    db.flush()
    return token


def test_open_invites_count_towards_the_limit(db):
    tenant = make_tenant(db, "Limit Einladungen")
    tenant.user_limit_override = 2
    make_app_user(db, "limit-admin@example.com", tenant_id=tenant.id, role_code="admin")  # 1 Login
    invited = make_participant(db, tenant.id, "Eingeladen")
    other = make_participant(db, tenant.id, "Weitere Person")
    _invite(db, tenant.id, invited)

    assert user_limit_service.pending_invite_count(db, tenant.id) == 1
    # Login + offene Einladung = Limit: niemand weiteres
    with pytest.raises(HTTPException) as full:
        user_limit_service.ensure_login_capacity(db, tenant.id, for_user_id=other.id)
    assert full.value.status_code == 409
    # Die eingeladene Person selbst (erneut senden, annehmen) belegt keinen zusätzlichen Platz
    user_limit_service.ensure_login_capacity(db, tenant.id, for_user_id=invited.id)


def test_expired_or_revoked_invites_do_not_count(db):
    tenant = make_tenant(db, "Limit abgelaufen")
    expired = _invite(db, tenant.id, make_participant(db, tenant.id, "Abgelaufen"))
    expired.expires_at = datetime.now(UTC) - timedelta(days=1)
    revoked = _invite(db, tenant.id, make_participant(db, tenant.id, "Zurückgezogen"))
    revoked.revoked_at = datetime.now(UTC)
    db.flush()
    assert user_limit_service.pending_invite_count(db, tenant.id) == 0


def test_open_invite_of_a_former_member_does_not_count(db):
    """Ausgetretene Personen (Austrittsdatum vor heute, Schweizer Zeit) können eine Einladung nie
    annehmen (account.py) und zählen nicht zum Limit - ihre liegengebliebene Einladung auch nicht."""
    from datetime import date

    tenant = make_tenant(db, "Limit Ausgetreten")
    tenant.user_limit_override = 2
    make_app_user(db, "limit-former-admin@example.com", tenant_id=tenant.id, role_code="admin")  # 1 Login
    former = make_participant(db, tenant.id, "Ausgetreten")
    _invite(db, tenant.id, former)
    former.left_at = date(2000, 1, 1)
    leaving_today = make_participant(db, tenant.id, "Tritt heute aus")
    _invite(db, tenant.id, leaving_today)
    from app.services.todo_fine_service import today

    leaving_today.left_at = today()  # am Austrittstag selbst noch Mitglied: zählt weiter
    db.flush()

    assert user_limit_service.pending_invite_count(db, tenant.id) == 1


def test_reentry_of_a_former_login_respects_the_limit(db):
    """Ausgetretene mit Login zählen nicht zum Limit; wird das Austrittsdatum entfernt oder in die
    Zukunft verschoben, gilt der Login wieder (has_left) - das ist ein weiteres aktives Konto und
    muss wie Reaktivieren gegen das Limit geprüft werden (Personen- und Benutzer-Route)."""
    from datetime import date

    from app.schemas.participant import ParticipantUpdate
    from app.schemas.user import UserUpdate
    from app.services.participant_service import ParticipantService
    from app.services.todo_fine_service import today
    from app.services.user_service import UserService
    from tests.factories import make_current_user

    tenant = make_tenant(db, "Limit Wiedereintritt")
    tenant.user_limit_override = 1
    admin = make_app_user(db, "reentry-admin@example.com", tenant_id=tenant.id, role_code="admin")  # 1 Login = Limit
    former = make_app_user(db, "reentry-former@example.com", tenant_id=tenant.id, role_code="reader")
    former.left_at = date(2020, 1, 1)
    db.flush()
    assert user_limit_service.login_account_count(db, tenant.id) == 1

    with pytest.raises(HTTPException) as via_person:
        ParticipantService().update_participant(db, former.id, ParticipantUpdate(left_at=None), tenant_id=tenant.id)
    assert via_person.value.status_code == 409
    actor = make_current_user(tenant.id, role="admin", user_id=admin.id)
    with pytest.raises(HTTPException) as via_user:
        UserService().update_user(db, former.id, UserUpdate(left_at=today()), actor)
    assert via_user.value.status_code == 409
    db.refresh(former)
    assert former.left_at == date(2020, 1, 1)
    # Ein anderes, früheres Austrittsdatum (bleibt ausgetreten) ist kein Wiedereintritt
    ParticipantService().update_participant(db, former.id, ParticipantUpdate(left_at=date(2019, 1, 1)), tenant_id=tenant.id)


def test_subscription_reports_open_invites_as_taken_seats(db):
    """«Abo & Nutzung» zeigt freie Plätze: offene Einladungen zählen beim Einladen schon mit und
    müssen deshalb mitgeliefert werden, sonst zeigt die Seite Plätze frei, die ein 409 ergeben."""
    from tests.factories import system_role_permissions
    from app.core.security import CurrentUser
    from app.services.tenant_service import TenantService

    tenant = make_tenant(db, "Limit Anzeige")
    tenant.user_limit_override = 2
    make_app_user(db, "anzeige-admin@example.com", tenant_id=tenant.id, role_code="admin")
    _invite(db, tenant.id, make_participant(db, tenant.id, "Eingeladen"))
    actor = CurrentUser(
        user_id=1, user_public_id=tenant.public_id, first_name="Test", last_name="Admin", display_name="Test Admin",
        email="test@example.com", preferred_language="de", current_tenant_id=tenant.id,
        current_tenant_public_id=tenant.public_id, current_tenant_name=tenant.name, current_tenant_profile_image_path=None,
        permissions=system_role_permissions("admin"), current_tenant_features=frozenset(),
    )
    subscription = TenantService().get_subscription(db, tenant.id, actor)
    assert subscription.user_count == 1
    assert subscription.pending_invite_count == 1
