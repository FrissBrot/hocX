from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.rate_limit import check_account_lockout, record_failed_attempt
from app.core.security import CurrentUser, hash_password, require_admin, verify_password
from app.models import AppUser, Participant, Tenant, UserTenantRole
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.tenant_service import build_tenant_profile_image_url
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    TenantMembershipRead,
    TenantMembershipWrite,
    UserCreate,
    UserPasswordChange,
    UserRead,
    UserSelfUpdate,
    UserUpdate,
)


# Account-scoped lockout on self-service current_password guesses (audit finding, 2026-08-27):
# /me/password lets an authenticated user try arbitrary current_password values with no cap,
# so a hijacked/idle session (or a shared device) could brute-force the account's real
# password via this endpoint even without the login form. Mirrors the login lockout pattern
# in auth_service.py, keyed by the authenticated user's id rather than email since the caller
# is already authenticated here.
_PASSWORD_CHANGE_ATTEMPT_LIMIT = 10
_PASSWORD_CHANGE_WINDOW_SECONDS = 15 * 60


@dataclass
class _ResolvedMembership:
    """Internal-id counterpart of TenantMembershipWrite - every function below this point
    in the file works with internal tenant ids exclusively; only the public entry points
    (create_user/admin_create_user/_update_user_core/merge_users) ever see the client-
    facing UUID-typed TenantMembershipWrite and resolve it to this shape first."""

    tenant_id: int
    role_code: str
    is_active: bool


def _resolve_memberships(db: Session, memberships: list[TenantMembershipWrite]) -> list[_ResolvedMembership]:
    tenant_ids = [m.tenant_id for m in memberships]
    id_map = public_id_service.resolve_internal_ids(db, Tenant, tenant_ids)
    resolved = []
    for m in memberships:
        internal_id = id_map.get(m.tenant_id)
        if internal_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {m.tenant_id} not found")
        resolved.append(_ResolvedMembership(tenant_id=internal_id, role_code=m.role_code, is_active=m.is_active))
    return resolved


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()
        self.access_service = AccessService()
        self.audit_service = AuditService()

    def _role_id_by_code(self, db: Session) -> dict[str, int]:
        return {role.code: role.id for role in self.repository.list_roles(db)}

    def _memberships_for_user(self, db: Session, user_id: int) -> list[TenantMembershipRead]:
        memberships = self.repository.list_memberships(db, user_id=user_id)
        role_map = {role.id: role.code for role in self.repository.list_roles(db)}
        tenant_map = {tenant.id: tenant for tenant in self.repository.list_tenants(db)}
        result: list[TenantMembershipRead] = []
        for membership in memberships:
            tenant = tenant_map.get(membership.tenant_id)
            if tenant is None:
                continue
            result.append(
                TenantMembershipRead(
                    tenant_id=tenant.public_id,
                    tenant_name=tenant.name,
                    tenant_profile_image_path=tenant.profile_image_path,
                    tenant_profile_image_url=build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path),
                    role_code=role_map.get(membership.role_id, "reader"),
                    is_active=membership.is_active,
                )
            )
        return result

    def _internal_memberships_for_user(self, db: Session, user_id: int) -> list[_ResolvedMembership]:
        """Internal-id counterpart of _memberships_for_user, for callers (merge_users) that
        need to recompute/pass memberships through _apply_memberships rather than serialize
        them to the API."""
        memberships = self.repository.list_memberships(db, user_id=user_id)
        role_map = {role.id: role.code for role in self.repository.list_roles(db)}
        return [
            _ResolvedMembership(
                tenant_id=membership.tenant_id,
                role_code=role_map.get(membership.role_id, "reader"),
                is_active=membership.is_active,
            )
            for membership in memberships
        ]

    def _admin_tenant_ids_for_actor(self, actor: CurrentUser) -> set[int]:
        return {
            membership.tenant_id
            for membership in actor.available_tenants
            if membership.role_code == "admin" and membership.is_active
        }

    def _admin_tenant_public_ids_for_actor(self, db: Session, actor: CurrentUser) -> set[uuid.UUID]:
        """Public-id counterpart of _admin_tenant_ids_for_actor, for scoping against
        UserRead.memberships[].tenant_id - which (like every other response-schema FK) is
        the tenant's public_id, not its internal int, since the public_id migration.
        Resolves via the DB from the actor's *internal* admin tenant ids rather than
        trusting CurrentUser.available_tenants[].tenant_public_id directly, since that field
        is only informational (populated once at session build time) and isn't guaranteed
        to be the authorization-relevant value here."""
        return set(
            public_id_service.resolve_public_ids(db, Tenant, list(self._admin_tenant_ids_for_actor(actor))).values()
        )

    def _scope_memberships(self, user: UserRead, visible_tenant_ids: set[uuid.UUID]) -> UserRead:
        """Restricts a UserRead's tenant memberships to the tenants the viewing actor is
        themselves admin of. Without this, a tenant admin who is merely allowed to *manage*
        a shared user (because that user also has a membership in the admin's own tenant)
        would otherwise see that user's role in every other tenant they belong to, including
        tenants the admin has no authority over.

        visible_tenant_ids is a set of tenant *public* ids - matching
        TenantMembershipRead.tenant_id, which is public since the public_id migration. Pass
        _admin_tenant_public_ids_for_actor(db, actor) here, not _admin_tenant_ids_for_actor's
        internal ints."""
        return user.model_copy(update={
            "memberships": [m for m in user.memberships if m.tenant_id in visible_tenant_ids]
        })

    def _read_model(self, db: Session, user: AppUser) -> UserRead:
        external_identity = user.external_identity_json or {}
        return UserRead(
            id=user.public_id,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            email=user.email,
            preferred_language=user.preferred_language,
            is_active=user.is_active,
            external_identity_json=external_identity,
            default_tenant_id=public_id_service.resolve_public_id(db, Tenant, user.default_tenant_id)
            if user.default_tenant_id is not None
            else None,
            memberships=self._memberships_for_user(db, user.id),
            login_enabled=external_identity.get("login_enabled") is not False,
            is_participant_account=external_identity.get("source") == "participant_auto",
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def _read_model_from_preloaded(
        self,
        user: AppUser,
        memberships: list[TenantMembershipRead],
        tenant_map: dict[int, Tenant],
    ) -> UserRead:
        external_identity = user.external_identity_json or {}
        default_tenant = tenant_map.get(user.default_tenant_id) if user.default_tenant_id is not None else None
        return UserRead(
            id=user.public_id,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            email=user.email,
            preferred_language=user.preferred_language,
            is_active=user.is_active,
            external_identity_json=external_identity,
            default_tenant_id=default_tenant.public_id if default_tenant is not None else None,
            memberships=memberships,
            login_enabled=external_identity.get("login_enabled") is not False,
            is_participant_account=external_identity.get("source") == "participant_auto",
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def list_all_users(self, db: Session) -> list[UserRead]:
        """Unscoped listing across every tenant - only for the platform-admin panel."""
        users = self.repository.list(db)
        if not users:
            return []

        user_ids = [u.id for u in users]

        # Batch-load all required data in 3 queries total (was N*4 before)
        all_memberships = self.repository.list_memberships_batch(db, user_ids=user_ids)
        role_map = {r.id: r.code for r in self.repository.list_roles(db)}
        tenant_map = {t.id: t for t in self.repository.list_tenants(db)}

        memberships_by_user: dict[int, list[TenantMembershipRead]] = {uid: [] for uid in user_ids}
        for m in all_memberships:
            tenant = tenant_map.get(m.tenant_id)
            if tenant is None:
                continue
            memberships_by_user[m.user_id].append(
                TenantMembershipRead(
                    tenant_id=tenant.public_id,
                    tenant_name=tenant.name,
                    tenant_profile_image_path=tenant.profile_image_path,
                    tenant_profile_image_url=build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path),
                    role_code=role_map.get(m.role_id, "reader"),
                    is_active=m.is_active,
                )
            )

        return [
            self._read_model_from_preloaded(user, memberships_by_user.get(user.id, []), tenant_map)
            for user in users
        ]

    def list_users(self, db: Session, actor: CurrentUser):
        require_admin(actor)
        allowed_ids = {
            m.user_id
            for m in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if m.is_active
        }
        # user.id below is UserRead.id, i.e. the user's public_id (see
        # _read_model_from_preloaded) - allowed_ids from the repository query is internal
        # ints, so it has to be translated before the membership check below, or every user
        # would be filtered out.
        allowed_public_ids = set(public_id_service.resolve_public_ids(db, AppUser, list(allowed_ids)).values())
        admin_tenant_ids = self._admin_tenant_public_ids_for_actor(db, actor)
        return [
            self._scope_memberships(user, admin_tenant_ids)
            for user in self.list_all_users(db)
            if user.id in allowed_public_ids
        ]

    def get_user(self, db: Session, user_id: int, actor: CurrentUser):
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        tenant_user_ids = {
            membership.user_id
            for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if membership.is_active
        }
        if user_id not in tenant_user_ids:
            # 404, not 403: a 403 here would confirm to a tenant-admin that a given user_id
            # exists in some *other* tenant, just not theirs - a user-enumeration channel across
            # tenant boundaries. Reporting "not found" either way closes that.
            return None
        return self._scope_memberships(self._read_model(db, user), self._admin_tenant_public_ids_for_actor(db, actor))

    def admin_get_user(self, db: Session, user_id: int) -> UserRead | None:
        """Unscoped single-user lookup for the platform-admin panel."""
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        return self._read_model(db, user)

    def get_self(self, db: Session, actor: CurrentUser) -> UserRead:
        user = self.repository.get(db, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return self._read_model(db, user)

    def _normalize_memberships(
        self,
        actor: CurrentUser,
        memberships: list[_ResolvedMembership] | None,
    ) -> list[_ResolvedMembership]:
        if memberships is None:
            return []
        admin_tenant_ids = self._admin_tenant_ids_for_actor(actor)
        return [membership for membership in memberships if membership.tenant_id in admin_tenant_ids]

    def _new_app_user_from_payload(self, db: Session, payload: UserCreate) -> AppUser:
        default_tenant_id = (
            public_id_service.resolve_internal_id(db, Tenant, payload.default_tenant_id)
            if payload.default_tenant_id is not None
            else None
        )
        return AppUser(
            default_tenant_id=default_tenant_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            external_identity_json={
                **(payload.external_identity_json or {}),
                "login_enabled": payload.login_enabled,
            },
        )

    def create_user(self, db: Session, payload: UserCreate, actor: CurrentUser):
        require_admin(actor)
        memberships = self._normalize_memberships(actor, _resolve_memberships(db, payload.memberships))
        if not memberships and actor.current_tenant_id is not None:
            memberships = [_ResolvedMembership(tenant_id=actor.current_tenant_id, role_code="reader", is_active=True)]

        user = self._new_app_user_from_payload(db, payload)
        if user.default_tenant_id is None:
            user.default_tenant_id = memberships[0].tenant_id if memberships else actor.current_tenant_id
        self.repository.create(db, user)
        self._apply_memberships(db, user.id, memberships, actor)
        db.commit()
        return self._read_model(db, user)

    def admin_create_user(self, db: Session, payload: UserCreate) -> UserRead:
        """Unscoped user creation for the platform-admin panel - memberships can target any tenant."""
        user = self._new_app_user_from_payload(db, payload)
        resolved_memberships = _resolve_memberships(db, payload.memberships)
        if user.default_tenant_id is None and resolved_memberships:
            user.default_tenant_id = resolved_memberships[0].tenant_id
        self.repository.create(db, user)
        self._apply_memberships(db, user.id, resolved_memberships, None)
        db.commit()
        return self._read_model(db, user)

    def _apply_memberships(
        self,
        db: Session,
        user_id: int,
        memberships: list[_ResolvedMembership],
        actor: CurrentUser | None,
        *,
        merge_with_existing: bool = False,
    ) -> None:
        """actor=None means the caller already established full authority over all tenants
        involved (platform-admin routes, internal merges) - membership scoping is skipped."""
        role_ids = self._role_id_by_code(db)
        next_memberships: list[UserTenantRole]

        if merge_with_existing:
            existing = {
                membership.tenant_id: membership
                for membership in self.repository.list_memberships(db, user_id=user_id)
            }
            for membership in memberships:
                existing[membership.tenant_id] = UserTenantRole(
                    user_id=user_id,
                    tenant_id=membership.tenant_id,
                    role_id=role_ids[membership.role_code],
                    is_active=membership.is_active,
                )
            next_memberships = list(existing.values())
        else:
            next_memberships = [
                UserTenantRole(
                    user_id=user_id,
                    tenant_id=membership.tenant_id,
                    role_id=role_ids[membership.role_code],
                    is_active=membership.is_active,
                )
                for membership in memberships
            ]

        admin_tenant_ids: set[int] | None = None
        if actor is not None:
            admin_tenant_ids = self._admin_tenant_ids_for_actor(actor)
            retained = [
                membership
                for membership in self.repository.list_memberships(db, user_id=user_id)
                if membership.tenant_id not in admin_tenant_ids
            ]
            # `retained` (already-persisted rows for tenants outside the actor's scope) is
            # only merged in here so _guard_last_tenant_admin below sees the true final
            # state of the user's memberships, not just the submitted/in-scope slice - it
            # must NOT be handed to replace_memberships for persistence (audit finding,
            # 2026-08-27: memberships in a tenant the calling admin doesn't manage must be
            # left completely untouched by this endpoint, regardless of what the payload
            # contains; the actual deletion scoping happens via scope_tenant_ids below).
            next_memberships = retained + [
                membership for membership in next_memberships if membership.tenant_id in admin_tenant_ids
            ]

        self._guard_last_tenant_admin(db, user_id, next_memberships, role_ids)

        if admin_tenant_ids is not None:
            self.repository.replace_memberships(
                db,
                user_id=user_id,
                memberships=[m for m in next_memberships if m.tenant_id in admin_tenant_ids],
                scope_tenant_ids=admin_tenant_ids,
            )
        else:
            self.repository.replace_memberships(db, user_id=user_id, memberships=next_memberships)

    def _guard_last_tenant_admin(
        self,
        db: Session,
        user_id: int,
        next_memberships: list[UserTenantRole],
        role_ids: dict[str, int],
    ) -> None:
        """Mirrors AdminTenantUserService's last-admin protection: this is the second,
        deliberately independent path (see class docstring) that can strip a user's admin
        membership - it must not be able to leave a tenant without any active admin either."""
        admin_role_id = role_ids.get("admin")
        if admin_role_id is None:
            return
        tenant_ids_still_admin = {
            m.tenant_id for m in next_memberships if m.role_id == admin_role_id and m.is_active
        }
        tenant_ids_was_admin = {
            m.tenant_id
            for m in self.repository.list_memberships(db, user_id=user_id)
            if m.role_id == admin_role_id and m.is_active
        }
        for tenant_id in tenant_ids_was_admin - tenant_ids_still_admin:
            remaining_admins = [
                m
                for m in self.repository.list_memberships(db, tenant_id=tenant_id)
                if m.role_id == admin_role_id and m.is_active and m.user_id != user_id
            ]
            if not remaining_admins:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden",
                )

    def update_user(self, db: Session, user_id: int, payload: UserUpdate, actor: CurrentUser):
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        manageable_ids = {
            membership.user_id
            for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if membership.is_active
        }
        if user_id not in manageable_ids:
            # 404, not 403 - see get_user's comment above on why (avoids cross-tenant user-id enumeration).
            return None
        return self._update_user_core(db, user, payload, actor)

    def admin_update_user(self, db: Session, user_id: int, payload: UserUpdate) -> UserRead | None:
        """Unscoped update for the platform-admin panel - no tenant-membership gate."""
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        return self._update_user_core(db, user, payload, actor=None)

    def _update_user_core(self, db: Session, user: AppUser, payload: UserUpdate, actor: CurrentUser | None):
        previous_external = user.external_identity_json or {}
        is_promoting_participant_login = (
            bool(payload.login_enabled)
            and previous_external.get("login_enabled") is False
            and previous_external.get("source") == "participant_auto"
        )

        values = payload.model_dump(exclude_unset=True, exclude={"password", "memberships"})
        if payload.login_enabled is not None:
            if payload.login_enabled and previous_external.get("login_enabled") is False and not payload.password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Set a password to enable login for this account",
                )
            values["external_identity_json"] = {
                **previous_external,
                "login_enabled": payload.login_enabled,
            }
        if payload.password:
            values["password_hash"] = hash_password(payload.password)
            # Password change invalidates all existing sessions
            values["session_revoke_at"] = datetime.now(UTC)
        if payload.is_active is False:
            # Deactivation invalidates all existing sessions
            values["session_revoke_at"] = datetime.now(UTC)
        if payload.login_enabled is False:
            # Disabling login invalidates all existing sessions
            values.setdefault("session_revoke_at", datetime.now(UTC))
        if values:
            self.repository.update(db, user, values)

        if is_promoting_participant_login:
            user = self._link_or_promote_participant_login(db, user, previous_external, actor)

        if payload.memberships is not None:
            resolved = _resolve_memberships(db, payload.memberships)
            memberships = resolved if actor is None else self._normalize_memberships(actor, resolved)
            self._apply_memberships(db, user.id, memberships, actor, merge_with_existing=False)
        db.commit()
        return self._read_model(db, user)

    def _link_or_promote_participant_login(
        self, db: Session, user: AppUser, previous_external: dict, actor: CurrentUser | None
    ) -> AppUser:
        """When a participant shadow account's login gets enabled, adopt its real email.

        If another AppUser already owns that email, merge the shadow account into it
        (adding this tenant's membership there) instead of creating a duplicate identity -
        the same person getting login access in a second tenant must stay one central user.
        `user` already carries the just-applied password/login_enabled at this point.
        """
        real_email = previous_external.get("participant_email")
        if not real_email or real_email == user.email:
            return user

        existing = self.repository.get_by_email(db, real_email)
        if existing is None or existing.id == user.id:
            return self.repository.update(db, user, {"email": real_email})

        # SECURITY: real_email is admin-typed and unverified (see the password_hash note
        # below), so this silently grants the target account membership in whichever
        # tenant the acting admin controls - without the target's consent or, before this
        # fix, any notification at all (audit finding, 2026-08-25). A full consent/
        # notification flow is out of scope for this pass (no email-sending
        # infrastructure exists yet); logging it here at least makes the action
        # discoverable/reviewable after the fact instead of leaving zero trace.
        self.audit_service.log(
            db,
            action="user.merged_via_participant_login_promotion",
            actor=actor,
            tenant_id=actor.current_tenant_id if actor else None,
            entity_type="app_user",
            entity_id=existing.id,
            details={"merged_from_user_id": user.id, "email": real_email},
        )

        # SECURITY: `real_email` is whatever email the tenant admin typed in when creating the
        # participant record - it is never verified to belong to the person setting it. Do NOT
        # carry the shadow account's password_hash/session_revoke_at over onto the pre-existing
        # target account here: that would let any tenant admin silently overwrite an unrelated
        # user's password (in ANY tenant) just by creating a participant with that user's email
        # and enabling login with a password of the admin's choosing - full account takeover
        # without ever knowing the victim's real password. The merge below only adds this
        # tenant's membership to the target; the target keeps its own existing credentials, and
        # if it never had a usable password before, it still needs one set through a channel
        # the account owner actually controls (e.g. an admin in a tenant they already access).
        self.merge_users(db, source_user_id=user.id, target_user_id=existing.id)
        target = self.repository.get(db, existing.id)
        return self.repository.update(
            db,
            target,
            {"external_identity_json": {**(target.external_identity_json or {}), "login_enabled": True}},
        )

    def delete_user(self, db: Session, user_id: int, actor: CurrentUser) -> bool:
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return False
        if actor.user_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own admin account")
        manageable_ids = {
            membership.user_id
            for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if membership.is_active
        }
        if user_id not in manageable_ids:
            # 404, not 403 - see get_user's comment above on why (avoids cross-tenant user-id enumeration).
            return False
        self.repository.delete(db, user)
        db.commit()
        return True

    def update_self(self, db: Session, actor: CurrentUser, payload: UserSelfUpdate):
        user = self.repository.get(db, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        values = payload.model_dump(exclude_unset=True)
        accordion_enabled = values.pop("protocol_accordion_enabled", None)
        if accordion_enabled is not None:
            values["external_identity_json"] = {
                **(user.external_identity_json or {}),
                "protocol_accordion_enabled": accordion_enabled,
            }
        if values:
            self.repository.update(db, user, values)
            db.commit()
        return self._read_model(db, user)

    def change_own_password(self, db: Session, actor: CurrentUser, payload: UserPasswordChange) -> UserRead:
        """Self-service password change while logged in. Requires the current password as
        confirmation (unlike the tenant-admin password-set path in _update_user_core, which
        an admin can use without knowing the target's old password). On success the new hash
        is stored and session_revoke_at is bumped so other active sessions using the old
        password are logged out - the same pattern already used there."""
        user = self.repository.get(db, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        lockout_key = f"password-change:{actor.user_id}"
        check_account_lockout(lockout_key, limit=_PASSWORD_CHANGE_ATTEMPT_LIMIT)
        if not user.password_hash or not verify_password(payload.current_password, user.password_hash):
            record_failed_attempt(lockout_key, period_seconds=_PASSWORD_CHANGE_WINDOW_SECONDS)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aktuelles Passwort ist nicht korrekt")

        self.repository.update(
            db,
            user,
            {
                "password_hash": hash_password(payload.new_password),
                "session_revoke_at": datetime.now(UTC),
            },
        )
        db.commit()
        return self._read_model(db, user)

    def merge_users(self, db: Session, *, source_user_id: int, target_user_id: int) -> UserRead:
        """Merges source into target: memberships, participant links and default tenant carry
        over, source is deleted. Callers are responsible for authorization (platform-admin
        route, or the internal participant-login auto-link in update_user)."""
        if source_user_id == target_user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source and target user must differ")

        source = self.repository.get(db, source_user_id)
        target = self.repository.get(db, target_user_id)
        if source is None or target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source or target user not found")

        conflicting_tenant_ids = {
            participant.tenant_id
            for participant in db.scalars(select(Participant).where(Participant.app_user_id == source_user_id))
        } & {
            participant.tenant_id
            for participant in db.scalars(select(Participant).where(Participant.app_user_id == target_user_id))
        }
        if conflicting_tenant_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Users cannot be merged because both are already linked to participants in the same tenant",
            )

        # Roles are capability bundles, not a linear rank: writer and kassier are deliberately
        # incomparable. Silently choosing either during a merge would discard the other
        # account's authority. Admin is the only role containing both bundles.
        role_capabilities = {
            "reader": frozenset({"read"}),
            "writer": frozenset({"read", "workspace_write"}),
            "kassier": frozenset({"read", "finance_write"}),
            "admin": frozenset({"read", "workspace_write", "finance_write", "tenant_admin"}),
        }

        merged_memberships: dict[int, _ResolvedMembership] = {}
        for membership in self._internal_memberships_for_user(db, target_user_id) + self._internal_memberships_for_user(db, source_user_id):
            existing = merged_memberships.get(membership.tenant_id)
            candidate = _ResolvedMembership(
                tenant_id=membership.tenant_id,
                role_code=membership.role_code,
                is_active=membership.is_active,
            )
            if existing is None:
                merged_memberships[membership.tenant_id] = candidate
                continue
            existing_capabilities = role_capabilities.get(existing.role_code, frozenset())
            candidate_capabilities = role_capabilities.get(candidate.role_code, frozenset())
            if existing_capabilities and candidate_capabilities and not (
                existing_capabilities <= candidate_capabilities or candidate_capabilities <= existing_capabilities
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Users cannot be merged automatically: roles '{existing.role_code}' and "
                        f"'{candidate.role_code}' are incompatible in the same tenant"
                    ),
                )
            if candidate_capabilities > existing_capabilities:
                merged_memberships[membership.tenant_id] = candidate
            elif candidate_capabilities == existing_capabilities and candidate.is_active and not existing.is_active:
                merged_memberships[membership.tenant_id] = candidate

        self._apply_memberships(
            db,
            target_user_id,
            list(merged_memberships.values()),
            None,
            merge_with_existing=False,
        )

        target_default_tenant_id = target.default_tenant_id or source.default_tenant_id
        self.repository.update(
            db,
            target,
            {
                "default_tenant_id": target_default_tenant_id,
                "external_identity_json": {
                    **(target.external_identity_json or {}),
                    "merged_user_ids": sorted(
                        {
                            *(target.external_identity_json or {}).get("merged_user_ids", []),
                            source_user_id,
                        }
                    ),
                },
            },
        )

        for participant in db.scalars(select(Participant).where(Participant.app_user_id == source_user_id)):
            participant.app_user_id = target_user_id
            db.add(participant)

        all_tenants = {
            membership.tenant_id
            for membership in merged_memberships.values()
        } | {
            participant.tenant_id
            for participant in db.scalars(select(Participant).where(Participant.app_user_id == target_user_id))
        }
        for tenant_id in all_tenants:
            self.access_service.sync_user_access_from_participants(db, user_id=target_user_id, tenant_id=tenant_id)

        self.repository.delete(db, source)
        db.commit()
        return self._read_model(db, target)
