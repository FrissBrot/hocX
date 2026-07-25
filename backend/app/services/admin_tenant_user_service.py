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
            user_id=user.id,
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

    def grant_or_update_role(self, db: Session, tenant_id: int, user_id: int, role_code: str) -> AdminTenantUserRead:
        user = self.repository.get(db, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        role_ids = {role.code: role.id for role in self.repository.list_roles(db)}
        if role_code not in role_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role '{role_code}'")

        existing = next(
            (m for m in self.repository.list_memberships(db, tenant_id=tenant_id) if m.user_id == user_id), None
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
        existing = next(
            (m for m in self.repository.list_memberships(db, tenant_id=tenant_id) if m.user_id == user_id), None
        )
        if existing is None:
            return False
        db.delete(existing)
        db.commit()
        return True
