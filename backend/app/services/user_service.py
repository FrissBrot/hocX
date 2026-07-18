from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.security import CurrentUser, hash_password, require_admin
from app.models import AppUser, Participant, UserTenantRole
from app.services.access_service import AccessService
from app.services.tenant_service import build_tenant_profile_image_url
from app.repositories.user_repository import UserRepository
from app.schemas.user import TenantMembershipRead, TenantMembershipWrite, UserCreate, UserRead, UserSelfUpdate, UserUpdate


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()
        self.access_service = AccessService()

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
                    tenant_id=tenant.id,
                    tenant_name=tenant.name,
                    tenant_profile_image_path=tenant.profile_image_path,
                    tenant_profile_image_url=build_tenant_profile_image_url(tenant.id, tenant.profile_image_path),
                    role_code=role_map.get(membership.role_id, "reader"),
                    is_active=membership.is_active,
                )
            )
        return result

    def _admin_tenant_ids_for_actor(self, actor: CurrentUser) -> set[int]:
        return {
            membership.tenant_id
            for membership in actor.available_tenants
            if membership.role_code == "admin" and membership.is_active
        }

    def _read_model(self, db: Session, user: AppUser) -> UserRead:
        external_identity = user.external_identity_json or {}
        return UserRead(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            email=user.email,
            preferred_language=user.preferred_language,
            is_active=user.is_active,
            oidc_subject=user.oidc_subject,
            oidc_issuer=user.oidc_issuer,
            oidc_email=user.oidc_email,
            external_identity_json=external_identity,
            default_tenant_id=user.default_tenant_id,
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
    ) -> UserRead:
        external_identity = user.external_identity_json or {}
        return UserRead(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            email=user.email,
            preferred_language=user.preferred_language,
            is_active=user.is_active,
            oidc_subject=user.oidc_subject,
            oidc_issuer=user.oidc_issuer,
            oidc_email=user.oidc_email,
            external_identity_json=external_identity,
            default_tenant_id=user.default_tenant_id,
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
                    tenant_id=tenant.id,
                    tenant_name=tenant.name,
                    tenant_profile_image_path=tenant.profile_image_path,
                    tenant_profile_image_url=build_tenant_profile_image_url(tenant.id, tenant.profile_image_path),
                    role_code=role_map.get(m.role_id, "reader"),
                    is_active=m.is_active,
                )
            )

        return [
            self._read_model_from_preloaded(user, memberships_by_user.get(user.id, []))
            for user in users
        ]

    def list_users(self, db: Session, actor: CurrentUser):
        require_admin(actor)
        allowed_ids = {
            m.user_id
            for m in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if m.is_active
        }
        return [user for user in self.list_all_users(db) if user.id in allowed_ids]

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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not manageable in current tenant")
        return self._read_model(db, user)

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
        memberships: list[TenantMembershipWrite] | None,
    ) -> list[TenantMembershipWrite]:
        if memberships is None:
            return []
        admin_tenant_ids = self._admin_tenant_ids_for_actor(actor)
        return [membership for membership in memberships if membership.tenant_id in admin_tenant_ids]

    def _new_app_user_from_payload(self, payload: UserCreate) -> AppUser:
        return AppUser(
            default_tenant_id=payload.default_tenant_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            oidc_subject=payload.oidc_subject,
            oidc_issuer=payload.oidc_issuer,
            oidc_email=payload.oidc_email,
            external_identity_json={
                **(payload.external_identity_json or {}),
                "login_enabled": payload.login_enabled,
            },
        )

    def create_user(self, db: Session, payload: UserCreate, actor: CurrentUser):
        require_admin(actor)
        memberships = self._normalize_memberships(actor, payload.memberships)
        if not memberships and actor.current_tenant_id is not None:
            memberships = [TenantMembershipWrite(tenant_id=actor.current_tenant_id, role_code="reader", is_active=True)]

        user = self._new_app_user_from_payload(payload)
        if user.default_tenant_id is None:
            user.default_tenant_id = memberships[0].tenant_id if memberships else actor.current_tenant_id
        self.repository.create(db, user)
        self._apply_memberships(db, user.id, memberships, actor)
        db.commit()
        return self._read_model(db, user)

    def admin_create_user(self, db: Session, payload: UserCreate) -> UserRead:
        """Unscoped user creation for the platform-admin panel - memberships can target any tenant."""
        user = self._new_app_user_from_payload(payload)
        if user.default_tenant_id is None and payload.memberships:
            user.default_tenant_id = payload.memberships[0].tenant_id
        self.repository.create(db, user)
        self._apply_memberships(db, user.id, payload.memberships, None)
        db.commit()
        return self._read_model(db, user)

    def _apply_memberships(
        self,
        db: Session,
        user_id: int,
        memberships: list[TenantMembershipWrite],
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

        if actor is not None:
            admin_tenant_ids = self._admin_tenant_ids_for_actor(actor)
            retained = [
                membership
                for membership in self.repository.list_memberships(db, user_id=user_id)
                if membership.tenant_id not in admin_tenant_ids
            ]
            next_memberships = retained + [
                membership for membership in next_memberships if membership.tenant_id in admin_tenant_ids
            ]

        self.repository.replace_memberships(db, user_id=user_id, memberships=next_memberships)

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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not manageable in current tenant")
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
            user = self._link_or_promote_participant_login(db, user, previous_external)

        if payload.memberships is not None:
            memberships = payload.memberships if actor is None else self._normalize_memberships(actor, payload.memberships)
            self._apply_memberships(db, user.id, memberships, actor, merge_with_existing=False)
        db.commit()
        return self._read_model(db, user)

    def _link_or_promote_participant_login(self, db: Session, user: AppUser, previous_external: dict) -> AppUser:
        """When a participant shadow account's login gets enabled, adopt its real email.

        If another AppUser already owns that email, merge the shadow account into it
        (adding this tenant's membership there) instead of creating a duplicate identity -
        the same person getting login access in a second tenant must stay one central user.
        `user` already carries the just-applied password/login_enabled at this point.
        """
        real_email = previous_external.get("participant_email") or user.oidc_email
        if not real_email or real_email == user.email:
            return user

        existing = self.repository.get_by_email(db, real_email)
        if existing is None or existing.id == user.id:
            return self.repository.update(db, user, {"email": real_email})

        # capture the login state that was just written to the shadow user before it is
        # deleted by the merge, then re-apply it onto the surviving target user
        login_state = {
            "password_hash": user.password_hash,
            "session_revoke_at": user.session_revoke_at,
        }
        self.merge_users(db, source_user_id=user.id, target_user_id=existing.id)
        target = self.repository.get(db, existing.id)
        login_state["external_identity_json"] = {
            **(target.external_identity_json or {}),
            "login_enabled": True,
        }
        return self.repository.update(db, target, login_state)

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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not manageable in current tenant")
        self.repository.delete(db, user)
        db.commit()
        return True

    def update_self(self, db: Session, actor: CurrentUser, payload: UserSelfUpdate):
        user = self.repository.get(db, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        values = payload.model_dump(exclude_unset=True)
        if values:
            self.repository.update(db, user, values)
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

        role_priority = {"reader": 1, "writer": 2, "admin": 3}

        merged_memberships: dict[int, TenantMembershipWrite] = {}
        for membership in self._memberships_for_user(db, target_user_id) + self._memberships_for_user(db, source_user_id):
            existing = merged_memberships.get(membership.tenant_id)
            candidate = TenantMembershipWrite(
                tenant_id=membership.tenant_id,
                role_code=membership.role_code,
                is_active=membership.is_active,
            )
            if existing is None:
                merged_memberships[membership.tenant_id] = candidate
                continue
            if role_priority.get(candidate.role_code, 0) > role_priority.get(existing.role_code, 0):
                merged_memberships[membership.tenant_id] = candidate
            elif candidate.is_active and not existing.is_active:
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
