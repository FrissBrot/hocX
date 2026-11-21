from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import text
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

    def list_users(
        self, db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None, tenant_public_id: uuid.UUID | None = None,
    ) -> AdminUserPage:
        # list_all_users() already batch-loads everything in 3 queries total (see its
        # docstring) - offset/limit (and now q) are applied in Python rather than pushed
        # into that query so the existing N+1-avoidance logic doesn't need to change.
        #
        # q is applied BEFORE the offset/limit slice (audit A1, 2026-08-16): the admin
        # frontend's search box used to filter only the 50 already-fetched items of the
        # current page, so a match on page 3 was invisible while browsing page 1 - mirrors
        # the same name/email/tenant/role substring match the frontend used to do locally.
        all_users = self.user_service.list_all_users(db)
        if tenant_public_id is not None:
            all_users = [user for user in all_users if user.tenant_id == tenant_public_id]
        if q:
            query = q.strip().lower()
            if query:
                def _matches(user: UserRead) -> bool:
                    haystack = (
                        f"{user.display_name} {user.first_name} {user.last_name} {user.email} "
                        f"{user.tenant_name} {' '.join(role.name or role.system_key or '' for role in user.roles)}"
                    ).lower()
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



class PlatformAdminService:
    """Manages the platform-admin accounts themselves (self-service within /admin)."""

    def _read_model(self, admin: PlatformAdmin) -> PlatformAdminRead:
        return PlatformAdminRead.model_validate(admin)

    def list_admins(self, db: Session) -> list[PlatformAdminRead]:
        """Mit Passkey-Anzahl und letzter Anmeldung (1.5.1). Letzte Anmeldung aus auth_event
        (Index idx_auth_event_admin_ts, je Admin ein Indexzugriff); ältere Anmeldungen, die vor
        dem Anmeldeschutz oder ausserhalb der Aufbewahrung liegen, aus audit_log (admin.login)."""
        admins = db.query(PlatformAdmin).order_by(PlatformAdmin.email.asc()).all()
        if not admins:
            return []
        ids = [admin.id for admin in admins]
        passkeys = dict(db.execute(
            text(
                "SELECT platform_admin_id, count(*) FROM user_mfa_factor WHERE platform_admin_id = ANY(:ids) "
                "AND factor_type = 'webauthn' GROUP BY platform_admin_id"
            ),
            {"ids": ids},
        ).all())
        last_event = dict(db.execute(
            text(
                "SELECT a.id, (SELECT max(e.ts) FROM auth_event e WHERE e.platform_admin_id = a.id "
                "AND e.event_type = 'admin.login.success') FROM platform_admin a WHERE a.id = ANY(:ids)"
            ),
            {"ids": ids},
        ).all())
        missing = [admin.email for admin in admins if last_event.get(admin.id) is None]
        last_audit: dict[str, datetime] = {}
        if missing:
            last_audit = dict(db.execute(
                text(
                    "SELECT actor_email, max(created_at) FROM audit_log WHERE action = 'admin.login' "
                    "AND actor_email = ANY(:emails) GROUP BY actor_email"
                ),
                {"emails": missing},
            ).all())
        return [
            self._read_model(admin).model_copy(update={
                "passkey_count": int(passkeys.get(admin.id, 0)),
                "last_login_at": last_event.get(admin.id) or last_audit.get(admin.email),
            })
            for admin in admins
        ]

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
