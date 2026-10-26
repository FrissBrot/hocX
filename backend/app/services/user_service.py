from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.rate_limit import check_account_lockout, record_failed_attempt
from app.core.permissions import P
from app.core.security import CurrentUser, hash_password, require_permission, verify_password
from app.core.tenant_scope import tenant_scope_suspended
from app.models import AppUser, Tenant
from app.services import public_id_service
from app.services import role_service
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
    """A user belongs to exactly one tenant (app_user.tenant_id) and has one or more of that
    tenant's roles (user_role, see role_service). The tenant entry points (list_users/get_user/
    create_user/update_user/delete_user, all access.manage) only ever see and touch users of the
    actor's own tenant and apply role_service's guards (no privilege escalation, last capable
    admin, no self-removal). The admin_* entry points are the unscoped counterparts for the
    platform-admin panel (actor=None: no escalation guard, last-admin guard still applies)."""

    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()
        self.access_service = AccessService()

    def _read_models(self, db: Session, users: list[AppUser]) -> list[UserRead]:
        if not users:
            return []
        tenants = {
            tenant.id: tenant
            for tenant in db.scalars(select(Tenant).where(Tenant.id.in_({user.tenant_id for user in users})))
        }
        roles = role_service.roles_by_user(db, [user.id for user in users])
        result = []
        for user in users:
            external_identity = user.external_identity_json or {}
            tenant = tenants[user.tenant_id]
            result.append(
                UserRead(
                    id=user.public_id,
                    tenant_id=tenant.public_id,
                    tenant_name=tenant.name,
                    roles=[role_service.role_ref(role) for role in roles.get(user.id, [])],
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
        require_permission(actor, P.ACCESS_MANAGE)
        return self._read_models(db, self.repository.list_by_tenant(db, actor.current_tenant_id))

    def get_user(self, db: Session, user_id: int, actor: CurrentUser):
        require_permission(actor, P.ACCESS_MANAGE)
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
        require_permission(actor, P.ACCESS_MANAGE)
        if payload.tenant_id is not None and payload.tenant_id != actor.current_tenant_public_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Users can only be created in the own tenant")
        user = self._new_app_user(db, payload, tenant_id=actor.current_tenant_id)
        self.repository.create(db, user)
        self._assign_initial_roles(db, actor, user, payload)
        db.commit()
        return self._read_model(db, user)

    def _assign_initial_roles(self, db: Session, actor: CurrentUser | None, user: AppUser, payload: UserCreate) -> None:
        """Neue Konten: angegebene Rollen (Schutzregeln von role_service) oder die Standardrolle
        reader ("Mitglied")."""
        db.flush()
        roles = self._requested_roles(db, user.tenant_id, payload.role_ids, payload.system_role)
        if roles is None:
            role_service.assign_default_role(db, user)
            return
        role_service.set_user_roles(db, actor, user, roles)

    def _requested_roles(self, db: Session, tenant_id: int, role_ids: list | None, system_role: str | None):
        """role_ids (Rollen des Mandanten per public_id) oder system_role (genau eine Standardrolle,
        für das Plattform-Admin-Panel). None = keine Angabe."""
        if role_ids is not None:
            return role_service.resolve_roles(db, tenant_id, role_ids)
        if system_role is not None:
            return [role_service.system_role(db, tenant_id, system_role)]
        return None

    def admin_create_user(self, db: Session, payload: UserCreate) -> UserRead:
        """Unscoped user creation for the platform-admin panel - the tenant is picked explicitly."""
        if payload.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="tenant_id is required")
        tenant_id = public_id_service.resolve_internal_id(db, Tenant, payload.tenant_id)
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
        user = self._new_app_user(db, payload, tenant_id=tenant_id)
        self.repository.create(db, user)
        self._assign_initial_roles(db, None, user, payload)
        db.commit()
        return self._read_model(db, user)

    def update_user(self, db: Session, user_id: int, payload: UserUpdate, actor: CurrentUser):
        require_permission(actor, P.ACCESS_MANAGE)
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
        values = payload.model_dump(exclude_unset=True, exclude={"password", "role_ids", "system_role"})
        if "email" in values:
            values["email"] = values["email"].strip().lower() if values["email"] and values["email"].strip() else None
        if actor is not None and user.id != actor.user_id:
            # Keine Konto-Übernahme Höherberechtigter (Passwort, Login, E-Mail, Aktiv).
            role_service.ensure_can_manage_account(db, actor, user.id)
        roles = self._requested_roles(db, user.tenant_id, payload.role_ids, payload.system_role)
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
        # Deaktivieren, Login entziehen und Rollen ändern dürfen den letzten Administrator nicht
        # treffen und nicht die eigene Benutzerverwaltung entziehen (role_service.admin_guard).
        with role_service.admin_guard(db, user.tenant_id, actor, affects_actor=actor is not None and user.id == actor.user_id):
            if values:
                self.repository.update(db, user, values)
            if roles is not None:
                role_service.set_user_roles(db, actor, user, roles)

        if payload.is_active is not None:
            self.access_service.sync_user_access_from_participants(db, user_id=user.id, tenant_id=user.tenant_id)
        db.commit()
        return self._read_model(db, user)

    def ensure_login_email_available(self, db: Session, email: str, *, excluding_user_id: int | None = None) -> None:
        statement = select(AppUser.id).where(AppUser.login_enabled.is_(True), AppUser.email == email.strip().lower())
        if excluding_user_id is not None:
            statement = statement.where(AppUser.id != excluding_user_id)
        # Login-E-Mails sind plattformweit eindeutig: die Prüfung muss auch Konten anderer
        # Mandanten sehen (Row-Level-Security, app/core/tenant_scope.py) und gibt nur Ja/Nein zurück.
        with tenant_scope_suspended(db):  # rls-ok: plattformweite Eindeutigkeit, liefert nur Ja/Nein
            taken = db.scalar(statement) is not None
        if taken:
            raise HTTPException(status_code=409, detail="Diese E-Mail-Adresse wird bereits für einen Login verwendet")

    def delete_user(self, db: Session, user_id: int, actor: CurrentUser) -> bool:
        require_permission(actor, P.ACCESS_MANAGE)
        user = self.repository.get(db, user_id)
        if user is None:
            return False
        if actor.user_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own admin account")
        if user.tenant_id != actor.current_tenant_id:
            # 404, not 403 - see _tenant_user (avoids cross-tenant user-id enumeration).
            return False
        role_service.ensure_can_manage_account(db, actor, user.id)
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
