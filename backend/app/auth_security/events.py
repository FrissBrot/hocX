"""Sicherheitsereignisse ``auth_event`` (SEC-AUTH-012, Audit Abschnitt 10.1).

Ein Schema für alle Anmeldephasen. Geschrieben in einer eigenen, kurzen Transaktion
(``SessionLocal``): ein Ereignis darf weder mit dem Rollback des Aufrufers verschwinden noch ihn
blockieren. Scheitert das Schreiben (Datenbank überlastet), wird der Login nicht verhindert - der
Verlust wird gezählt und gedrosselt ins Fehlerprotokoll geschrieben (Abschnitt 11: «Security darf
kein DoS-Vektor werden»).

Nie gespeichert: Passwörter, Codes, Tickets, Tokens, Session-Cookies, eingegebene E-Mails im
Klartext, IP-Adressen im Klartext. Vom Standort nur der Ländercode (``src_country``, Migration 0215). ``details`` nimmt nur feste Kennungen/Zahlen auf
(``_ALLOWED_DETAIL_KEYS``).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterable

from sqlalchemy import text

from app.auth_security import context as request_context

_logger = logging.getLogger(__name__)

POLICY_VERSION = "risk-v1-2026-11-20"

# Ereignistypen (Abschnitt 10.1/10.2). Der Test test_auth_events prüft, dass nur diese entstehen.
EVENT_TYPES = frozenset({
    "login.password",          # Passwortphase (success/failure/blocked/challenged)
    "login.locked",            # gesperrter Versuch (je Zähler gesampelt)
    "login.challenge",         # zusätzliche Prüfung verlangt/bestanden (E-Mail-Code)
    "login.mfa.totp",
    "login.mfa.passkey",
    "login.success",           # Session ausgestellt
    "mfa.enroll",
    "mfa.remove",
    "mfa.setup_skipped",
    "session.revoke",
    "session.logout",
    "reset.request",
    "reset.complete",
    "password.change",
    "token.invalid",           # ungültiges/abgelaufenes Ticket oder Bridge-Token
    "block.set",
    "block.clear",
    "device.revoke",
    "stepup.success",
    "stepup.failure",
    "stepup.required",
    "ratelimit.backend_error",
    # Plattform-Admin (Aufrufer im Branch fix/admin-isolation)
    "admin.login.password",
    "admin.login.mfa",
    "admin.login.success",
    "admin.mfa.enroll",
    "admin.mfa.remove",
    "admin.stepup",
    "admin.logout",
})
OUTCOMES = frozenset({"success", "failure", "blocked", "challenged", "info"})

_ALLOWED_DETAIL_KEYS = frozenset({
    "reason", "factor", "layer", "count", "limit", "minutes", "by_admin", "method", "purpose", "action",
    "error", "stage", "scope", "revoked", "known_device", "new_device", "new_network", "mode", "kind",
    # 1.6 Sperren: gekürztes Subjekt der Sperre, setzender Admin, Vorfall (ab 1.6), Wiederholung
    "subject", "admin_id", "incident_id", "repeat",
})
# Risiko-Gewichte je Grund (1.6, ``details.weights``): nur bekannte Codes als Schlüssel, ganze Zahlen
_MAX_WEIGHTS = 20

_lost = 0
_last_error_logged = 0.0
_lock = threading.Lock()


def lost_events() -> int:
    """Seit Prozessstart nicht geschriebene Ereignisse (Systemcheck rate_limiter)."""
    return _lost


def _clean_weights(weights) -> dict[str, int] | None:
    if not isinstance(weights, dict):
        return None
    clean: dict[str, int] = {}
    for reason, weight in list(weights.items())[:_MAX_WEIGHTS]:
        if isinstance(reason, str) and reason.replace("_", "").isalnum() and len(reason) <= 40 and isinstance(weight, int) and not isinstance(weight, bool):
            clean[reason] = max(0, min(100, weight))
    return clean or None


def _clean_details(details: dict | None) -> dict:
    if not details:
        return {}
    clean: dict = {}
    for key, value in details.items():
        if key == "weights":
            weights = _clean_weights(value)
            if weights:
                clean[key] = weights
            continue
        if key not in _ALLOWED_DETAIL_KEYS:
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:64]
    return clean


def record(
    *,
    event_type: str,
    outcome: str,
    actor_kind: str | None = None,
    user_id: int | None = None,
    platform_admin_id: int | None = None,
    tenant_id: int | None = None,
    subject_hash: str | None = None,
    device_hash: str | None = None,
    session_id: uuid.UUID | None = None,
    risk_score: int | None = None,
    risk_reasons: Iterable[str] = (),
    risk_weights: dict[str, int] | None = None,
    enforcement: str | None = None,
    details: dict | None = None,
    ctx: request_context.RequestContext | None = None,
) -> None:
    """Schreibt ein Ereignis. Wirft nie (ausser bei Programmierfehlern im Typ).

    ``risk_weights`` (1.6): Gewicht je Risikogrund, landet in ``details.weights`` - für die
    Erklärung im Ereignis-Detail. Ältere Ereignisse haben nur die Gründe."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unbekannter auth_event-Typ: {event_type}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unbekanntes Ergebnis: {outcome}")
    ctx = ctx or request_context.current()
    if actor_kind is None:
        actor_kind = "admin" if platform_admin_id else ("user" if user_id else ("system" if event_type.startswith("ratelimit.") else "anonymous"))
    params = {
        "event_type": event_type,
        "outcome": outcome,
        "actor_kind": actor_kind,
        "actor_user_id": user_id,
        "platform_admin_id": platform_admin_id,
        "tenant_id": tenant_id,
        "subject_hash": subject_hash,
        "src_net_hash": ctx.net_hash,
        "src_ip_hash": ctx.ip_hash,
        "src_private": ctx.private,
        "device_hash": device_hash,
        "session_id": session_id,
        "request_id": ctx.request_id,
        "risk_score": max(0, min(100, int(risk_score))) if risk_score is not None else None,
        "risk_reasons": sorted(set(risk_reasons)),
        "enforcement": enforcement,
        "policy_version": POLICY_VERSION if risk_score is not None else None,
        "endpoint": (ctx.endpoint or "")[:128] or None,
        "host_kind": ctx.host_kind,
        "user_agent_family": ctx.user_agent_family,
        "src_country": ctx.country,
        "details": _clean_details({**(details or {}), **({"weights": risk_weights} if risk_weights and risk_score is not None else {})}),
    }
    _write(params)


_INSERT = text(
    """
    INSERT INTO auth_event (event_type, outcome, actor_kind, actor_user_id, platform_admin_id, tenant_id, subject_hash,
        src_net_hash, src_ip_hash, src_private, device_hash, session_id, request_id, risk_score, risk_reasons,
        enforcement, policy_version, endpoint, host_kind, user_agent_family, src_country, details)
    VALUES (:event_type, :outcome, :actor_kind, :actor_user_id, :platform_admin_id, :tenant_id, :subject_hash,
        :src_net_hash, :src_ip_hash, :src_private, :device_hash, :session_id, :request_id, :risk_score,
        CAST(:risk_reasons AS text[]), :enforcement, :policy_version, :endpoint, :host_kind, :user_agent_family,
        :src_country, CAST(:details AS jsonb))
    """
)


def _write(params: dict) -> None:
    import json

    from app.core.db import SessionLocal

    global _lost, _last_error_logged
    payload = {**params, "details": json.dumps(params["details"])}
    try:
        with SessionLocal() as session:
            session.execute(_INSERT, payload)
            session.commit()
    except Exception as exc:  # noqa: BLE001 - Ereignis-Verlust darf den Login nicht verhindern
        with _lock:
            _lost += 1
            now = time.monotonic()
            report = now - _last_error_logged >= 60
            if report:
                _last_error_logged = now
        _logger.warning("auth_event nicht geschrieben (%s): %s", params.get("event_type"), exc)
        if report:
            from app.core.db import SessionLocal as _Session
            from app.core.error_log import record_system_error

            try:
                with _Session() as session:
                    record_system_error(session, exc=exc)  # wirft nie, rollt selbst zurück
            except Exception:  # noqa: BLE001 - Datenbank ganz weg: bleibt im Log
                _logger.exception("Fehlerprotokoll nicht erreichbar")


def forget_user(db, user_ids: list[int]) -> int:
    """Personenbezug gelöschter Konten entfernen (vor dem Löschen, ohne Commit): Konto, Subjekt-
    und Geräte-Pseudonym. Die Ereignisse bleiben als anonyme Zählbasis bis zum Fristende."""
    if not user_ids:
        return 0
    # Vorfälle «Konto unter Beschuss» tragen das gekürzte Subjekt-Pseudonym (1.6): mit anonymisieren
    from app.auth_security import incidents

    prefixes = list(db.scalars(
        text("SELECT DISTINCT left(subject_hash, 12) FROM auth_event WHERE actor_user_id = ANY(:ids) AND subject_hash IS NOT NULL"),
        {"ids": list(user_ids)},
    ))
    incidents.forget_accounts(db, prefixes)
    return db.execute(
        text("UPDATE auth_event SET actor_user_id = NULL, subject_hash = NULL, device_hash = NULL WHERE actor_user_id = ANY(:ids)"),
        {"ids": list(user_ids)},
    ).rowcount or 0


def forget_tenant(db, tenant_id: int) -> int:
    from app.auth_security import incidents

    incidents.forget_tenant(db, tenant_id)
    return db.execute(text("DELETE FROM auth_event WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id}).rowcount or 0


def purge(db, *, retention_days: int) -> int:
    deleted = db.execute(
        text("DELETE FROM auth_event WHERE ts < now() - make_interval(days => :days)"), {"days": max(1, int(retention_days))}
    ).rowcount or 0
    db.commit()
    return deleted
