from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.security import CurrentUser, hash_password, require_admin, require_superadmin
from app.models import AppUser, Role, Tenant, UserTenantRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import TenantMembershipRead, TenantMembershipWrite, UserCreate, UserRead, UserSelfUpdate, UserUpdate


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()

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
                    role_code=role_map.get(membership.role_id, "reader"),
                    is_active=membership.is_active,
                )
            )
        return result

    def _admin_tenant_ids_for_actor(self, actor: CurrentUser) -> set[int]:
        if actor.is_superadmin:
            return {membership.tenant_id for membership in actor.available_tenants}
        return {
            membership.tenant_id
            for membership in actor.available_tenants
            if membership.role_code == "admin" and membership.is_active
        }

    def _read_model(self, db: Session, user: AppUser) -> UserRead:
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
            external_identity_json=user.external_identity_json or {},
            default_tenant_id=user.default_tenant_id,
            memberships=self._memberships_for_user(db, user.id),
            is_superadmin="superadmin" in self.repository.list_global_roles(db, user_id=user.id),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def list_users(self, db: Session, actor: CurrentUser):
        require_admin(actor)
        users = self.repository.list(db)
        if actor.is_superadmin:
            return [self._read_model(db, user) for user in users]

        allowed_user_ids = {
            membership.user_id
            for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if membership.is_active
        }
        return [self._read_model(db, user) for user in users if user.id in allowed_user_ids]

    def get_user(self, db: Session, user_id: int, actor: CurrentUser):
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        if actor.is_superadmin:
            return self._read_model(db, user)
        tenant_user_ids = {
            membership.user_id
            for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
            if membership.is_active
        }
        if user_id not in tenant_user_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not manageable in current tenant")
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
        if actor.is_superadmin:
            return memberships
        admin_tenant_ids = self._admin_tenant_ids_for_actor(actor)
        allowed = [membership for membership in memberships if membership.tenant_id in admin_tenant_ids]
        for membership in allowed:
            if membership.role_code == "superadmin":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin role is global only")
        return allowed

    def create_user(self, db: Session, payload: UserCreate, actor: CurrentUser):
        require_admin(actor)
        memberships = self._normalize_memberships(actor, payload.memberships)
        if not actor.is_superadmin and not memberships and actor.current_tenant_id is not None:
            memberships = [TenantMembershipWrite(tenant_id=actor.current_tenant_id, role_code="reader", is_active=True)]

        user = AppUser(
            default_tenant_id=payload.default_tenant_id or (memberships[0].tenant_id if memberships else actor.current_tenant_id),
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            name=payload.display_name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            oidc_subject=payload.oidc_subject,
            oidc_issuer=payload.oidc_issuer,
            oidc_email=payload.oidc_email,
            external_identity_json=payload.external_identity_json,
        )
        self.repository.create(db, user)
        self._apply_memberships(db, user.id, memberships, actor)
        if actor.is_superadmin:
            role_ids = self._role_id_by_code(db)
            self.repository.set_global_superadmin(
                db,
                user_id=user.id,
                enabled=payload.is_superadmin,
                superadmin_role_id=role_ids["superadmin"],
            )
        db.commit()
        return self._read_model(db, user)

    def _apply_memberships(
        self,
        db: Session,
        user_id: int,
        memberships: list[TenantMembershipWrite],
        actor: CurrentUser,
        *,
        merge_with_existing: bool = False,
    ) -> None:
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

        if not actor.is_superadmin:
            retained = [
                membership
                for membership in self.repository.list_memberships(db, user_id=user_id)
                if membership.tenant_id not in self._admin_tenant_ids_for_actor(actor)
            ]
            next_memberships = retained + [
                membership for membership in next_memberships if membership.tenant_id in self._admin_tenant_ids_for_actor(actor)
            ]

        self.repository.replace_memberships(db, user_id=user_id, memberships=next_memberships)

    def update_user(self, db: Session, user_id: int, payload: UserUpdate, actor: CurrentUser):
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        if not actor.is_superadmin:
            manageable_ids = {
                membership.user_id
                for membership in self.repository.list_memberships(db, tenant_id=actor.current_tenant_id)
                if membership.is_active
            }
            if user_id not in manageable_ids:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not manageable in current tenant")

        values = payload.model_dump(exclude_unset=True, exclude={"password", "memberships", "is_superadmin"})
        if "display_name" in values:
            values["name"] = values["display_name"]
        if payload.password:
            values["password_hash"] = hash_password(payload.password)
        if values:
            self.repository.update(db, user, values)
        if payload.memberships is not None:
            memberships = self._normalize_memberships(actor, payload.memberships)
            self._apply_memberships(db, user_id, memberships, actor, merge_with_existing=False)
        if actor.is_superadmin and payload.is_superadmin is not None:
            role_ids = self._role_id_by_code(db)
            self.repository.set_global_superadmin(
                db,
                user_id=user_id,
                enabled=payload.is_superadmin,
                superadmin_role_id=role_ids["superadmin"],
            )
        db.commit()
        return self._read_model(db, user)

    def delete_user(self, db: Session, user_id: int, actor: CurrentUser) -> bool:
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return False
        if actor.user_id == user_id and not actor.is_superadmin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own admin account")
        if not actor.is_superadmin:
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
