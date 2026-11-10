"""Gemeinsame Identität, optionale Kontaktdaten und ausschliesslich administrierte Logins."""
from datetime import date

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import func, inspect, select

from app.models import AppUser, Participant, TemplateParticipant
from app.schemas.participant import ParticipantCreate, ParticipantUpdate
from app.schemas.user import LoginRequest, UserCreate, UserUpdate
from app.services.auth_service import AuthService
from app.services.participant_service import ParticipantService
from app.services.user_service import UserService
from tests.factories import make_app_user, make_current_user, make_tenant, make_template, make_template_participant


def actor(tenant, role="admin"):
    result = make_current_user(tenant.id, role=role, user_id=999999)
    result.current_tenant_public_id = tenant.public_id
    return result


def test_single_identity_without_email_or_password(db):
    tenant = make_tenant(db)
    person = ParticipantService().create_participant(db, ParticipantCreate(display_name="Nur Teilnehmer"), tenant_id=tenant.id)
    assert Participant is AppUser
    assert db.get(AppUser, person.id) is person
    assert person.email is None and person.password_hash is None
    assert not person.login_enabled
    assert db.scalar(select(func.count(AppUser.id)).where(AppUser.tenant_id == tenant.id)) == 1
    assert "participant" not in inspect(db.bind).get_table_names()
    assert not hasattr(person, "app_user_id")


def test_contact_email_can_be_shared_with_login_and_other_participants(db):
    tenant = make_tenant(db)
    make_app_user(db, tenant_id=tenant.id, email="family@example.com")
    service = ParticipantService()
    for name in ("Kind 1", "Kind 2"):
        person = service.create_participant(db, ParticipantCreate(display_name=name, email="family@example.com"), tenant_id=tenant.id)
        assert not person.login_enabled


def test_login_activation_preserves_identity_and_assignments(db):
    tenant = make_tenant(db)
    person = ParticipantService().create_participant(db, ParticipantCreate(display_name="Person"), tenant_id=tenant.id)
    template = make_template(db, tenant.id)
    make_template_participant(db, template.id, person.id)
    original_id, original_public_id = person.id, person.public_id
    result = UserService().update_user(db, person.id, UserUpdate(email=" Person@Example.com ", password="a-secure-password-123", login_enabled=True), actor(tenant))
    assert result.id == original_public_id
    assert result.email == "person@example.com"
    assert result.login_enabled
    assert db.get(Participant, original_id).password_hash
    assert db.scalar(select(TemplateParticipant.participant_id).where(TemplateParticipant.template_id == template.id)) == original_id
    # Kontaktzeilen mit gleicher Adresse stören die Login-Suche nicht.
    ParticipantService().create_participant(db, ParticipantCreate(display_name="Andere Person", email=result.email), tenant_id=tenant.id)
    response = AuthService().login(db, Response(), LoginRequest(email="PERSON@EXAMPLE.COM", password="a-secure-password-123"), request_host=None)
    assert response.authenticated


@pytest.mark.parametrize("email,password", [(None,"a-secure-password-123"),("person@example.com",None)])
def test_activation_requires_email_and_password(db, email, password):
    tenant = make_tenant(db)
    person = ParticipantService().create_participant(db, ParticipantCreate(display_name="Person"), tenant_id=tenant.id)
    with pytest.raises(HTTPException):
        UserService().update_user(db, person.id, UserUpdate(email=email,password=password,login_enabled=True), actor(tenant))
    assert not person.login_enabled


def test_activation_conflict_never_merges_or_changes_existing_login(db):
    tenant = make_tenant(db)
    existing = make_app_user(db, tenant_id=tenant.id, email="taken@example.com")
    password_hash = existing.password_hash
    person = ParticipantService().create_participant(db, ParticipantCreate(display_name="Person",email=existing.email),tenant_id=tenant.id)
    with pytest.raises(HTTPException) as exc:
        UserService().update_user(db, person.id, UserUpdate(password="a-secure-password-123",login_enabled=True),actor(tenant))
    assert exc.value.status_code == 409
    assert not person.login_enabled and existing.password_hash == password_hash
    assert db.get(AppUser, person.id) is person
    assert not hasattr(UserService(), "merge_users")


def test_writer_cannot_activate_login(db):
    tenant = make_tenant(db)
    person = ParticipantService().create_participant(db,ParticipantCreate(display_name="Person"),tenant_id=tenant.id)
    with pytest.raises(HTTPException) as exc:
        UserService().update_user(db,person.id,UserUpdate(email="person@example.com",password="a-secure-password-123",login_enabled=True),actor(tenant,"writer"))
    assert exc.value.status_code == 403
    assert not person.login_enabled


def test_both_apis_update_same_stammdaten(db):
    tenant = make_tenant(db)
    result = UserService().create_user(db,UserCreate(display_name="Person"),actor(tenant))
    person = db.scalar(select(Participant).where(Participant.public_id == result.id))
    ParticipantService().update_participant(db,person.id,ParticipantUpdate(display_name="Neuer Name",joined_at=date(2020,1,1)),tenant_id=tenant.id)
    assert UserService().get_user(db,person.id,actor(tenant)).display_name == "Neuer Name"
    UserService().update_user(db,person.id,UserUpdate(display_name="Noch ein Name"),actor(tenant))
    assert ParticipantService().get_participant(db,person.id,tenant_id=tenant.id).display_name == "Noch ein Name"


def test_disable_login_keeps_participant_and_revokes_sessions(db):
    tenant = make_tenant(db)
    user = make_app_user(db,tenant_id=tenant.id)
    UserService().update_user(db,user.id,UserUpdate(login_enabled=False,email=None),actor(tenant))
    assert db.get(Participant,user.id) is user
    assert user.session_revoke_at is not None and not user.login_enabled


def test_last_admin_cannot_lose_login_or_be_deleted_via_participant_api(db):
    tenant = make_tenant(db)
    user = make_app_user(db,tenant_id=tenant.id,role_code="admin")
    for action in (
        lambda: UserService().update_user(db,user.id,UserUpdate(login_enabled=False),actor(tenant)),
        lambda: ParticipantService().delete_participant(db,user.id,tenant_id=tenant.id),
        lambda: ParticipantService().update_participant(db,user.id,ParticipantUpdate(is_active=False),tenant_id=tenant.id),
    ):
        with pytest.raises(HTTPException) as exc:
            action()
        assert exc.value.status_code == 409
    assert user.is_active and user.login_enabled


def test_create_login_requires_credentials():
    with pytest.raises(ValidationError):
        UserCreate(display_name="Person",login_enabled=True)


def test_writer_cannot_change_login_credentials_or_delete_login(db):
    from app.api.routes.participants import patch_participant, delete_participant
    tenant = make_tenant(db)
    person = make_app_user(db, tenant_id=tenant.id)
    writer = actor(tenant, "writer")
    for payload in (ParticipantUpdate(login_enabled=False), ParticipantUpdate(email="changed@example.com"), ParticipantUpdate(is_active=False)):
        with pytest.raises(HTTPException) as error:
            patch_participant(person.public_id, payload, db, writer)
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        delete_participant(person.public_id, db, writer)
    assert error.value.status_code == 403
    assert person.login_enabled
