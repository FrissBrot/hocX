"""Austrittsdatum in der Vergangenheit sperrt einen Login (AppUser.has_left) - wie Deaktivieren.
Deshalb gelten dieselben Schutzregeln: kein Setzen ohne access.manage bzw. bei Höherberechtigten,
und der letzte handlungsfähige Administrator darf so nicht verschwinden."""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import participants as participant_routes
from app.core.permissions import P
from app.schemas.participant import ParticipantUpdate
from app.services import role_service
from app.services.participant_service import ParticipantService
from app.services.todo_fine_service import today
from tests.factories import make_app_user, make_current_user, make_tenant


def test_left_admin_is_not_counted_as_capable_admin(db):
    tenant = make_tenant(db)
    make_app_user(db, "aktiv-admin@example.com", tenant_id=tenant.id, role_code="admin")
    former = make_app_user(db, "weg-admin@example.com", tenant_id=tenant.id, role_code="admin")
    former.left_at = today() - timedelta(days=1)
    leaving_today = make_app_user(db, "heute-admin@example.com", tenant_id=tenant.id, role_code="admin")
    leaving_today.left_at = today()  # am Austrittstag noch Mitglied
    db.flush()
    assert role_service.count_capable_admins(db, tenant.id) == 2


def test_exit_date_in_the_past_cannot_remove_the_last_admin(db):
    tenant = make_tenant(db)
    admin = make_app_user(db, "einzig-admin@example.com", tenant_id=tenant.id, role_code="admin")
    with pytest.raises(HTTPException) as error:
        ParticipantService().update_participant(
            db, admin.id, ParticipantUpdate(left_at=today() - timedelta(days=1)), tenant_id=tenant.id,
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "last_admin"
    db.refresh(admin)
    assert admin.left_at is None


def test_exit_date_of_a_login_needs_access_manage(db):
    tenant = make_tenant(db)
    make_app_user(db, "admin-bleibt@example.com", tenant_id=tenant.id, role_code="admin")
    target = make_app_user(db, "konto@example.com", tenant_id=tenant.id, role_code="admin")
    only_participants = make_current_user(tenant.id, role="writer", user_id=999999, permissions=frozenset({P.PARTICIPANTS_MANAGE.value}))
    with pytest.raises(HTTPException) as error:
        participant_routes.patch_participant(target.public_id, ParticipantUpdate(left_at=today() - timedelta(days=1)), db, only_participants)
    assert error.value.status_code == 403
    db.refresh(target)
    assert target.left_at is None


def test_exit_date_of_a_person_without_login_stays_with_participants_manage(db):
    from tests.factories import make_participant

    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Ohne Login")
    only_participants = make_current_user(tenant.id, role="writer", user_id=999999, permissions=frozenset({P.PARTICIPANTS_MANAGE.value}))
    participant_routes.patch_participant(person.public_id, ParticipantUpdate(left_at=today() - timedelta(days=1)), db, only_participants)
    db.refresh(person)
    assert person.has_left


def test_admin_cannot_lock_themselves_out_with_an_exit_date(db):
    from app.schemas.user import UserUpdate
    from app.services.user_service import UserService

    tenant = make_tenant(db)
    make_app_user(db, "andere-admin@example.com", tenant_id=tenant.id, role_code="admin")
    me = make_app_user(db, "ich-admin@example.com", tenant_id=tenant.id, role_code="admin")
    actor = make_current_user(tenant.id, role="admin", user_id=me.id)
    with pytest.raises(HTTPException) as error:
        UserService().update_user(db, me.id, UserUpdate(left_at=today() - timedelta(days=1)), actor)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "own_access_management"
