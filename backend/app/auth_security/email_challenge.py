"""Zusätzliche Prüfung per E-Mail-Code (Audit Abschnitt 7.2, Klasse «moderat»/«hoch»).

Für Konten **ohne** zweiten Faktor, wenn die Anmeldung von einem unbekannten Gerät mit erhöhtem
Risiko kommt (oder die Konto-/Quellzähler die weiche Schwelle erreicht haben): nach korrektem
Passwort gibt es noch keine Session, sondern ein Ticket (Redis, 10 min, nur im Antwort-Body) und
einen 6-stelligen Code per Mail. Erst Ticket + Code führen weiter (Ersteinrichtung des zweiten
Faktors bei Pflicht bzw. Session). Konten mit Faktor brauchen das nicht: der Faktor ist die Prüfung.

Der Code wird direkt per SMTP verschickt (nicht über den Versand-Loop, der bis zu einer Minute
wartet), als HMAC gespeichert, ist einmalig und nach 5 Fehlversuchen je Ticket verbraucht. Ist der
E-Mail-Versand nicht eingerichtet, entfällt die Prüfung bei «moderat»; bei «hoch» oder harten
Zählerschwellen wird die Anmeldung für unbekannte Geräte abgelehnt (bekannte Geräte gehen immer).
"""
from __future__ import annotations

import hmac
import json
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth_security import events
from app.core.auth_pseudonym import pseudonym
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.redis_client import get_redis_sync
from app.models import AppUser, Tenant

FLOW_PREFIX = "mfa:flow:"
KIND = "login_email_challenge"
MAX_ATTEMPTS = 5
MAX_SENDS = 3


class ChallengeUnavailable(Exception):
    """E-Mail-Versand nicht eingerichtet oder fehlgeschlagen."""


def email_unavailable() -> HTTPException:
    """Antwort, wenn eine Anmeldung einen Mailcode bräuchte, der Versand aber gestört ist
    (delivery_status) oder gerade scheitert. Kommt erst nach korrektem Passwort - wie die Aufforderung
    zur Codeeingabe selbst, also kein zusätzliches Orakel. Kein Retry-After: Abhilfe schafft der
    Administrator, nicht Warten."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "auth_email_unavailable", "message": "Anmeldung aktuell nicht möglich, wende dich an deinen Administrator"},
    )


def _code_hash(ticket: str, code: str) -> str:
    return pseudonym("email-challenge", f"{ticket}:{code}", length=40)


def _send(db: Session, user: AppUser, code: str) -> None:
    from app.notifications import email_transport
    from app.notifications.render import render_login_code

    config = email_transport.load_config(db)
    if config is None or not (user.email or "").strip():
        raise ChallengeUnavailable("email disabled")
    tenant = db.get(Tenant, user.tenant_id)
    rendered = render_login_code(
        lang=user.preferred_language, code=code, minutes=settings.auth_email_code_ttl_minutes,
        recipient_name=user.first_name or user.display_name, tenant_name=tenant.name if tenant else "hocX",
        base_url=config.link_base_url,
    )
    from app.notifications import delivery_status

    try:
        email_transport.send(config, email_transport.OutgoingEmail(to=user.email.strip(), subject=rendered.subject, text=rendered.text, html=rendered.html, images=rendered.images))
    except email_transport.EmailError as exc:
        # Zentraler Versandstatus + gedrosselt ins Fehlerprotokoll (delivery_status)
        delivery_status.record_failure(db, exc, kind="login_code", tenant_id=user.tenant_id)
        raise ChallengeUnavailable(str(exc)) from exc
    delivery_status.record_success(db)


def available(db: Session) -> bool:
    from app.notifications import email_transport

    return email_transport.load_config(db) is not None


def start(db: Session, *, user: AppUser, request_host: str | None, context: dict) -> str:
    """Ticket anlegen und Code verschicken. ``context`` (Risiko, Gerät) reist im Ticket mit und
    wird nach bestandener Prüfung für Session und Ereignisse gebraucht. Wirft ChallengeUnavailable."""
    ticket = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    data = {
        "kind": KIND, "user_id": user.id, "request_host": request_host, "issued_at_ms": int(datetime.now(UTC).timestamp() * 1000),
        "code_hash": _code_hash(ticket, code), "attempts": 0, "sends": 1, "context": context,
    }
    _send(db, user, code)
    get_redis_sync().set(f"{FLOW_PREFIX}{ticket}", json.dumps(data), nx=True, ex=settings.auth_email_code_ttl_minutes * 60)
    events.record(event_type="login.challenge", outcome="challenged", user_id=user.id, tenant_id=user.tenant_id, details={"method": "email"})
    return ticket


def _invalid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "mfa_flow_expired", "message": "Bestätigung ist abgelaufen, bitte erneut anmelden"})


def _load(ticket: str) -> tuple[dict, int]:
    client = get_redis_sync()
    key = f"{FLOW_PREFIX}{ticket}"
    raw = client.get(key)
    if raw is None:
        raise _invalid()
    data = json.loads(raw)
    if data.get("kind") != KIND:
        raise _invalid()
    return data, max(1, client.ttl(key))


def resend(db: Session, ticket: str) -> None:
    data, ttl = _load(ticket)
    if int(data.get("sends", 1)) >= MAX_SENDS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": "rate_limited", "message": "Zu viele Codes angefordert"})
    user = db.get(AppUser, int(data["user_id"]))
    if user is None:
        raise _invalid()
    code = f"{secrets.randbelow(1_000_000):06d}"
    data["code_hash"] = _code_hash(ticket, code)
    data["sends"] = int(data.get("sends", 1)) + 1
    data["attempts"] = 0
    try:
        _send(db, user, code)
    except ChallengeUnavailable:
        # Erwartet und bereits erfasst (Versandstatus + Fehlerprotokoll in _send): kein zweiter
        # Eintrag über den HTTPException-Handler.
        raise email_unavailable() from None
    get_redis_sync().set(f"{FLOW_PREFIX}{ticket}", json.dumps(data), ex=ttl)


def verify(db: Session, *, ticket: str, code: str) -> tuple[AppUser, dict]:
    """Prüft den Code; liefert Konto und Ticket-Daten. Das Ticket wird bei Erfolg verbraucht
    (GETDEL), bei Fehlversuchen gezählt (höchstens MAX_ATTEMPTS)."""
    enforce_rate_limit(f"email-challenge:{ticket}", limit=MAX_ATTEMPTS * MAX_SENDS, period_seconds=settings.auth_email_code_ttl_minutes * 60)
    data, ttl = _load(ticket)
    user = db.get(AppUser, int(data["user_id"]))
    if user is None or not user.is_active or not user.login_enabled or user.has_left:
        raise _invalid()
    # Millisekunden wie beim Session-Token (Security-Review N4)
    if user.session_revoke_at is not None and int(user.session_revoke_at.timestamp() * 1000) > int(data.get("issued_at_ms", 0)):
        raise _invalid()
    client = get_redis_sync()
    if not hmac.compare_digest(_code_hash(ticket, (code or "").strip()), str(data.get("code_hash"))):
        data["attempts"] = int(data.get("attempts", 0)) + 1
        if data["attempts"] >= MAX_ATTEMPTS:
            client.delete(f"{FLOW_PREFIX}{ticket}")
        else:
            client.set(f"{FLOW_PREFIX}{ticket}", json.dumps(data), ex=ttl)
        events.record(event_type="login.challenge", outcome="failure", user_id=user.id, tenant_id=user.tenant_id, details={"method": "email"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "email_code_invalid", "message": "Der Code ist nicht gültig"})
    if client.getdel(f"{FLOW_PREFIX}{ticket}") is None:
        raise _invalid()
    events.record(event_type="login.challenge", outcome="success", user_id=user.id, tenant_id=user.tenant_id, details={"method": "email"})
    return user, data

