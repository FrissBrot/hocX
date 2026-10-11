from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.rate_limit import check_account_lockout, record_failed_attempt
from app.core.security import CurrentUser, hash_password, require_admin, verify_password
from app.models import AppUser, Tenant
from app.services import public_id_service
from app.services.access_service import AccessService
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
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


class UserService:
    """A user belongs to exactly one tenant with exactly one role (app_user.tenant_id/role_id).
    The tenant-admin entry points (list_users/get_user/create_user/update_user/delete_user)
    only ever see and touch users of the acting admin's own tenant - since the account can't
    exist anywhere else, that scoping is also complete authority over it. The admin_* entry
    points are the unscoped counterparts for the platform-admin panel."""

    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()
        self.access_service = AccessService()

    def _role_id_by_code(self, db: Session) -> dict[str, int]:
        return {role.code: role.id for role in self.repository.list_roles(db)}

    def _role_id(self, db: Session, role_code: str) -> int:
        role_id = self._role_id_by_code(db).get(role_code)
        if role_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role '{role_code}'")
        return role_id

    def _read_models(self, db: Session, users: list[AppUser]) -> list[UserRead]:
        if not users:
            return []
        tenants = {
            tenant.id: tenant
            for tenant in db.scalars(select(Tenant).where(Tenant.id.in_({user.tenant_id for user in users})))
        }
        role_codes = {role.id: role.code for role in self.repository.list_roles(db)}
        result = []
        for user in users:
            external_identity = user.external_identity_json or {}
            tenant = tenants[user.tenant_id]
            result.append(
                UserRead(
                    id=user.public_id,
                    tenant_id=tenant.public_id,
                    tenant_name=tenant.name,
                    role_code=role_codes[user.role_id],
                    first_name=user.first_name,
                    last_name=user.last_name,
                    display_name=user.display_name,
                    email=user.email,
                    preferred_language=user.preferred_language,
                    is_active=user.is_active,
                    external_identity_json=external_identity,
                    login_enabled=user.login_enabled,
                    joined_at=user.joined_at,
                    left_at=user.left_at,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
            )
        return result

    def _read_model(self, db: Session, user: AppUser) -> UserRead:
        return self._read_models(db, [user])[0]

    def _tenant_user(self, db: Session, user_id: int, actor: CurrentUser) -> AppUser | None:
        """The user, but only if they belong to the actor's tenant. None (-> 404, not 403) for
        a user of another tenant, so an admin can't probe which user ids exist elsewhere."""
        user = self.repository.get(db, user_id)
        if user is None or user.tenant_id != actor.current_tenant_id:
            return None
        return user

    def list_all_users(self, db: Session) -> list[UserRead]:
        """Unscoped listing across every tenant - only for the platform-admin panel."""
        return self._read_models(db, self.repository.list(db))

    def list_users(self, db: Session, actor: CurrentUser):
        require_admin(actor)
        return self._read_models(db, self.repository.list_by_tenant(db, actor.current_tenant_id))

    def get_user(self, db: Session, user_id: int, actor: CurrentUser):
        require_admin(actor)
        user = self._tenant_user(db, user_id, actor)
        return self._read_model(db, user) if user is not None else None

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

    def _new_app_user(self, db: Session, payload: UserCreate, *, tenant_id: int) -> AppUser:
        if payload.login_enabled:
            self.ensure_login_email_available(db, payload.email)
        return AppUser(
            tenant_id=tenant_id,
            role_id=self._role_id(db, payload.role_code),
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            email=payload.email.strip().lower() if payload.email and payload.email.strip() else None,
            login_enabled=payload.login_enabled,
            joined_at=payload.joined_at,
            left_at=payload.left_at,
            password_hash=hash_password(payload.password) if payload.password else None,
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            external_identity_json=payload.external_identity_json or {},
        )

    def create_user(self, db: Session, payload: UserCreate, actor: CurrentUser):
        require_admin(actor)
        if payload.tenant_id is not None and payload.tenant_id != actor.current_tenant_public_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Users can only be created in the own tenant")
        user = self._new_app_user(db, payload, tenant_id=actor.current_tenant_id)
        self.repository.create(db, user)
        db.commit()
        return self._read_model(db, user)

    def admin_create_user(self, db: Session, payload: UserCreate) -> UserRead:
        """Unscoped user creation for the platform-admin panel - the tenant is picked explicitly."""
        if payload.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="tenant_id is required")
        tenant_id = public_id_service.resolve_internal_id(db, Tenant, payload.tenant_id)
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
        user = self._new_app_user(db, payload, tenant_id=tenant_id)
        self.repository.create(db, user)
        db.commit()
        return self._read_model(db, user)

    def guard_last_tenant_admin(
        self,
        db: Session,
        user: AppUser,
        *,
        role_code: str | None = None,
        is_active: bool | None = None,
        removed: bool = False,
    ) -> None:
        """A tenant must never be left without an active admin: blocks demoting, deactivating
        or deleting (removed=True) the tenant's last active admin. role_code/is_active are the
        values the user is about to get (None = unchanged). Shared with AdminTenantUserService
        so every entry point enforces the same rule."""
        current_role_code = next((r.code for r in self.repository.list_roles(db) if r.id == user.role_id), None)
        if not (user.is_active and user.login_enabled and current_role_code == "admin"):
            return
        next_role_code = role_code or current_role_code
        next_is_active = user.is_active if is_active is None else is_active
        if not removed and next_role_code == "admin" and next_is_active:
            return
        if self.repository.count_active_admins(db, user.tenant_id, excluding_user_id=user.id) == 0:
            detail = (
                "Der letzte Administrator eines Mandanten kann nicht deaktiviert werden"
                if not removed and next_role_code == "admin"
                else "Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden"
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    def update_user(self, db: Session, user_id: int, payload: UserUpdate, actor: CurrentUser):
        require_admin(actor)
        user = self._tenant_user(db, user_id, actor)
        if user is None:
            return None
        return self._update_user_core(db, user, payload, actor)

    def admin_update_user(self, db: Session, user_id: int, payload: UserUpdate) -> UserRead | None:
        """Unscoped update for the platform-admin panel - no tenant gate."""
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        return self._update_user_core(db, user, payload, actor=None)

    def _update_user_core(self, db: Session, user: AppUser, payload: UserUpdate, actor: CurrentUser | None):
        values = payload.model_dump(exclude_unset=True, exclude={"password", "role_code"})
        if "email" in values:
            values["email"] = values["email"].strip().lower() if values["email"] and values["email"].strip() else None
        if payload.role_code is not None:
            values["role_id"] = self._role_id(db, payload.role_code)
        self.guard_last_tenant_admin(
            db, user, role_code=payload.role_code, is_active=payload.is_active,
            removed=payload.login_enabled is False,
        )
        login_enabled = user.login_enabled if payload.login_enabled is None else payload.login_enabled
        if login_enabled:
            email = values.get("email", user.email)
            if not email or not email.strip():
                raise HTTPException(status_code=400, detail="Eine E-Mail-Adresse ist für einen Login erforderlich")
            if not user.login_enabled and not payload.password:
                raise HTTPException(status_code=400, detail="Set a password to enable login for this account")
            self.ensure_login_email_available(db, email, excluding_user_id=user.id)
        joined_at = values.get("joined_at", user.joined_at)
        left_at = values.get("left_at", user.left_at)
        if joined_at and left_at and left_at < joined_at:
            raise ValueError("left_at must not be before joined_at")
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

        if payload.is_active is not None:
            self.access_service.sync_user_access_from_participants(db, user_id=user.id, tenant_id=user.tenant_id)
        db.commit()
        return self._read_model(db, user)

    def ensure_login_email_available(self, db: Session, email: str, *, excluding_user_id: int | None = None) -> None:
        statement = select(AppUser.id).where(AppUser.login_enabled.is_(True), AppUser.email == email.strip().lower())
        if excluding_user_id is not None:
            statement = statement.where(AppUser.id != excluding_user_id)
        if db.scalar(statement) is not None:
            raise HTTPException(status_code=409, detail="Diese E-Mail-Adresse wird bereits für einen Login verwendet")

    def delete_user(self, db: Session, user_id: int, actor: CurrentUser) -> bool:
        require_admin(actor)
        user = self.repository.get(db, user_id)
        if user is None:
            return False
        if actor.user_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own admin account")
        if user.tenant_id != actor.current_tenant_id:
            # 404, not 403 - see _tenant_user (avoids cross-tenant user-id enumeration).
            return False
        self.guard_last_tenant_admin(db, user, removed=True)
        from app.services.participant_service import ParticipantService
        return ParticipantService().delete_participant(db, user_id, tenant_id=user.tenant_id)

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
