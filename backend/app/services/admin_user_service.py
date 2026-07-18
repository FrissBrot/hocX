from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.admin import PlatformAdminCreate, PlatformAdminRead, PlatformAdminUpdate
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService
from app.core.security import hash_password
from app.models import PlatformAdmin


class AdminUserService:
    """Cross-tenant AppUser management for the platform-admin panel."""

    def __init__(self, user_service: UserService | None = None) -> None:
        self.user_service = user_service or UserService()

    def list_users(self, db: Session) -> list[UserRead]:
        return self.user_service.list_all_users(db)

    def get_user(self, db: Session, user_id: int) -> UserRead | None:
        return self.user_service.admin_get_user(db, user_id)

    def create_user(self, db: Session, payload: UserCreate) -> UserRead:
        return self.user_service.admin_create_user(db, payload)

    def update_user(self, db: Session, user_id: int, payload: UserUpdate) -> UserRead | None:
        return self.user_service.admin_update_user(db, user_id, payload)

    def merge_users(self, db: Session, *, source_user_id: int, target_user_id: int) -> UserRead:
        return self.user_service.merge_users(db, source_user_id=source_user_id, target_user_id=target_user_id)


class PlatformAdminService:
    """Manages the platform-admin accounts themselves (self-service within /admin)."""

    def _read_model(self, admin: PlatformAdmin) -> PlatformAdminRead:
        return PlatformAdminRead.model_validate(admin)

    def list_admins(self, db: Session) -> list[PlatformAdminRead]:
        admins = db.query(PlatformAdmin).order_by(PlatformAdmin.email.asc()).all()
        return [self._read_model(admin) for admin in admins]

    def create_admin(self, db: Session, payload: PlatformAdminCreate) -> PlatformAdminRead:
        admin = PlatformAdmin(
            email=payload.email,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            is_active=payload.is_active,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return self._read_model(admin)

    def update_admin(self, db: Session, admin_id: int, payload: PlatformAdminUpdate, *, current_admin_id: int) -> PlatformAdminRead | None:
        admin = db.get(PlatformAdmin, admin_id)
        if admin is None:
            return None
        if payload.is_active is False and admin_id == current_admin_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own admin account")
        if payload.is_active is False:
            remaining_active = db.query(PlatformAdmin).filter(PlatformAdmin.id != admin_id, PlatformAdmin.is_active.is_(True)).count()
            if remaining_active == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin account is required")
        if payload.display_name is not None:
            admin.display_name = payload.display_name
        if payload.password:
            admin.password_hash = hash_password(payload.password)
        if payload.is_active is not None:
            admin.is_active = payload.is_active
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return self._read_model(admin)
