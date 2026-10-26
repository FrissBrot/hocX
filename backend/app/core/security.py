from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.locale_config_generated import LOCALE_COOKIE_NAME, normalize_locale
from app.core.permissions import CATALOG, P, effective_permissions, requires_mfa
from app.core.tenant_scope import bind_tenant_scope
from app.models import AppUser, Tenant, TenantFeature, TenantRole, TenantRolePermission, UserMfaFactor, UserRole


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600000


@dataclass
class CurrentUser:
    user_id: int
    user_public_id: uuid.UUID
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str
    # A user belongs to exactly one tenant (app_user.tenant_id); the "current_" prefix is
    # historical from when a session could switch between tenants.
    current_tenant_id: int
    current_tenant_public_id: uuid.UUID
    current_tenant_name: str
    current_tenant_profile_image_path: str | None
    protocol_accordion_enabled: bool = True
    mfa_verified: bool = False
    # Feature-Gating pro Mandant (orthogonal zu den Rollen): welche Features fuer
    # current_tenant_id gebucht sind. Leer per Default (deny-by-default) - build_current_user
    # laedt den echten Stand aus tenant_feature.
    current_tenant_features: frozenset[str] = frozenset()
    # Effektive Berechtigungen (RBAC): Vereinigungsmenge aller Rollen des Kontos inkl. der festen
    # Implikationen, bei jedem Request frisch aus user_role/tenant_role geladen - Rollenänderungen
    # wirken damit sofort, auch in laufenden Sessions. Leer = default deny.
    permissions: frozenset[str] = frozenset()
    # Interne IDs der zugewiesenen tenant_role-Zeilen (für die Schutzregeln der Rollenverwaltung).
    role_ids: tuple[int, ...] = ()
    # Anzeige in der Session (Name bzw. system_key der Standardrolle).
    roles: tuple["RoleSummary", ...] = ()

    def can(self, permission: P) -> bool:
        """Funktionsberechtigung: Permission vorhanden und - falls an ein Modul gebunden - das
        Modul für den Mandanten gebucht. Ressourcenregeln (welcher Datensatz) prüft
        services/access_service.py zusätzlich."""
        definition = CATALOG[permission]
        if definition.feature is not None and definition.feature not in self.current_tenant_features:
            return False
        return permission in self.permissions


@dataclass(frozen=True)
class RoleSummary:
    public_id: uuid.UUID
    name: str | None
    system_key: str | None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


# A fixed, valid-shaped hash with no corresponding real password - used to run
# verify_password's full PBKDF2 work even when no account exists, so a login attempt
# against an unknown email takes the same time as one against a real email with a wrong
# password (audit finding, 2026-08-25: short-circuiting straight past verify_password for
# a missing account was a measurable, account-enumerating timing side channel).
DUMMY_PASSWORD_HASH = hash_password("hocx-dummy-password-for-timing-only")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("utf-8"))
        expected = base64.b64decode(digest_raw.encode("utf-8"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _sign_payload(payload: bytes) -> str:
    signature = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def create_session_token(user_id: int, *, mfa_verified: bool = False) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "user_id": user_id,
            "mfa": bool(mfa_verified),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.auth_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


def issue_session_cookie(response: Response, user_id: int, *, mfa_verified: bool = False) -> None:
    """Mints a fresh session token and sets it as a host-only cookie on the response - shared by
    login and the cross-domain login bridge so both stay consistent. (OIDC is admin-panel-only
    now - see platform_oidc_service.py / issue_admin_session_cookie.) Sessions issued before
    the single-tenant switch carry an extra "tenant_id" claim, which parse_session_token simply
    ignores."""
    token = create_session_token(user_id, mfa_verified=mfa_verified)
    response.set_cookie(
        key=settings.auth_session_cookie,
        value=token,
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )


def issue_locale_cookie(response: Response, locale: str | None) -> None:
    """Spiegelt die gespeicherte Sprachpraeferenz (preferred_language) in einen eigenen Cookie,
    den das Frontend serverseitig ohne weiteren Netzwerk-Request lesen kann (next-intl, siehe
    frontend/i18n/request.ts) - dieselbe Rolle wie issue_session_cookie fuer die Session, nur
    nicht httpOnly-kritisch (next-intl liest sie serverseitig ueber cookies(), unabhaengig vom
    httpOnly-Flag). Aufgerufen bei Login, bei jedem Session-Abruf (haelt den Cookie frisch, falls
    preferred_language zwischenzeitlich auf einem anderen Geraet geaendert wurde) und beim
    Self-Update des Profils. normalize_locale faengt eine unbekannte/leere Locale ab, statt sie
    ungeprueft in den Cookie zu schreiben."""
    response.set_cookie(
        key=LOCALE_COOKIE_NAME,
        value=normalize_locale(locale),
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )


def parse_session_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    token = token.strip('"')
    payload_b64, signature_b64 = token.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        expected = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if int(data.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        return None
    return data


def _load_role_rows(db: Session, user_id: int):
    return db.execute(
        select(TenantRole.id, TenantRole.public_id, TenantRole.name, TenantRole.system_key, TenantRolePermission.permission_key)
        .select_from(UserRole)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .outerjoin(TenantRolePermission, TenantRolePermission.role_id == TenantRole.id)
        .where(UserRole.user_id == user_id)
    ).all()


def _effective(rows) -> frozenset[str]:
    return frozenset(str(key) for key in effective_permissions(
        (row.permission_key for row in rows if row.permission_key is not None),
        (row.system_key for row in rows),
    ))


def load_role_permissions(db: Session, user_id: int) -> tuple[frozenset[str], tuple[int, ...]]:
    """Effektive Permissions und Rollen-IDs eines Kontos (eine indexgestützte Abfrage)."""
    rows = _load_role_rows(db, user_id)
    return _effective(rows), tuple(sorted({row.id for row in rows}))


def build_current_user(db: Session, user: AppUser, *, mfa_verified: bool = False) -> CurrentUser:
    tenant = db.execute(select(Tenant).where(Tenant.id == user.tenant_id)).scalar_one()
    rows = _load_role_rows(db, user.id)
    summaries = {row.id: RoleSummary(public_id=row.public_id, name=row.name, system_key=row.system_key) for row in rows}
    tenant_features = frozenset(
        db.scalars(select(TenantFeature.feature_code).where(TenantFeature.tenant_id == tenant.id))
    )
    return CurrentUser(
        user_id=user.id,
        user_public_id=user.public_id,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        email=user.email,
        preferred_language=user.preferred_language,
        protocol_accordion_enabled=(user.external_identity_json or {}).get("protocol_accordion_enabled", True) is not False,
        current_tenant_id=tenant.id,
        current_tenant_public_id=tenant.public_id,
        current_tenant_name=tenant.name,
        current_tenant_profile_image_path=tenant.profile_image_path,
        mfa_verified=mfa_verified,
        current_tenant_features=tenant_features,
        permissions=_effective(rows),
        role_ids=tuple(sorted(summaries)),
        roles=tuple(summaries[role_id] for role_id in sorted(summaries)),
    )


def _has_active_mfa_factor(db: Session, user_id: int) -> bool:
    return (
        db.query(UserMfaFactor.id)
        .filter(UserMfaFactor.user_id == user_id)
        .limit(1)
        .one_or_none()
        is not None
    )


def _requires_mfa(user: CurrentUser) -> bool:
    return requires_mfa(user.permissions)


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_session_cookie),
) -> CurrentUser | None:
    token = session_cookie or request.cookies.get(settings.auth_session_cookie)
    session_data = parse_session_token(token)
    if session_data is None:
        return None
    user = db.get(AppUser, int(session_data["user_id"]))
    if user is None or not user.is_active or not user.login_enabled:
        return None
    if user.session_revoke_at is not None:
        token_iat = int(session_data.get("iat", 0))
        if int(user.session_revoke_at.timestamp()) > token_iat:
            return None
    current_user = build_current_user(db, user, mfa_verified=bool(session_data.get("mfa")))
    has_mfa_factor = _has_active_mfa_factor(db, user.id)
    if has_mfa_factor and not current_user.mfa_verified:
        return None
    if _requires_mfa(current_user) and (not has_mfa_factor or not current_user.mfa_verified):
        return None
    # Ab hier sieht die Session per Row-Level-Security nur noch Daten dieses Mandanten.
    bind_tenant_scope(db, current_user.current_tenant_id)
    return current_user


def get_current_user(user: CurrentUser | None = Depends(get_optional_current_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_feature(user: CurrentUser, code: str) -> CurrentUser:
    """Feature-Gating pro Mandant - orthogonal zur Berechtigung. Ein 403 hier bedeutet "fuer
    diesen Mandanten nicht gebucht", nicht "darf das nicht"."""
    if code not in user.current_tenant_features:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{code}' nicht gebucht")
    return user


def require_permission(user: CurrentUser, permission: P) -> CurrentUser:
    """Zentrale Funktionsberechtigung (SECURITY-RULES §1.3: vor dem Laden/Ändern aufrufen).
    Ist die Permission an ein Modul gebunden, kommt bei fehlendem Modul dieselbe Meldung wie bei
    require_feature."""
    feature = CATALOG[permission].feature
    if feature is not None:
        require_feature(user, feature)
    if permission not in user.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required")
    return user


def require_any_permission(user: CurrentUser, *permissions: P) -> CurrentUser:
    """Mindestens eine der Permissions (z. B. Teilnehmerliste: participants.manage oder
    meetings.edit). Bewusst ohne Feature-Sonderfall - nur für Permissions ohne Modulbindung."""
    if any(user.can(permission) for permission in permissions):
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required")
