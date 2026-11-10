from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AppUser, TenantRole
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminTenantUserRead
from app.services import role_service
from app.services.user_service import UserService


class AdminTenantUserService:
    """Manages the users of a single tenant from the tenant-settings side of the platform-admin
    panel (as opposed to admin_user_service.py, which lists and edits users across all tenants).
    A user belongs to exactly one tenant, so "granting" a role only ever changes the roles of a
    user who is already in that tenant - creating users is admin_create_user's job. The platform
    admin only assigns standard roles (e.g. "Administrator" in an emergency); custom roles are
    the tenant's own business (role_service)."""

    def __init__(self, repository: UserRepository | None = None, user_service: UserService | None = None) -> None:
        self.repository = repository or UserRepository()
        self.user_service = user_service or UserService(self.repository)

    def _read_model(self, user: AppUser, roles: list[TenantRole]) -> AdminTenantUserRead:
        return AdminTenantUserRead(
            user_id=user.public_id,
            email=user.email,
            display_name=user.display_name,
            roles=[role_service.role_ref(role) for role in roles],
            login_enabled=user.login_enabled,
            is_active=user.is_active,
        )

    def list_users(self, db: Session, tenant_id: int) -> list[AdminTenantUserRead]:
        users = self.repository.list_by_tenant(db, tenant_id)
        roles = role_service.roles_by_user(db, [user.id for user in users])
        return [self._read_model(user, roles.get(user.id, [])) for user in users]

    def _tenant_user(self, db: Session, tenant_id: int, user_id: int) -> AppUser | None:
        user = self.repository.get(db, user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    def set_role(self, db: Session, tenant_id: int, user_id: int, role_code: str) -> AdminTenantUserRead:
        """Ersetzt alle Rollen des Kontos durch genau die Standardrolle role_code (Schutz des
        letzten Administrators gilt auch hier)."""
        user = self._tenant_user(db, tenant_id, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in this tenant")
        role = role_service.system_role(db, tenant_id, role_code)
        role_service.set_user_roles(db, None, user, [role])
        db.commit()
        return self._read_model(user, role_service.roles_by_user(db, [user.id]).get(user.id, []))

    def delete_user(self, db: Session, tenant_id: int, user_id: int) -> bool:
        """Deletes the user's account (it exists nowhere else). False if the user isn't in the tenant."""
        user = self._tenant_user(db, tenant_id, user_id)
        if user is None:
            return False
        from app.services.participant_service import ParticipantService
        return ParticipantService().delete_participant(db, user_id, tenant_id=tenant_id)
