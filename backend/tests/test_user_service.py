"""Regression tests for UserService. A user belongs to exactly one tenant with exactly one role
(app_user.tenant_id/role_id), which is what these tests pin down:
(1) a tenant admin's authority over an account is complete but stops at the tenant border -
    an account of another tenant can't be read, changed (password/email/role/active flag) or
    deleted, and looks like "not found" rather than "forbidden";
(2) the "last tenant admin" guard - a tenant must never end up with zero active admins;
(3) capability-aware role handling in merge_users(), which is now same-tenant only."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.security import CurrentUser
from app.schemas.user import UserCreate, UserPasswordChange, UserUpdate
from app.services.user_service import _PASSWORD_CHANGE_ATTEMPT_LIMIT, UserService
from tests.factories import make_app_user, make_current_user, make_participant, make_tenant


def _admin_actor(tenant, *, user_id: int = 999999) -> CurrentUser:
    # user_id is frequently a synthetic int with no backing row here, so - like
    # tests/factories.py's make_current_user - only the tenant public id is real (the
    # create_user tenant check compares against it).
    return CurrentUser(
        user_id=user_id,
        user_public_id=uuid.uuid4(),
        first_name="Admin",
        last_name="Actor",
        display_name="Admin Actor",
        email="admin-actor@example.com",
        preferred_language="de",
        is_participant_account=False,
        current_tenant_id=tenant.id,
        current_tenant_public_id=tenant.public_id,
        current_tenant_name=tenant.name,
        current_tenant_profile_image_path=None,
        current_role="admin",
    )


def _payload(email: str, **overrides) -> UserCreate:
    return UserCreate(
        first_name="New",
        last_name="Person",
        display_name="New Person",
        email=email,
        password="a-very-long-password-123",
        **overrides,
    )


# --- merge_users: capability-aware role merge logic --------------------------------------


def test_merge_users_prefers_higher_role_writer_over_reader(db):
    tenant = make_tenant(db, "Merge Tenant")
    target = make_app_user(db, email="target@example.com", tenant_id=tenant.id, role_code="reader")
    source = make_app_user(db, email="source@example.com", tenant_id=tenant.id, role_code="writer")

    result = UserService().merge_users(db, source_user_id=source.id, target_user_id=target.id)

    assert result.role_code == "writer"


def test_merge_users_kassier_supersedes_reader_but_conflicts_with_writer(db):
    tenant = make_tenant(db, "Kassier Merge Tenant")
    target_a = make_app_user(db, email="target-a@example.com", tenant_id=tenant.id, role_code="reader")
    source_a = make_app_user(db, email="source-a@example.com", tenant_id=tenant.id, role_code="kassier")

    service = UserService()
    assert service.merge_users(db, source_user_id=source_a.id, target_user_id=target_a.id).role_code == "kassier"

    target_b = make_app_user(db, email="target-b@example.com", tenant_id=tenant.id, role_code="kassier")
    source_b = make_app_user(db, email="source-b@example.com", tenant_id=tenant.id, role_code="writer")
    with pytest.raises(HTTPException) as exc_info:
        service.merge_users(db, source_user_id=source_b.id, target_user_id=target_b.id)
    assert exc_info.value.status_code == 409


def test_merge_users_prefers_active_account_when_role_priority_equal(db):
    tenant = make_tenant(db, "Active Merge Tenant")
    target = make_app_user(db, email="target-inactive@example.com", tenant_id=tenant.id, is_active=False)
    source = make_app_user(db, email="source-active@example.com", tenant_id=tenant.id, is_active=True)

    result = UserService().merge_users(db, source_user_id=source.id, target_user_id=target.id)

    assert result.is_active is True


def test_merge_users_raises_when_source_equals_target(db):
    user = make_app_user(db)

    with pytest.raises(HTTPException) as exc_info:
        UserService().merge_users(db, source_user_id=user.id, target_user_id=user.id)
    assert exc_info.value.status_code == 400


def test_merge_users_refuses_accounts_of_different_tenants(db):
    """Accounts don't span tenants, so two accounts of different tenants can never be one person."""
    target = make_app_user(db, email="merge-target-a@example.com")
    source = make_app_user(db, email="merge-source-b@example.com")

    service = UserService()
    with pytest.raises(HTTPException) as exc_info:
        service.merge_users(db, source_user_id=source.id, target_user_id=target.id)
    assert exc_info.value.status_code == 400
    assert service.repository.get(db, source.id) is not None


def test_merge_users_raises_on_conflicting_participant_links(db):
    """Both accounts already linked to a (different) participant - merging would silently
    orphan one of the two participant links, so the service must refuse."""
    tenant = make_tenant(db, "Conflict Tenant")
    target = make_app_user(db, email="target-conflict@example.com", tenant_id=tenant.id)
    source = make_app_user(db, email="source-conflict@example.com", tenant_id=tenant.id)

    participant_target = make_participant(db, tenant.id, display_name="Target Person")
    participant_target.app_user_id = target.id
    participant_source = make_participant(db, tenant.id, display_name="Source Person")
    participant_source.app_user_id = source.id
    db.add_all([participant_target, participant_source])
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        UserService().merge_users(db, source_user_id=source.id, target_user_id=target.id)
    assert exc_info.value.status_code == 400


def test_merge_users_moves_participant_link_and_deletes_source(db):
    tenant = make_tenant(db, "Move Link Tenant")
    target = make_app_user(db, email="target-move@example.com", tenant_id=tenant.id)
    source = make_app_user(db, email="source-move@example.com", tenant_id=tenant.id)

    participant = make_participant(db, tenant.id, display_name="Moving Person")
    participant.app_user_id = source.id
    db.add(participant)
    db.flush()

    service = UserService()
    service.merge_users(db, source_user_id=source.id, target_user_id=target.id)

    db.refresh(participant)
    assert participant.app_user_id == target.id
    assert service.repository.get(db, source.id) is None


# --- last-tenant-admin guard ---------------------------------------------------------------


def test_update_user_blocks_demoting_the_last_admin_of_a_tenant(db):
    tenant = make_tenant(db, "Last Admin Tenant")
    admin_user = make_app_user(db, email="only-admin@example.com", tenant_id=tenant.id, role_code="admin")

    with pytest.raises(HTTPException) as exc_info:
        UserService().update_user(db, admin_user.id, UserUpdate(role_code="reader"), _admin_actor(tenant))
    assert exc_info.value.status_code == 409
    db.refresh(admin_user)
    assert admin_user.role_id == UserService()._role_id(db, "admin")


def test_update_user_blocks_deactivating_the_last_admin_of_a_tenant(db):
    tenant = make_tenant(db, "Last Admin Deactivate Tenant")
    admin_user = make_app_user(db, email="only-admin-2@example.com", tenant_id=tenant.id, role_code="admin")

    with pytest.raises(HTTPException) as exc_info:
        UserService().update_user(db, admin_user.id, UserUpdate(is_active=False), _admin_actor(tenant))
    assert exc_info.value.status_code == 409


def test_update_user_allows_demoting_admin_when_another_admin_remains(db):
    tenant = make_tenant(db, "Two Admins Tenant")
    admin_one = make_app_user(db, email="admin-one@example.com", tenant_id=tenant.id, role_code="admin")
    make_app_user(db, email="admin-two@example.com", tenant_id=tenant.id, role_code="admin")

    result = UserService().update_user(db, admin_one.id, UserUpdate(role_code="reader"), _admin_actor(tenant))

    assert result.role_code == "reader"


def test_an_inactive_admin_does_not_count_as_remaining_admin(db):
    tenant = make_tenant(db, "Inactive Admin Tenant")
    admin_user = make_app_user(db, email="active-admin@example.com", tenant_id=tenant.id, role_code="admin")
    make_app_user(db, email="inactive-admin@example.com", tenant_id=tenant.id, role_code="admin", is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        UserService().update_user(db, admin_user.id, UserUpdate(role_code="writer"), _admin_actor(tenant))
    assert exc_info.value.status_code == 409


def test_update_user_rejects_unknown_role(db):
    tenant = make_tenant(db, "Unknown Role Tenant")
    user = make_app_user(db, email="unknown-role@example.com", tenant_id=tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        UserService().update_user(db, user.id, UserUpdate(role_code="superadmin"), _admin_actor(tenant))
    assert exc_info.value.status_code == 400


# --- tenant isolation boundary --------------------------------------------------------------


def test_get_user_not_found_when_target_user_not_in_actors_tenant(db):
    """Returns None (-> 404 at the route), not a 403: a 403 here would let a tenant-admin
    distinguish "exists in another tenant" from "doesn't exist at all", a user-enumeration
    channel across tenant boundaries."""
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    other_user = make_app_user(db, email="other-tenant-user@example.com", tenant_id=tenant_b.id)

    assert UserService().get_user(db, other_user.id, _admin_actor(tenant_a)) is None


def test_list_users_only_returns_users_of_the_actors_tenant(db):
    tenant_a = make_tenant(db, "Tenant A List")
    tenant_b = make_tenant(db, "Tenant B List")
    own = make_app_user(db, email="list-own@example.com", tenant_id=tenant_a.id)
    inactive = make_app_user(db, email="list-inactive@example.com", tenant_id=tenant_a.id, is_active=False)
    foreign = make_app_user(db, email="list-foreign@example.com", tenant_id=tenant_b.id)

    listed = {u.id for u in UserService().list_users(db, _admin_actor(tenant_a))}

    assert listed == {own.public_id, inactive.public_id}
    assert foreign.public_id not in listed


def test_update_user_cannot_touch_an_account_of_another_tenant(db):
    """Regression for the audit finding that a tenant admin could reset the password (and
    email/active flag) of an account that also belonged to their tenant but was really
    somebody else's: an account of another tenant must be completely out of reach."""
    tenant_a = make_tenant(db, "Takeover Tenant A")
    tenant_b = make_tenant(db, "Takeover Tenant B")
    victim = make_app_user(db, email="victim@example.com", password="victim original password", tenant_id=tenant_b.id, role_code="admin")
    original_hash = victim.password_hash

    result = UserService().update_user(
        db,
        victim.id,
        UserUpdate(password="attacker chosen password", email="attacker@example.com", is_active=False, role_code="reader"),
        _admin_actor(tenant_a),
    )

    assert result is None
    db.refresh(victim)
    assert victim.password_hash == original_hash
    assert victim.email == "victim@example.com"
    assert victim.is_active is True
    assert victim.tenant_id == tenant_b.id


def test_delete_user_cannot_delete_an_account_of_another_tenant(db):
    tenant_a = make_tenant(db, "Delete Tenant A")
    tenant_b = make_tenant(db, "Delete Tenant B")
    victim = make_app_user(db, email="delete-victim@example.com", tenant_id=tenant_b.id)

    service = UserService()
    assert service.delete_user(db, victim.id, _admin_actor(tenant_a)) is False
    assert service.repository.get(db, victim.id) is not None


def test_delete_user_removes_an_account_of_the_own_tenant(db):
    tenant = make_tenant(db, "Delete Own Tenant")
    user = make_app_user(db, email="delete-me@example.com", tenant_id=tenant.id)

    service = UserService()
    assert service.delete_user(db, user.id, _admin_actor(tenant)) is True
    assert service.repository.get(db, user.id) is None


def test_delete_user_blocks_deleting_the_last_admin(db):
    tenant = make_tenant(db, "Delete Last Admin Tenant")
    only_admin = make_app_user(db, email="delete-last-admin@example.com", tenant_id=tenant.id, role_code="admin")

    # A different admin acts (the guard is about the tenant's admin count, not self-delete).
    actor = _admin_actor(tenant, user_id=only_admin.id + 1000)
    with pytest.raises(HTTPException) as exc_info:
        UserService().delete_user(db, only_admin.id, actor)
    assert exc_info.value.status_code == 409


def test_delete_user_cannot_delete_own_account(db):
    tenant = make_tenant(db, "Self Delete Tenant")
    admin_user = make_app_user(db, email="self-delete@example.com", tenant_id=tenant.id, role_code="admin")

    with pytest.raises(HTTPException) as exc_info:
        UserService().delete_user(db, admin_user.id, _admin_actor(tenant, user_id=admin_user.id))
    assert exc_info.value.status_code == 400


def test_deleting_a_tenant_deletes_its_users(db):
    tenant = make_tenant(db, "Cascade Tenant")
    user = make_app_user(db, email="cascade@example.com", tenant_id=tenant.id)
    user_id = user.id

    db.delete(tenant)
    db.flush()
    db.expire_all()

    assert db.get(type(user), user_id) is None


def test_change_own_password_locks_out_after_repeated_wrong_current_password(db):
    """Audit finding, 2026-08-27: /me/password had no cap on wrong current_password guesses,
    so a hijacked/idle session could brute-force the account's real password purely through
    this endpoint. Verifies the account-scoped lockout added to change_own_password."""
    tenant = make_tenant(db, "Password Lockout Tenant")
    user = make_app_user(db, email="pw-lockout@example.com", password="correct horse battery staple", tenant_id=tenant.id, role_code="writer")
    actor = make_current_user(tenant.id, role="writer", user_id=user.id)
    service = UserService()

    for _ in range(_PASSWORD_CHANGE_ATTEMPT_LIMIT):
        payload = UserPasswordChange(current_password="wrong-password", new_password="a brand new password")
        with pytest.raises(HTTPException) as exc_info:
            service.change_own_password(db, actor, payload)
        assert exc_info.value.status_code == 400

    # Even the *correct* current password should now be rejected by the lockout.
    payload = UserPasswordChange(current_password="correct horse battery staple", new_password="a brand new password")
    with pytest.raises(HTTPException) as exc_info:
        service.change_own_password(db, actor, payload)
    assert exc_info.value.status_code == 429


# --- create_user -----------------------------------------------------------------------------


def test_create_user_defaults_to_actors_tenant_as_reader(db):
    tenant = make_tenant(db, "Create Default Tenant")

    result = UserService().create_user(db, _payload("new-person@example.com"), _admin_actor(tenant))

    assert result.tenant_id == tenant.public_id
    assert result.tenant_name == "Create Default Tenant"
    assert result.role_code == "reader"


def test_create_user_uses_requested_role(db):
    tenant = make_tenant(db, "Create Role Tenant")

    result = UserService().create_user(db, _payload("new-kassier@example.com", role_code="kassier"), _admin_actor(tenant))

    assert result.role_code == "kassier"


def test_create_user_rejects_unknown_role(db):
    tenant = make_tenant(db, "Create Unknown Role Tenant")

    with pytest.raises(HTTPException) as exc_info:
        UserService().create_user(db, _payload("bad-role@example.com", role_code="superadmin"), _admin_actor(tenant))
    assert exc_info.value.status_code == 400


def test_create_user_refuses_a_different_tenant(db):
    tenant_a = make_tenant(db, "Create Own Tenant")
    tenant_b = make_tenant(db, "Create Foreign Tenant")

    with pytest.raises(HTTPException) as exc_info:
        UserService().create_user(db, _payload("foreign-create@example.com", tenant_id=tenant_b.public_id), _admin_actor(tenant_a))
    assert exc_info.value.status_code == 403


def test_admin_create_user_requires_and_uses_the_given_tenant(db):
    tenant = make_tenant(db, "Platform Create Tenant")
    service = UserService()

    with pytest.raises(HTTPException) as exc_info:
        service.admin_create_user(db, _payload("platform-no-tenant@example.com"))
    assert exc_info.value.status_code == 422

    result = service.admin_create_user(db, _payload("platform-created@example.com", tenant_id=tenant.public_id, role_code="admin"))
    assert result.tenant_id == tenant.public_id
    assert result.role_code == "admin"


# --- participant login promotion ---------------------------------------------------------------


def _shadow_user(db, tenant, *, real_email: str):
    user = make_app_user(db, email=f"participant-{tenant.id}-1@participants.hocx.local", tenant_id=tenant.id)
    user.external_identity_json = {"source": "participant_auto", "login_enabled": False, "participant_email": real_email}
    db.add(user)
    db.flush()
    return user


def test_enabling_login_adopts_the_participants_real_email(db):
    tenant = make_tenant(db, "Promote Tenant")
    shadow = _shadow_user(db, tenant, real_email="real-person@example.com")

    result = UserService().update_user(
        db, shadow.id, UserUpdate(login_enabled=True, password="a-very-long-password-123"), _admin_actor(tenant)
    )

    assert result.email == "real-person@example.com"
    assert result.login_enabled is True


def test_enabling_login_merges_into_an_existing_account_of_the_same_tenant(db):
    tenant = make_tenant(db, "Promote Merge Tenant")
    existing = make_app_user(db, email="already-here@example.com", tenant_id=tenant.id, role_code="writer")
    acting_admin = make_app_user(db, email="promote-admin@example.com", tenant_id=tenant.id, role_code="admin")
    shadow = _shadow_user(db, tenant, real_email="already-here@example.com")
    original_hash = existing.password_hash
    service = UserService()

    result = service.update_user(
        db,
        shadow.id,
        UserUpdate(login_enabled=True, password="a-very-long-password-123"),
        _admin_actor(tenant, user_id=acting_admin.id),
    )

    assert result.id == existing.public_id
    assert service.repository.get(db, shadow.id) is None
    db.refresh(existing)
    # The unverified, admin-typed email must never overwrite the existing account's credentials.
    assert existing.password_hash == original_hash


def test_enabling_login_is_refused_when_the_email_belongs_to_another_tenant(db):
    tenant_a = make_tenant(db, "Promote Tenant A")
    tenant_b = make_tenant(db, "Promote Tenant B")
    foreign = make_app_user(db, email="taken@example.com", tenant_id=tenant_b.id)
    shadow = _shadow_user(db, tenant_a, real_email="taken@example.com")
    foreign_hash = foreign.password_hash
    service = UserService()

    with pytest.raises(HTTPException) as exc_info:
        service.update_user(
            db, shadow.id, UserUpdate(login_enabled=True, password="a-very-long-password-123"), _admin_actor(tenant_a)
        )

    assert exc_info.value.status_code == 409
    db.refresh(foreign)
    assert foreign.password_hash == foreign_hash
    assert foreign.tenant_id == tenant_b.id
