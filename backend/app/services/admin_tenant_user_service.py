from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AppUser, UserTenantRole
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminTenantUserRead


class AdminTenantUserService:
    """Manages who has access to a single tenant, from the tenant-settings side (as opposed
    to admin_user_service.py, which manages a user's memberships across all tenants at
    once) - grant/change/remove here always touches exactly one UserTenantRole row, so
    changing a role never requires removing and re-adding the membership."""

    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()

    def _read_model(self, user: AppUser, role_code: str) -> AdminTenantUserRead:
        return AdminTenantUserRead(
            user_id=user.public_id,
            email=user.email,
            display_name=user.display_name,
            role_code=role_code,
            login_enabled=(user.external_identity_json or {}).get("login_enabled", True) is not False,
            is_active=user.is_active,
        )

    def list_users(self, db: Session, tenant_id: int) -> list[AdminTenantUserRead]:
        memberships = self.repository.list_memberships(db, tenant_id=tenant_id)
        role_code_by_id = {role.id: role.code for role in self.repository.list_roles(db)}
        users_by_id = {user.id: user for user in db.query(AppUser).filter(AppUser.id.in_([m.user_id for m in memberships])).all()}
        return [
            self._read_model(users_by_id[m.user_id], role_code_by_id[m.role_id])
            for m in memberships
            if m.user_id in users_by_id
        ]

    @staticmethod
    def _is_last_active_admin(
        memberships: list[UserTenantRole], *, admin_role_id: int | None, user_id: int
    ) -> bool:
        """True if user_id is currently an active admin of the tenant and no other active
        admin membership exists among `memberships` (which must already be scoped to the
        tenant in question)."""
        if admin_role_id is None:
            return False
        is_active_admin = any(
            m.user_id == user_id and m.is_active and m.role_id == admin_role_id for m in memberships
        )
        if not is_active_admin:
            return False
        remaining_admins = [
            m for m in memberships if m.role_id == admin_role_id and m.is_active and m.user_id != user_id
        ]
        return not remaining_admins

    def grant_or_update_role(self, db: Session, tenant_id: int, user_id: int, role_code: str) -> AdminTenantUserRead:
        user = self.repository.get(db, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        role_ids = {role.code: role.id for role in self.repository.list_roles(db)}
        if role_code not in role_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role '{role_code}'")

        memberships = self.repository.list_memberships(db, tenant_id=tenant_id)
        existing = next((m for m in memberships if m.user_id == user_id), None)

        admin_role_id = role_ids.get("admin")
        if role_ids[role_code] != admin_role_id and self._is_last_active_admin(
            memberships, admin_role_id=admin_role_id, user_id=user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Der letzte Administrator eines Mandanten kann nicht auf eine niedrigere Rolle herabgestuft werden",
            )

        if existing is not None:
            existing.role_id = role_ids[role_code]
            existing.is_active = True
            db.add(existing)
        else:
            db.add(UserTenantRole(user_id=user_id, tenant_id=tenant_id, role_id=role_ids[role_code], is_active=True))
        db.commit()
        return self._read_model(user, role_code)

    def remove_user(self, db: Session, tenant_id: int, user_id: int) -> bool:
        memberships = self.repository.list_memberships(db, tenant_id=tenant_id)
        existing = next((m for m in memberships if m.user_id == user_id), None)
        if existing is None:
            return False

        role_ids = {role.code: role.id for role in self.repository.list_roles(db)}
        if self._is_last_active_admin(memberships, admin_role_id=role_ids.get("admin"), user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Der letzte Administrator eines Mandanten kann nicht entfernt werden",
            )

        db.delete(existing)
        db.commit()
        return True
