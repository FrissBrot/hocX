from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.admin import AdminUserPage, PlatformAdminCreate, PlatformAdminRead, PlatformAdminUpdate
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService
from app.core.security import hash_password
from app.models import PlatformAdmin


class AdminUserService:
    """Cross-tenant AppUser management for the platform-admin panel."""

    def __init__(self, user_service: UserService | None = None) -> None:
        self.user_service = user_service or UserService()

    def list_users(self, db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None) -> AdminUserPage:
        # list_all_users() already batch-loads everything in 3 queries total (see its
        # docstring) - offset/limit (and now q) are applied in Python rather than pushed
        # into that query so the existing N+1-avoidance logic doesn't need to change.
        #
        # q is applied BEFORE the offset/limit slice (audit A1, 2026-08-16): the admin
        # frontend's search box used to filter only the 50 already-fetched items of the
        # current page, so a match on page 3 was invisible while browsing page 1 - mirrors
        # the same name/email/membership substring match the frontend used to do locally.
        all_users = self.user_service.list_all_users(db)
        if q:
            query = q.strip().lower()
            if query:
                def _matches(user: UserRead) -> bool:
                    membership_text = " ".join(f"{m.tenant_name} {m.role_code}" for m in user.memberships)
                    haystack = f"{user.display_name} {user.first_name} {user.last_name} {user.email} {membership_text}".lower()
                    return query in haystack

                all_users = [user for user in all_users if _matches(user)]
        total = len(all_users)
        items = all_users[offset : offset + limit] if limit is not None else all_users[offset:]
        return AdminUserPage(items=items, total=total)

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
            role=payload.role,
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
        if payload.role == "support":
            remaining_owners = db.query(PlatformAdmin).filter(
                PlatformAdmin.id != admin_id, PlatformAdmin.role == "owner", PlatformAdmin.is_active.is_(True)
            ).count()
            if remaining_owners == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active owner admin account is required")
        if payload.display_name is not None:
            admin.display_name = payload.display_name
        if payload.password:
            admin.password_hash = hash_password(payload.password)
            # Password change invalidates all existing sessions
            admin.session_revoke_at = datetime.now(UTC)
        if payload.is_active is False:
            # Deactivation invalidates all existing sessions
            admin.session_revoke_at = datetime.now(UTC)
        if payload.is_active is not None:
            admin.is_active = payload.is_active
        if payload.role is not None:
            admin.role = payload.role
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return self._read_model(admin)
