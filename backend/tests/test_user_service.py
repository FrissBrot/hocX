"""Regression tests for UserService - previously zero coverage despite owning two
security-sensitive pieces of logic: (1) the role_priority merge in merge_users(), fixed in the
critical-severity audit round (kassier sits strictly between reader and writer on a single
linear scale, not as an orthogonal permission), and (2) the "last tenant admin" guard shared
between update_user/create_user's membership-apply path and AdminTenantUserService's - a
tenant must never end up with zero active admins. Also covers the basic tenant-isolation
boundary on get_user/update_user/delete_user (an admin in tenant A must not manage users who
only belong to tenant B)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security import CurrentUser, TenantMembership
from app.schemas.user import TenantMembershipWrite, UserCreate, UserUpdate
from app.services.user_service import UserService
from tests.factories import make_app_user, make_current_user, make_participant, make_tenant, make_user_tenant_role


def _admin_actor(tenant_id: int, *, user_id: int = 999999, extra_tenants: list[TenantMembership] | None = None) -> CurrentUser:
    memberships = [
        TenantMembership(
            tenant_id=tenant_id, tenant_name="Admin Tenant", tenant_profile_image_path=None, role_code="admin", is_active=True
        )
    ] + (extra_tenants or [])
    return CurrentUser(
        user_id=user_id,
        first_name="Admin",
        last_name="Actor",
        display_name="Admin Actor",
        email="admin-actor@example.com",
        preferred_language="de",
        is_participant_account=False,
        default_tenant_id=tenant_id,
        current_tenant_id=tenant_id,
        current_tenant_name="Admin Tenant",
        current_tenant_profile_image_path=None,
        current_role="admin",
        available_tenants=memberships,
    )


# --- merge_users: role_priority merge logic (critical-round fix) -------------------------


def test_merge_users_prefers_higher_role_writer_over_reader(db):
    tenant = make_tenant(db, "Merge Tenant")
    target = make_app_user(db, email="target@example.com")
    source = make_app_user(db, email="source@example.com")
    make_user_tenant_role(db, target.id, tenant.id, role_code="reader")
    make_user_tenant_role(db, source.id, tenant.id, role_code="writer")

    service = UserService()
    result = service.merge_users(db, source_user_id=source.id, target_user_id=target.id)

    membership = next(m for m in result.memberships if m.tenant_id == tenant.id)
    assert membership.role_code == "writer"


def test_merge_users_kassier_sits_between_reader_and_writer(db):
    """kassier(2) must beat reader(1) but lose to writer(3) - the exact ordering fixed in the
    critical-severity audit round (role_priority = {reader:1, kassier:2, writer:3, admin:4})."""
    tenant = make_tenant(db, "Kassier Merge Tenant")

    target_a = make_app_user(db, email="target-a@example.com")
    source_a = make_app_user(db, email="source-a@example.com")
    make_user_tenant_role(db, target_a.id, tenant.id, role_code="reader")
    make_user_tenant_role(db, source_a.id, tenant.id, role_code="kassier")

    service = UserService()
    result_a = service.merge_users(db, source_user_id=source_a.id, target_user_id=target_a.id)
    membership_a = next(m for m in result_a.memberships if m.tenant_id == tenant.id)
    assert membership_a.role_code == "kassier"

    tenant_b = make_tenant(db, "Kassier Merge Tenant B")
    target_b = make_app_user(db, email="target-b@example.com")
    source_b = make_app_user(db, email="source-b@example.com")
    make_user_tenant_role(db, target_b.id, tenant_b.id, role_code="kassier")
    make_user_tenant_role(db, source_b.id, tenant_b.id, role_code="writer")

    result_b = service.merge_users(db, source_user_id=source_b.id, target_user_id=target_b.id)
    membership_b = next(m for m in result_b.memberships if m.tenant_id == tenant_b.id)
    assert membership_b.role_code == "writer"


def test_merge_users_prefers_active_membership_when_role_priority_equal(db):
    tenant = make_tenant(db, "Active Merge Tenant")
    target = make_app_user(db, email="target-inactive@example.com")
    source = make_app_user(db, email="source-active@example.com")
    make_user_tenant_role(db, target.id, tenant.id, role_code="reader", is_active=False)
    make_user_tenant_role(db, source.id, tenant.id, role_code="reader", is_active=True)

    service = UserService()
    result = service.merge_users(db, source_user_id=source.id, target_user_id=target.id)

    membership = next(m for m in result.memberships if m.tenant_id == tenant.id)
    assert membership.is_active is True


def test_merge_users_raises_when_source_equals_target(db):
    tenant = make_tenant(db)
    user = make_app_user(db)
    make_user_tenant_role(db, user.id, tenant.id, role_code="reader")

    service = UserService()
    with pytest.raises(HTTPException) as exc_info:
        service.merge_users(db, source_user_id=user.id, target_user_id=user.id)
    assert exc_info.value.status_code == 400


def test_merge_users_raises_on_conflicting_participant_links(db):
    """Both accounts already linked to a (different) participant in the same tenant - merging
    would silently orphan one of the two participant links, so the service must refuse."""
    tenant = make_tenant(db, "Conflict Tenant")
    target = make_app_user(db, email="target-conflict@example.com")
    source = make_app_user(db, email="source-conflict@example.com")
    make_user_tenant_role(db, target.id, tenant.id, role_code="reader")
    make_user_tenant_role(db, source.id, tenant.id, role_code="reader")

    participant_target = make_participant(db, tenant.id, display_name="Target Person")
    participant_target.app_user_id = target.id
    participant_source = make_participant(db, tenant.id, display_name="Source Person")
    participant_source.app_user_id = source.id
    db.add_all([participant_target, participant_source])
    db.flush()

    service = UserService()
    with pytest.raises(HTTPException) as exc_info:
        service.merge_users(db, source_user_id=source.id, target_user_id=target.id)
    assert exc_info.value.status_code == 400


def test_merge_users_moves_participant_link_and_deletes_source(db):
    tenant = make_tenant(db, "Move Link Tenant")
    target = make_app_user(db, email="target-move@example.com")
    source = make_app_user(db, email="source-move@example.com")
    make_user_tenant_role(db, target.id, tenant.id, role_code="reader")
    make_user_tenant_role(db, source.id, tenant.id, role_code="reader")

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
    admin_user = make_app_user(db, email="only-admin@example.com")
    make_user_tenant_role(db, admin_user.id, tenant.id, role_code="admin")

    actor = _admin_actor(tenant.id, user_id=admin_user.id + 1)
    service = UserService()
    payload = UserUpdate(memberships=[TenantMembershipWrite(tenant_id=tenant.id, role_code="reader", is_active=True)])

    with pytest.raises(HTTPException) as exc_info:
        service.update_user(db, admin_user.id, payload, actor)
    assert exc_info.value.status_code == 409


def test_update_user_allows_demoting_admin_when_another_admin_remains(db):
    tenant = make_tenant(db, "Two Admins Tenant")
    admin_one = make_app_user(db, email="admin-one@example.com")
    admin_two = make_app_user(db, email="admin-two@example.com")
    make_user_tenant_role(db, admin_one.id, tenant.id, role_code="admin")
    make_user_tenant_role(db, admin_two.id, tenant.id, role_code="admin")

    actor = _admin_actor(tenant.id, user_id=admin_two.id)
    service = UserService()
    payload = UserUpdate(memberships=[TenantMembershipWrite(tenant_id=tenant.id, role_code="reader", is_active=True)])

    result = service.update_user(db, admin_one.id, payload, actor)
    membership = next(m for m in result.memberships if m.tenant_id == tenant.id)
    assert membership.role_code == "reader"


# --- tenant isolation boundary --------------------------------------------------------------


def test_get_user_forbidden_when_target_user_not_in_actors_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    actor_user = make_app_user(db, email="actor@example.com")
    make_user_tenant_role(db, actor_user.id, tenant_a.id, role_code="admin")
    other_user = make_app_user(db, email="other-tenant-user@example.com")
    make_user_tenant_role(db, other_user.id, tenant_b.id, role_code="reader")

    actor = _admin_actor(tenant_a.id, user_id=actor_user.id)
    service = UserService()

    with pytest.raises(HTTPException) as exc_info:
        service.get_user(db, other_user.id, actor)
    assert exc_info.value.status_code == 403


def test_get_user_hides_memberships_in_tenants_actor_does_not_administer(db):
    """A shared user who is a member of both the actor's tenant and an unrelated tenant is
    manageable (the actor sees basic info), but the actor must not learn what role that user
    holds in the other tenant - only tenants the *actor themselves* administers are visible."""
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    actor_user = make_app_user(db, email="actor2@example.com")
    make_user_tenant_role(db, actor_user.id, tenant_a.id, role_code="admin")
    shared_user = make_app_user(db, email="shared-user@example.com")
    make_user_tenant_role(db, shared_user.id, tenant_a.id, role_code="reader")
    make_user_tenant_role(db, shared_user.id, tenant_b.id, role_code="admin")

    actor = _admin_actor(tenant_a.id, user_id=actor_user.id)
    service = UserService()

    result = service.get_user(db, shared_user.id, actor)
    visible_tenant_ids = {m.tenant_id for m in result.memberships}
    assert visible_tenant_ids == {tenant_a.id}


def test_list_users_hides_memberships_in_tenants_actor_does_not_administer(db):
    tenant_a = make_tenant(db, "Tenant A List")
    tenant_b = make_tenant(db, "Tenant B List")
    actor_user = make_app_user(db, email="actor3@example.com")
    make_user_tenant_role(db, actor_user.id, tenant_a.id, role_code="admin")
    shared_user = make_app_user(db, email="shared-user-2@example.com")
    make_user_tenant_role(db, shared_user.id, tenant_a.id, role_code="reader")
    make_user_tenant_role(db, shared_user.id, tenant_b.id, role_code="admin")

    actor = _admin_actor(tenant_a.id, user_id=actor_user.id)
    service = UserService()

    results = service.list_users(db, actor)
    listed = next(u for u in results if u.id == shared_user.id)
    visible_tenant_ids = {m.tenant_id for m in listed.memberships}
    assert visible_tenant_ids == {tenant_a.id}


def test_delete_user_cannot_delete_own_account(db):
    tenant = make_tenant(db, "Self Delete Tenant")
    admin_user = make_app_user(db, email="self-delete@example.com")
    make_user_tenant_role(db, admin_user.id, tenant.id, role_code="admin")

    actor = _admin_actor(tenant.id, user_id=admin_user.id)
    service = UserService()

    with pytest.raises(HTTPException) as exc_info:
        service.delete_user(db, admin_user.id, actor)
    assert exc_info.value.status_code == 400


# --- create_user ------------------------------------------------------------------------------


def test_create_user_defaults_membership_to_actors_current_tenant_as_reader(db):
    tenant = make_tenant(db, "Create Default Tenant")
    admin_user = make_app_user(db, email="creator@example.com")
    make_user_tenant_role(db, admin_user.id, tenant.id, role_code="admin")
    actor = _admin_actor(tenant.id, user_id=admin_user.id)

    service = UserService()
    payload = UserCreate(
        first_name="New",
        last_name="Person",
        display_name="New Person",
        email="new-person@example.com",
        password="a-very-long-password-123",
        memberships=[],
    )
    result = service.create_user(db, payload, actor)

    assert len(result.memberships) == 1
    assert result.memberships[0].tenant_id == tenant.id
    assert result.memberships[0].role_code == "reader"
