"""Step-up: frische starke Anmeldung für kritische Aktionen (SEC-AUTH-010, Audit Abschnitt 9.2).

Ein gestohlenes Session-Cookie reicht damit nicht, um Persistenz zu schaffen (eigenen Faktor
registrieren, Faktoren entfernen), Rechte auszuweiten oder Daten zu exportieren. Die Route ruft
``require_recent_auth(user, ...)``; ist die letzte starke Anmeldung der Session älter als erlaubt,
antwortet sie mit 403 ``step_up_required``. Das Frontend (``StepUpDialog``) fragt dann den Faktor
ab (``POST /api/auth/step-up``) und wiederholt die Aktion.

Faktoren: TOTP oder Passkey, wenn das Konto einen hat; sonst das Passwort. Höchstalter:
``auth_step_up_mfa_minutes`` (Faktoren ändern, Standard 10) bzw. ``auth_step_up_admin_minutes``
(Rollen/Rechte, fremde Faktoren, Exporte, Domains, Sicherheitseinstellungen, Standard 15).

Gleiches Muster wie der Plattform-Admin-Restore (``admin_mfa_service.verify_step_up_totp``); der
Admin-Branch kann ``require_recent_auth`` für Admin-Sessions übernehmen, sobald diese im Register
stehen.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.auth_security import events
from app.core.config import settings
from app.core.security import CurrentUser

MFA = "mfa"
ADMIN = "admin"


def max_age_minutes(kind: str) -> int:
    return settings.auth_step_up_mfa_minutes if kind == MFA else settings.auth_step_up_admin_minutes


def is_recent(user: CurrentUser, minutes: int) -> bool:
    if user.auth_time is None:
        return False
    auth_time = user.auth_time if user.auth_time.tzinfo else user.auth_time.replace(tzinfo=UTC)
    return datetime.now(UTC) - auth_time <= timedelta(minutes=minutes)


def require_recent_auth(user: CurrentUser, *, kind: str = ADMIN, action: str) -> None:
    """403 ``step_up_required`` (mit ``max_age_minutes``), wenn die letzte starke Anmeldung zu
    alt ist. ``action`` ist eine feste Kennung für das Ereignis."""
    minutes = max_age_minutes(kind)
    if is_recent(user, minutes):
        return
    events.record(event_type="stepup.required", outcome="challenged", user_id=user.user_id, tenant_id=user.current_tenant_id,
                  session_id=user.session_id, details={"action": action, "minutes": minutes})
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "step_up_required", "message": "Bitte bestätige zuerst deine Identität", "max_age_minutes": minutes},
    )
