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
from app.core.mfa_policy import account_requires_mfa, mfa_grace_until
from app.core.permissions import CATALOG, P, assigned_only_permissions, effective_permissions
from app.core.features_generated import FEATURES
from app.core.tenant_mfa import tenant_requires_mfa
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
    # Währung des Vereins (tenant.finance_currency) für die Anzeige von Bussen und Konten
    current_tenant_currency: str = "CHF"
    protocol_accordion_enabled: bool = True
    # Rad-Effekt beim Scrollen im Protokoll-Editor; an = Akkordeon aus (Design «Protokoll-Editor v2»)
    # Rad-Effekt standardmässig aus (ruckelte bei grossen Protokollen), nur ausdrücklich eingeschaltet an
    protocol_wheel_enabled: bool = False
    mfa_verified: bool = False
    # MFA-Pflicht des Mandanten für alle Logins (tenant.require_mfa, Migration 0188).
    tenant_require_mfa: bool = False
    # Laufende Frist zum Einrichten von MFA (bestehende Konten, Migration 0192) - für den Hinweis
    mfa_grace_until: datetime | None = None
    # Feature-Gating pro Mandant (orthogonal zu den Rollen): welche Features fuer
    # current_tenant_id gebucht sind. Leer per Default (deny-by-default) - build_current_user
    # laedt den echten Stand aus tenant_feature.
    current_tenant_features: frozenset[str] = frozenset()
    # Features nach einem Downgrade im Zustand «nur lesen» (tenant_feature.access = 'read_only'):
    # bestehende Daten bleiben lesbar, Änderungen sind gesperrt (permissions/features.json).
    current_tenant_read_only_features: frozenset[str] = frozenset()
    # Effektive Berechtigungen (RBAC): Vereinigungsmenge aller Rollen des Kontos inkl. der festen
    # Implikationen, bei jedem Request frisch aus user_role/tenant_role geladen - Rollenänderungen
    # wirken damit sofort, auch in laufenden Sessions. Leer = default deny.
    permissions: frozenset[str] = frozenset()
    # Rechte mit Reichweite, die das Konto über keine Rolle für alle hat (Migration 0195): für sie
    # gelten nur zugewiesene Objekte (resource_assignment). Leer = überall «alle» (bisher).
    assigned_only: frozenset[str] = frozenset()
    # Interne IDs der zugewiesenen tenant_role-Zeilen (für die Schutzregeln der Rollenverwaltung).
    role_ids: tuple[int, ...] = ()
    # Anzeige in der Session (Name bzw. system_key der Standardrolle).
    roles: tuple["RoleSummary", ...] = ()
    # Session-Register (SEC-AUTH-011): ID der Session (None bei Tokens von vor dem Update) und
    # Zeitpunkt der letzten starken Anmeldung (Step-up, SEC-AUTH-010).
    session_id: uuid.UUID | None = None
    auth_time: datetime | None = None
    # Ausstellung/Ablauf des Tokens: nötig, um eine Session von vor dem Update (ohne sid) ins
    # Register zu übernehmen, ohne sie zu verlängern oder frischer zu machen (Security-Review M1/N5).
    token_issued_at: datetime | None = None
    token_expires_at: datetime | None = None

    def can(self, permission: P) -> bool:
        """Funktionsberechtigung: Permission vorhanden und - falls an ein Modul gebunden - das
        Modul für den Mandanten gebucht. Ressourcenregeln (welcher Datensatz) prüft
        services/access_service.py zusätzlich."""
        definition = CATALOG[permission]
        if definition.feature is not None and not self.has_feature(definition.feature, write=permission not in FEATURES[definition.feature].read_permissions):
            return False
        return permission in self.permissions

    def sees_all(self, permission: P) -> bool:
        """Reichweite «alle» für ein Recht mit Reichweite (sonst nur zugewiesene Objekte). Prüft
        nicht, ob das Recht vorhanden ist - dafür require_permission/can."""
        return permission.value not in self.assigned_only

    def has_feature(self, code: str, *, write: bool = True) -> bool:
        """Feature gebucht; ``write=False`` lässt auch den Nur-Lesen-Zustand nach einem Downgrade zu."""
        return code in self.current_tenant_features or (not write and code in self.current_tenant_read_only_features)


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


def _key_id(secret: str) -> str:
    """Schlüssel-ID im Token (SEC-AUTH-011): erlaubt die Rotation von AUTH_SECRET ohne alle
    abzumelden (AUTH_SECRET_PREVIOUS prüft weiter)."""
    return hashlib.sha256(b"hocx session kid v1:" + secret.encode("utf-8")).hexdigest()[:8]


def _session_secrets() -> list[str]:
    return [value for value in (settings.auth_secret, settings.auth_secret_previous) if value]


def _sign_payload(payload: bytes) -> str:
    signature = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def session_cookie_name() -> str:
    """Cookie-Name mit ``__Host-``-Präfix (SEC-AUTH-018), sobald Cookies ``Secure`` sind: ein
    Browser nimmt ihn nur host-only und mit Path=/ an - eine Geschwister-Subdomain kann ihn nicht
    unterschieben (Cookie-Tossing). Ohne HTTPS (lokal, E2E) bleibt der bisherige Name."""
    name = settings.auth_session_cookie
    if settings.auth_secure_cookies and not name.startswith("__Host-"):
        return f"__Host-{name}"
    return name


# Start dieses Prozesses ≈ Deploy-Zeitpunkt: bis dahin + auth_session_ttl_hours kann es noch
# Cookies unter dem bisherigen Namen geben (Security-Review N2).
_PROCESS_STARTED = datetime.now(UTC)


def legacy_cookie_accepted(now: datetime | None = None) -> bool:
    """Bisheriger Cookie-Name (ohne ``__Host-``) wird nur noch im Übergang gelesen:
    bis ``AUTH_LEGACY_COOKIE_UNTIL`` (ISO-Datum) bzw. ohne Angabe bis Prozessstart + Session-TTL."""
    now = now or datetime.now(UTC)
    if settings.auth_legacy_cookie_until:
        try:
            until = datetime.fromisoformat(settings.auth_legacy_cookie_until)
        except ValueError:
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return now < until
    return now < _PROCESS_STARTED + timedelta(hours=settings.auth_session_ttl_hours)


def session_cookie_names() -> tuple[str, ...]:
    """Gelesen wird zuerst der neue, im Übergang auch der bisherige Name."""
    names = [session_cookie_name()]
    if names[0] != settings.auth_session_cookie and legacy_cookie_accepted():
        names.append(settings.auth_session_cookie)
    return tuple(names)


def session_token_from_cookies(cookies) -> str | None:
    for name in session_cookie_names():
        value = cookies.get(name)
        if value:
            return value
    return None


def create_session_token(
    user_id: int, *, mfa_verified: bool = False, sid: str | None = None, expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = expires_at or now + timedelta(hours=settings.auth_session_ttl_hours)
    claims = {
        "user_id": user_id,
        "mfa": bool(mfa_verified),
        "iat": int(now.timestamp()),
        # Millisekunden: Widerruf und Neuausstellung in derselben Sekunde (Audit-Test H1)
        "iat_ms": int(now.timestamp() * 1000),
        # Mikrosekunden wie session_revoke_at (token_predates_revoke)
        "iat_us": epoch_microseconds(now),
        "exp": int(exp.timestamp()),
        "kid": _key_id(settings.auth_secret),
    }
    if sid:
        claims["sid"] = str(sid)
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    return _sign_payload(payload)


def issue_session_cookie(
    response: Response, user_id: int, *, mfa_verified: bool = False, sid: str | None = None, expires_at: datetime | None = None,
) -> None:
    """Mints a fresh session token and sets it as a host-only cookie on the response - shared by
    login and the cross-domain login bridge so both stay consistent. Mit ``sid`` gehört das Token zu
    einer Zeile im Session-Register (app/auth_security/sessions.py) und läuft mit ihr ab."""
    token = create_session_token(user_id, mfa_verified=mfa_verified, sid=sid, expires_at=expires_at)
    max_age = int((expires_at - datetime.now(UTC)).total_seconds()) if expires_at else settings.auth_session_ttl_hours * 3600
    name = session_cookie_name()
    response.set_cookie(
        key=name,
        value=token,
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=max(60, max_age),
        path="/",
    )
    if name != settings.auth_session_cookie:
        # Bisheriges Cookie ohne Präfix ablösen (Übergang SEC-AUTH-018)
        response.delete_cookie(settings.auth_session_cookie, path="/")


def clear_session_cookies(response: Response) -> None:
    for name in dict.fromkeys((session_cookie_name(), settings.auth_session_cookie)):
        response.delete_cookie(name, path="/", secure=settings.auth_secure_cookies, httponly=True, samesite="lax")


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
        provided = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not any(
        hmac.compare_digest(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest(), provided)
        for secret in _session_secrets()
    ):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        return None
    return data


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def epoch_microseconds(moment: datetime) -> int:
    """Ganzzahlige Mikrosekunden seit 1970 (ohne Gleitkomma-Rundung) - Auflösung von
    ``session_revoke_at`` (timestamptz) und vom Claim ``iat_us``."""
    return (moment - _EPOCH) // timedelta(microseconds=1)


def token_predates_revoke(revoke_at: datetime | None, session_data: dict) -> bool:
    """Gemeinsame Regel für Konten und Plattform-Admins (session_revoke_at): wurde das Token vor
    (oder gleichzeitig mit) dem Widerruf ausgestellt? Neue Tokens tragen ``iat_us`` in derselben
    Auflösung wie der Widerruf - damit sind beide Fälle eindeutig: ein vor dem Widerruf in derselben
    Millisekunde ausgestelltes Token ist ungültig, eine direkt danach neu ausgestellte Session gilt.
    Ältere Tokens (nur ``iat_ms``/``iat``) werden im Zweifel als widerrufen behandelt (>=)."""
    if revoke_at is None:
        return False
    if "iat_us" in session_data:
        return epoch_microseconds(revoke_at) >= int(session_data["iat_us"])
    if "iat_ms" in session_data:
        return epoch_microseconds(revoke_at) // 1000 >= int(session_data["iat_ms"])
    return epoch_microseconds(revoke_at) // 1_000_000 >= int(session_data.get("iat", 0))


def _token_predates_revoke(user: AppUser, session_data: dict) -> bool:
    return token_predates_revoke(user.session_revoke_at, session_data)


@dataclass
class ValidatedSession:
    user: AppUser
    data: dict
    # Zeile im Session-Register; None bei Tokens von vor dem Update (ohne sid)
    record: object | None

    @property
    def mfa_verified(self) -> bool:
        return bool(self.data.get("mfa")) or bool(self.record is not None and getattr(self.record, "mfa", False))

    @property
    def auth_time(self) -> datetime:
        if self.record is not None:
            return self.record.auth_time
        return datetime.fromtimestamp(int(self.data.get("iat", 0)), UTC)


def validate_session_token(db: Session, token: str | None) -> ValidatedSession | None:
    """Gemeinsame Kontoprüfung für REST und WebSocket (SEC-AUTH-014): Signatur und Ablauf, Konto
    aktiv, Login erlaubt, nicht ausgetreten, kein Widerruf seit Ausstellung, Session im Register
    aktiv (Inaktivität, absolute Dauer, Einzel-Widerruf). Die MFA-Regeln prüfen die Aufrufer."""
    session_data = parse_session_token(token)
    if session_data is None:
        return None
    try:
        user = db.get(AppUser, int(session_data["user_id"]))
    except (KeyError, TypeError, ValueError):
        return None
    if user is None or not user.is_active or not user.login_enabled or user.has_left:
        return None
    if _token_predates_revoke(user, session_data):
        return None
    record = None
    if session_data.get("sid"):
        from app.auth_security import sessions

        record = sessions.validate(db, session_data["sid"], user.id)
        if record is None:
            return None
    return ValidatedSession(user=user, data=session_data, record=record)


def _load_role_rows(db: Session, user_id: int):
    return db.execute(
        select(
            TenantRole.id, TenantRole.public_id, TenantRole.name, TenantRole.system_key,
            TenantRolePermission.permission_key, TenantRolePermission.scope,
        )
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


def _assigned_only(rows) -> frozenset[str]:
    roles: dict[int, tuple[str | None, list[tuple[str, str | None]]]] = {}
    for row in rows:
        entry = roles.setdefault(row.id, (row.system_key, []))
        if row.permission_key is not None:
            entry[1].append((row.permission_key, row.scope))
    return frozenset(str(key) for key in assigned_only_permissions(roles.values()))


def load_role_scopes(db: Session, user_id: int) -> frozenset[str]:
    """Rechte mit Reichweite, die das Konto nur für zugewiesene Objekte hat (Schutzregel 1 der
    Rollenverwaltung: keine Ausweitung von «zugewiesene» auf «alle»)."""
    return _assigned_only(_load_role_rows(db, user_id))


def load_role_permissions(db: Session, user_id: int) -> tuple[frozenset[str], tuple[int, ...]]:
    """Effektive Permissions und Rollen-IDs eines Kontos (eine indexgestützte Abfrage)."""
    rows = _load_role_rows(db, user_id)
    return _effective(rows), tuple(sorted({row.id for row in rows}))


def build_current_user(db: Session, user: AppUser, *, mfa_verified: bool = False) -> CurrentUser:
    tenant = db.execute(select(Tenant).where(Tenant.id == user.tenant_id)).scalar_one()
    rows = _load_role_rows(db, user.id)
    summaries = {row.id: RoleSummary(public_id=row.public_id, name=row.name, system_key=row.system_key) for row in rows}
    feature_rows = db.execute(select(TenantFeature.feature_code, TenantFeature.access).where(TenantFeature.tenant_id == tenant.id)).all()
    tenant_features = frozenset(row.feature_code for row in feature_rows if row.access == "full")
    read_only_features = frozenset(row.feature_code for row in feature_rows if row.access == "read_only")
    return CurrentUser(
        user_id=user.id,
        user_public_id=user.public_id,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        email=user.email,
        preferred_language=user.preferred_language,
        protocol_accordion_enabled=(user.external_identity_json or {}).get("protocol_accordion_enabled", True) is not False,
        protocol_wheel_enabled=(user.external_identity_json or {}).get("protocol_wheel_enabled", False) is True,
        current_tenant_id=tenant.id,
        current_tenant_public_id=tenant.public_id,
        current_tenant_name=tenant.name,
        current_tenant_profile_image_path=tenant.profile_image_path,
        current_tenant_currency=tenant.finance_currency or "CHF",
        mfa_verified=mfa_verified,
        tenant_require_mfa=tenant_requires_mfa(db, tenant.id),
        current_tenant_features=tenant_features,
        current_tenant_read_only_features=read_only_features,
        permissions=_effective(rows),
        assigned_only=_assigned_only(rows),
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


def _requires_mfa(db: Session, user: CurrentUser) -> bool:
    return account_requires_mfa(db, user.user_id, permissions=user.permissions, tenant_id=user.current_tenant_id)


# Fehlercode, wenn eine sonst gültige Session nur deshalb nicht auflöst, weil MFA Pflicht ist und
# das Konto noch keinen Faktor hat. Das Frontend leitet dann zum Login, der direkt in die
# Einrichtung führt (mfa_service.prepare_login, status «setup_required»).
MFA_SETUP_REQUIRED = "mfa_setup_required"


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_session_cookie),
) -> CurrentUser | None:
    token = session_token_from_cookies(request.cookies) if request is not None else None
    if token is None and session_cookie and (session_cookie_name() == settings.auth_session_cookie or legacy_cookie_accepted()):
        token = session_cookie
    validated = validate_session_token(db, token)
    if validated is None:
        return None
    user = validated.user
    current_user = build_current_user(db, user, mfa_verified=validated.mfa_verified)
    current_user.session_id = validated.record.id if validated.record is not None else None
    current_user.auth_time = validated.auth_time
    current_user.token_issued_at = datetime.fromtimestamp(int(validated.data.get("iat", 0)), UTC)
    current_user.token_expires_at = datetime.fromtimestamp(int(validated.data.get("exp", 0)), UTC)
    has_mfa_factor = _has_active_mfa_factor(db, user.id)
    if has_mfa_factor and not current_user.mfa_verified:
        return None
    if _requires_mfa(db, current_user) and (not has_mfa_factor or not current_user.mfa_verified):
        if not has_mfa_factor:
            # Bestehendes Konto, MFA neu Pflicht (nicht wegen Administrationsrechten): 3 Tage Frist
            grace = mfa_grace_until(db, current_user.user_id, permissions=current_user.permissions, tenant_id=current_user.current_tenant_id)
            if grace is not None:
                current_user.mfa_grace_until = grace
                bind_tenant_scope(db, current_user.current_tenant_id)
                return current_user
        if not has_mfa_factor and request is not None:
            # Nur als Grund für get_current_user (klare Fehlermeldung); die Session bleibt
            # ungültig, auch für Endpunkte mit optionalem Login.
            request.state.auth_block_reason = MFA_SETUP_REQUIRED
        return None
    # Ab hier sieht die Session per Row-Level-Security nur noch Daten dieses Mandanten.
    bind_tenant_scope(db, current_user.current_tenant_id)
    return current_user


def get_current_user(request: Request, user: CurrentUser | None = Depends(get_optional_current_user)) -> CurrentUser:
    if user is None:
        if getattr(request.state, "auth_block_reason", None) == MFA_SETUP_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": MFA_SETUP_REQUIRED, "message": "MFA muss eingerichtet werden. Bitte neu anmelden."},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_feature(user: CurrentUser, code: str, *, write: bool = True) -> CurrentUser:
    """Feature-Gating pro Mandant - orthogonal zur Berechtigung. Ein 403 hier bedeutet "fuer
    diesen Mandanten nicht gebucht", nicht "darf das nicht". ``write=False`` (nur lesen) lässt
    den Nur-Lesen-Zustand nach einem Downgrade zu (permissions/features.json)."""
    if user.has_feature(code, write=write):
        return user
    if code in user.current_tenant_read_only_features:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{code}' nur noch lesend (nicht mehr im Abo)")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{code}' nicht gebucht")


def require_permission(user: CurrentUser, permission: P) -> CurrentUser:
    """Zentrale Funktionsberechtigung (SECURITY-RULES §1.3: vor dem Laden/Ändern aufrufen).
    Ist die Permission an ein Modul gebunden, kommt bei fehlendem Modul dieselbe Meldung wie bei
    require_feature."""
    feature = CATALOG[permission].feature
    if feature is not None:
        require_feature(user, feature, write=permission not in FEATURES[feature].read_permissions)
    if permission not in user.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required")
    return user


def require_any_permission(user: CurrentUser, *permissions: P) -> CurrentUser:
    """Mindestens eine der Permissions (z. B. Teilnehmerliste: participants.manage oder
    meetings.edit). Bewusst ohne Feature-Sonderfall - nur für Permissions ohne Modulbindung."""
    if any(user.can(permission) for permission in permissions):
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required")
