from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AppUser
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminTenantUserRead
from app.services.user_service import UserService


class AdminTenantUserService:
    """Manages the users of a single tenant from the tenant-settings side of the platform-admin
    panel (as opposed to admin_user_service.py, which lists and edits users across all tenants).
    A user belongs to exactly one tenant, so "granting" a role only ever changes the role of a
    user who is already in that tenant - creating users is admin_create_user's job."""

    def __init__(self, repository: UserRepository | None = None, user_service: UserService | None = None) -> None:
        self.repository = repository or UserRepository()
        self.user_service = user_service or UserService(self.repository)

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
        role_code_by_id = {role.id: role.code for role in self.repository.list_roles(db)}
        return [self._read_model(user, role_code_by_id[user.role_id]) for user in self.repository.list_by_tenant(db, tenant_id)]

    def _tenant_user(self, db: Session, tenant_id: int, user_id: int) -> AppUser | None:
        user = self.repository.get(db, user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    def set_role(self, db: Session, tenant_id: int, user_id: int, role_code: str) -> AdminTenantUserRead:
        user = self._tenant_user(db, tenant_id, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in this tenant")
        role_ids = {role.code: role.id for role in self.repository.list_roles(db)}
        if role_code not in role_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role '{role_code}'")

        self.user_service.guard_last_tenant_admin(db, user, role_code=role_code)
        user.role_id = role_ids[role_code]
        db.add(user)
        db.commit()
        return self._read_model(user, role_code)

    def delete_user(self, db: Session, tenant_id: int, user_id: int) -> bool:
        """Deletes the user's account (it exists nowhere else). False if the user isn't in the tenant."""
        user = self._tenant_user(db, tenant_id, user_id)
        if user is None:
            return False
        self.user_service.guard_last_tenant_admin(db, user, removed=True)
        self.repository.delete(db, user)
        db.commit()
        return True
