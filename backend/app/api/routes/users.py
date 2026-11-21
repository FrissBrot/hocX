import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.db import get_db
from app.core.permissions import P
from app.auth_security import events
from app.auth_security import sessions as session_register
from app.auth_security.step_up import ADMIN, MFA, require_recent_auth
from app.core.security import CurrentUser, get_current_user, issue_locale_cookie, issue_session_cookie, require_permission
from app.models import AuthSession
from app.models.entities import AppUser, Tenant, UserMfaFactor
from app.schemas.step_up import KnownDeviceRead, SessionDeviceRead, SessionListRead
from app.schemas.mfa import (
    PasskeyRegistrationComplete,
    PasskeyRegistrationStartRead,
    PreferredMfaMethodUpdate,
    TenantMfaPolicyRead,
    TenantMfaPolicyUpdate,
    TenantProtocolPolicy,
    TotpEnrollmentComplete,
    TotpEnrollmentStartRead,
    UserMfaRead,
)
from app.schemas.user import UserCreate, UserPasswordChange, UserRead, UserSelfUpdate, UserUpdate
from app.core.rate_limit import enforce_rate_limit
from app.schemas.data_export import ProtectedExportRequest
from app.services import public_id_service
from app.services.data_export import personal as personal_data
from app.services.audit_service import AuditService
from app.services.mfa_service import MfaService
from app.services.user_service import UserService

from app.notifications import preferences as notification_preferences
from app.schemas.notifications import NotificationPreferencesRead, NotificationPreferencesWrite

router = APIRouter()
service = UserService()
mfa_service = MfaService()
audit = AuditService()


def _browser_origin(request: Request) -> str:
    """Origin der Seite, wie der Browser ihn meldet - nur für die Entscheidung, ob auf diesem
    Host Passkeys angeboten werden (siehe _request_hostname), nie als Prüfwert."""
    origin = request.headers.get("origin")
    if origin:
        return origin
    host = request.headers.get("host") or request.url.netloc
    if host.startswith("localhost") or host.startswith("127.0.0.1"):
        return f"http://{host}"
    return f"https://{host}"


def _expected_origin(request: Request) -> str:
    """Erwarteter WebAuthn-Origin. Mit konfigurierter Hauptdomain fest auf diese gesetzt statt aus
    dem Origin-Header des Requests übernommen (Security-Audit SEC-021, gleiche Regel wie
    routes/auth.py) - ein Vergleich mit dem Wert aus demselben Request prüft nichts. Nur lokal
    (ohne Domain) gilt weiter der Origin des Requests."""
    if settings.traefik_domain:
        return f"https://{settings.traefik_domain}"
    return _browser_origin(request)


def _request_hostname(request: Request) -> str | None:
    """See admin.py's identical helper: request.url.hostname is wrong whenever this request
    arrived through the frontend's own /api/* rewrite proxy, which overwrites Host with its
    own upstream target instead of preserving the browser's original one - reuses
    _browser_origin's own header-derived value (the Origin header, unaffected by that
    proxy hop) instead (audit fix, 2026-09-17)."""
    return urlparse(_browser_origin(request)).hostname


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_users(db, user)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if payload.password or payload.role_ids or payload.system_role or payload.login_enabled:
        # Konto mit Login/Rollen anlegen ist eine Rechtevergabe (SEC-AUTH-010)
        require_recent_auth(user, kind=ADMIN, action="user.create")
    try:
        return service.create_user(db, payload, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be created") from exc


@router.get("/mfa-policy", response_model=TenantMfaPolicyRead)
def get_mfa_policy(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """MFA-Pflicht für alle Logins der eigenen Organisation und wie viele Logins noch keinen
    Faktor haben (Seite «Logins & Rollen»)."""
    require_permission(user, P.ACCESS_MANAGE)
    return mfa_service.get_tenant_policy(db, user)


@router.put("/mfa-policy", response_model=TenantMfaPolicyRead)
def put_mfa_policy(
    payload: TenantMfaPolicyUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.ACCESS_MANAGE)
    if not payload.require_mfa:
        # Abschalten der MFA-Pflicht schwächt alle Konten (SEC-AUTH-010)
        require_recent_auth(user, kind=ADMIN, action="tenant.mfa_policy_off")
    result, changed = mfa_service.set_tenant_policy(db, user, require_mfa=payload.require_mfa)
    if changed:
        audit.log(
            db,
            action="tenant.mfa_policy_updated",
            actor=user,
            entity_type="tenant",
            entity_id=user.current_tenant_id,
            details={"require_mfa": result.require_mfa, "logins_without_mfa": result.logins_without_mfa},
        )
    return result


@router.get("/protocol-policy", response_model=TenantProtocolPolicy)
def get_protocol_policy(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Vier-Augen-Prinzip (Zugriff › Sicherheit): Verfasser schliesst eigenes Protokoll nicht ab."""
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = db.get(Tenant, user.current_tenant_id)
    return TenantProtocolPolicy(four_eyes_protocols=bool(tenant and tenant.four_eyes_protocols))


@router.put("/protocol-policy", response_model=TenantProtocolPolicy)
def put_protocol_policy(payload: TenantProtocolPolicy, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    require_recent_auth(user, kind=ADMIN, action="tenant.protocol_policy")
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    before = tenant.four_eyes_protocols
    tenant.four_eyes_protocols = payload.four_eyes_protocols
    db.commit()
    if before != payload.four_eyes_protocols:
        audit.log(db, action="tenant.protocol_policy_updated", actor=user, entity_type="tenant", entity_id=tenant.id,
                  details={"four_eyes_protocols": payload.four_eyes_protocols})
    return TenantProtocolPolicy(four_eyes_protocols=tenant.four_eyes_protocols)


@router.get("/me", response_model=UserRead)
def get_me(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.get_self(db, user)


@router.patch("/me", response_model=UserRead)
def patch_me(
    payload: UserSelfUpdate,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        updated = service.update_self(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Profile could not be updated") from exc
    # Sofort wirksam ohne auf den naechsten /session-Abruf zu warten (siehe
    # issue_locale_cookie-Docstring) - saveProfile() im Frontend ruft direkt danach ohnehin
    # /api/auth/session ab, das haelt den Cookie zusaetzlich synchron.
    issue_locale_cookie(response, updated.preferred_language)
    return updated


@router.post("/me/personal-data")
def export_my_personal_data(
    payload: ProtectedExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Selbstauskunft: eigene Daten als passwortgeschütztes ZIP (DSG Art. 25/28; PRIV-006)."""
    require_recent_auth(user, kind=ADMIN, action="personal_data.export")
    enforce_rate_limit(f"personal-data-export:{user.user_id}", limit=3, period_seconds=3600)
    person = db.get(AppUser, user.user_id)
    if person is None:
        raise HTTPException(status_code=404, detail="User not found")
    return personal_data.respond(db, person, password=payload.password, actor=user, self_export=True)


@router.get("/me/mfa", response_model=UserMfaRead)
def get_my_mfa(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return mfa_service.get_self_overview(db, user, _request_hostname(request))


@router.patch("/me/mfa/preferred-method", response_model=UserMfaRead)
def patch_my_preferred_mfa_method(
    payload: PreferredMfaMethodUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_recent_auth(user, kind=MFA, action="mfa.preferred")
    return mfa_service.set_self_preferred_method(
        db,
        user,
        factor_type=payload.factor_type,
        request_host=_request_hostname(request),
    )


@router.post("/me/mfa/totp/start", response_model=TotpEnrollmentStartRead)
def start_my_totp_enrollment(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_recent_auth(user, kind=MFA, action="mfa.enroll")
    return mfa_service.start_self_totp_enrollment(db, user)


@router.post("/me/mfa/totp/complete", response_model=UserMfaRead)
def complete_my_totp_enrollment(
    payload: TotpEnrollmentComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    mfa_service.complete_self_totp_enrollment(
        db,
        user,
        flow_token=payload.flow_token,
        code=payload.code,
        label=payload.label,
    )
    audit.log(db, action="user.mfa_factor_added", actor=user, entity_type="user_mfa_factor", details={"factor": "totp"})
    _after_factor_change(db, response, user, method="totp")
    return mfa_service.get_self_overview(db, user, _request_hostname(request))


@router.post("/me/mfa/passkeys/start", response_model=PasskeyRegistrationStartRead)
def start_my_passkey_registration(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_recent_auth(user, kind=MFA, action="mfa.enroll")
    return mfa_service.start_self_passkey_registration(
        db,
        user,
        request_host=_request_hostname(request),
        request_origin=_expected_origin(request),
    )


@router.post("/me/mfa/passkeys/complete", response_model=UserMfaRead)
def complete_my_passkey_registration(
    payload: PasskeyRegistrationComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    mfa_service.complete_self_passkey_registration(
        db,
        user,
        flow_token=payload.flow_token,
        label=payload.label,
        credential=payload.credential,
    )
    audit.log(db, action="user.mfa_factor_added", actor=user, entity_type="user_mfa_factor", details={"factor": "passkey"})
    _after_factor_change(db, response, user, method="passkey")
    return mfa_service.get_self_overview(db, user, _request_hostname(request))


@router.delete("/me/mfa/factors/{factor_id}", response_model=UserMfaRead)
def delete_my_mfa_factor(
    factor_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_recent_auth(user, kind=MFA, action="mfa.remove")
    internal_factor_id = public_id_service.resolve_internal_id(db, UserMfaFactor, factor_id)
    if internal_factor_id is None:
        raise HTTPException(status_code=404, detail="MFA factor not found")
    result = mfa_service.delete_self_factor(db, user, internal_factor_id)
    _after_factor_change(db, response, user, method=None)
    return result.model_copy(update={"can_add_passkey_here": mfa_service.can_add_passkey_here(_request_hostname(request))})


@router.post("/me/password", response_model=UserRead)
def change_my_password(
    payload: UserPasswordChange,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Altes Passwort wie bisher; mit zweitem Faktor zusätzlich frische Bestätigung (Audit 9.2)
    if mfa_service.has_factor(db, user.user_id):
        require_recent_auth(user, kind=MFA, action="password.change")
    try:
        current = service.change_own_password(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Password could not be changed") from exc
    audit.log(db, action="user.password_changed", actor=user, entity_type="user", entity_id=user.user_id)
    events.record(event_type="password.change", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id, session_id=user.session_id)
    # session_revoke_at beendet alle anderen Sessions; die eigene bleibt (gleiche Session-ID, neues
    # Cookie), sonst flöge die Person sofort nach dem Wechsel raus (Bereichs-Audit 05).
    # Andere bekannte Geräte vergessen (Security-Review M4), das aktuelle bleibt
    from app.auth_security import devices

    devices.revoke_others(db, user.user_id, devices.device_id_from_request(request))
    _keep_current_session(db, response, user, reason="password_change")
    return current


def _keep_current_session(db: Session, response: Response, user: CurrentUser, *, reason: str, mfa: bool | None = None) -> AuthSession:
    """Alle anderen Sessions beenden (Audit 9.3), die aktuelle mit neuem Cookie behalten.

    Nie ein Token ohne sid ausstellen (Security-Review M1): eine Session von vor dem Update wird ins
    Register übernommen - mit ihrer alten Ausstellung als auth_time und ihrem alten Ablauf, also
    weder verlängert noch für Step-up frischer."""
    session_register.revoke_all(db, user.user_id, reason=reason, except_id=user.session_id)
    record = db.get(AuthSession, user.session_id) if user.session_id else None
    if record is None:
        record = session_register.adopt_legacy(
            db, user_id=user.user_id, tenant_id=user.current_tenant_id, mfa=user.mfa_verified,
            issued_at=user.token_issued_at, expires_at=user.token_expires_at,
        )
        user.session_id = record.id
    if mfa:
        record.mfa = True
    db.commit()
    issue_session_cookie(response, user.user_id, mfa_verified=record.mfa, sid=str(record.id), expires_at=record.expires_at)
    return record


def _after_factor_change(db: Session, response: Response, user: CurrentUser, *, method: str | None) -> None:
    """Faktor hinzugefügt/entfernt: andere Sessions beenden (wer sie gestohlen hat, behält sonst
    Zugriff), die eigene behält ihre ID. Ein neuer Faktor gilt als frische starke Anmeldung."""
    db_user = db.get(AppUser, user.user_id)
    if db_user is not None:
        from datetime import UTC, datetime

        db_user.session_revoke_at = datetime.now(UTC)
    record = _keep_current_session(db, response, user, reason="mfa_change", mfa=method is not None or user.mfa_verified)
    if method:
        # Faktor gerade erfolgreich bestätigt: starke Anmeldung für diese Session
        session_register.mark_strong_auth(db, record, method)
        db.commit()


# ── Angemeldete Geräte (SEC-AUTH-011) ──────────────────────────────────


@router.get("/me/sessions", response_model=SessionListRead)
def list_my_sessions(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Eigene aktive Sessions (keine Permission nötig, nur eigene Daten)."""
    rows = session_register.list_active(db, user.user_id)
    return SessionListRead(
        sessions=[
            SessionDeviceRead(
                id=row.public_id, current=row.id == user.session_id, user_agent_family=row.user_agent_family, host=row.host,
                created_at=row.created_at, last_seen_at=row.last_seen_at, mfa=row.mfa, via_bridge=row.parent_id is not None,
                country=row.country,
            )
            for row in rows
        ],
        legacy_session=user.session_id is None,
    )


@router.get("/me/devices", response_model=list[KnownDeviceRead])
def list_my_devices(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Eigene bekannte Geräte (von Sperren ausgenommen, Security-Review M4) - nur eigene Daten."""
    from app.auth_security import devices

    current = devices.device_id_from_request(request)
    current_hashes = set(devices._hash_candidates(current)) if current else set()
    return [
        KnownDeviceRead(id=row.public_id, user_agent_family=row.user_agent_family, created_at=row.created_at,
                        last_seen_at=row.last_seen_at, current=row.device_hash in current_hashes, country=row.last_country)
        for row in devices.list_active(db, user.user_id)
    ]


@router.delete("/me/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_device(device_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Bekanntes Gerät vergessen; seine Sessions enden mit. Fremde/unbekannte: 404."""
    from datetime import UTC, datetime

    from app.models import AuthKnownDevice

    row = db.query(AuthKnownDevice).filter(AuthKnownDevice.public_id == device_id, AuthKnownDevice.user_id == user.user_id).one_or_none()
    if row is None or row.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Device not found")
    row.revoked_at = datetime.now(UTC)
    session_ids = list(db.scalars(select(AuthSession.id).where(AuthSession.device_id == row.id, AuthSession.revoked_at.is_(None))))
    session_register.revoke(db, session_ids, reason="device_revoked")
    db.commit()
    events.record(event_type="device.revoke", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id, session_id=user.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_session(session_id: uuid.UUID, response: Response, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Eine eigene Session beenden (fremde oder unbekannte: 404, kein Existenz-Orakel)."""
    row = db.query(AuthSession).filter(AuthSession.public_id == session_id, AuthSession.user_id == user.user_id).one_or_none()
    if row is None or row.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    session_register.revoke(db, [row.id], reason="user_revoked")
    db.commit()
    events.record(event_type="session.revoke", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id, session_id=row.id, details={"scope": "one"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/sessions/revoke-others", response_model=dict[str, int])
def revoke_my_other_sessions(response: Response, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Alle anderen Geräte abmelden; die aktuelle Session bleibt. Sessions von vor dem Update
    (ohne Register) werden über session_revoke_at mit beendet."""
    revoked = session_register.revoke_all(db, user.user_id, reason="user_revoked_others", except_id=user.session_id)
    db_user = db.get(AppUser, user.user_id)
    if db_user is not None:
        from datetime import UTC, datetime

        db_user.session_revoke_at = datetime.now(UTC)
    _keep_current_session(db, response, user, reason="user_revoked_others")
    events.record(event_type="session.revoke", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id, session_id=user.session_id, details={"scope": "others", "revoked": revoked})
    return {"revoked": revoked}


@router.get("/me/notification-preferences", response_model=NotificationPreferencesRead)
def get_my_notification_preferences(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Eigene E-Mail-Benachrichtigungen (eigene Daten, keine Permission nötig)."""
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return notification_preferences.read(db, user.user_id, user.current_tenant_id)


@router.put("/me/notification-preferences", response_model=NotificationPreferencesRead)
def put_my_notification_preferences(
    payload: NotificationPreferencesWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user),
):
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    try:
        return notification_preferences.write(db, user.user_id, user.current_tenant_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Preferences could not be saved") from exc


def _resolve_user_id(db: Session, user_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, AppUser, user_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    return internal_id


@router.get("/{user_id}/mfa", response_model=UserMfaRead)
def get_user_mfa(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_user_id = _resolve_user_id(db, user_id)
    return mfa_service.get_managed_user_overview(db, user, internal_user_id)


@router.delete("/{user_id}/mfa/factors/{factor_id}", response_model=UserMfaRead)
def delete_user_mfa_factor(
    user_id: uuid.UUID,
    factor_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_recent_auth(user, kind=ADMIN, action="user.mfa_reset")
    internal_user_id = _resolve_user_id(db, user_id)
    internal_factor_id = public_id_service.resolve_internal_id(db, UserMfaFactor, factor_id)
    if internal_factor_id is None:
        raise HTTPException(status_code=404, detail="MFA factor not found")
    result = mfa_service.delete_managed_user_factor(db, user, internal_user_id, internal_factor_id)
    audit.log(
        db,
        action="user.mfa_factor_deleted",
        actor=user,
        entity_type="user_mfa_factor",
        entity_id=internal_factor_id,
        details={"target_user_id": internal_user_id},
    )
    return result


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_user_id = _resolve_user_id(db, user_id)
    current = service.get_user(db, internal_user_id, user)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    return current


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_user_id = _resolve_user_id(db, user_id)
    try:
        current = service.update_user(db, internal_user_id, payload, user)
    except ValueError as exc:
        # Kuratierte Validierung (z. B. Austritt vor Eintritt) vor jedem Schreiben - 400 statt 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be updated") from exc
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.is_active is not None:
        action = "user.activated" if payload.is_active else "user.deactivated"
        audit.log(db, action=action, actor=user, entity_type="user", entity_id=internal_user_id)
    return current


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_user_id = _resolve_user_id(db, user_id)
    try:
        deleted = service.delete_user(db, internal_user_id, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
