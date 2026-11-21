"""Plattform-Admin: Anmeldeschutz (Auth-Audit 2026-11-20) - Daten für das Sicherheits-Dashboard
(zweiter Schritt) und Verwaltung der IP-Sperren (Stufe 5, Entsperren).

Lesen: nur owner (require_admin_owner; Anmeldeereignisse sind Personenbezug, Security-Review
Admin-Redesign M2). Sperren setzen/aufheben: require_admin_write, auditiert. Adressen
erscheinen nie im Klartext - nur gekürzte Pseudonyme; eine manuelle Sperre per IP wird beim Setzen
gehasht."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_security import blocks, read_service
from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner, require_admin_write
from app.core.config import settings
from app.core.admin_step_up import require_step_up
from app.core.db import get_db
from app.schemas.base import MAX_QUERY_OFFSET
from app.services.audit_service import AuditService

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


class BlockCreate(BaseModel):
    ip: str | None = Field(default=None, max_length=64)
    subject: str | None = Field(default=None, max_length=64)
    scope: Literal["source", "net"] = "source"
    minutes: int = Field(ge=1, le=blocks.MAX_MANUAL_MINUTES)
    reason: str = Field(min_length=3, max_length=200)


@router.get("/auth-security/summary", dependencies=[Depends(require_admin_owner)])
def auth_security_summary(db: Session = Depends(get_db)):
    return read_service.platform_summary(db)


# ── Admin-Redesign Phase E: Sicherheits-Übersicht, Warnungen, Richtlinien (nur owner) ─────────

# Wirksame Anmeldeschutz-Einstellungen, die die Richtlinien-Seite zeigt. Bewusst eine feste Liste
# (kein Präfix-Filter über alle auth_*-Felder): neue Einstellungen erscheinen erst, wenn sie hier
# eingetragen sind, und Geheimnisse (auth_secret, auth_secret_previous, admin_auth_secret …) oder
# Cookie-Namen können nie versehentlich ausgeliefert werden (Test test_policy_has_no_secrets).
POLICY_SETTINGS: dict[str, tuple[str, ...]] = {
    "sessions": ("auth_session_ttl_hours", "auth_session_idle_minutes", "auth_session_absolute_hours", "auth_device_ttl_days",
                 "admin_session_ttl_hours"),
    "limits": ("auth_ip_failures_soft", "auth_ip_failures_hard", "auth_net_failures_soft", "auth_net_failures_hard_hour",
               "auth_wide_failures_alert_hour", "auth_account_ip_failures", "auth_account_failures_challenge",
               "auth_account_failures_known_only", "auth_totp_account_limit", "auth_totp_drip_seconds", "auth_passkey_account_limit",
               "auth_ip_attempts_per_minute", "auth_ip_attempts_burst", "auth_net_attempts_per_minute", "auth_net_attempts_burst",
               "auth_net6_factor", "auth_wide_attempts_per_minute", "auth_wide_attempts_burst", "auth_emergency_ip_per_minute",
               "auth_emergency_account_per_minute"),
    "blocks": ("auth_block_strikes", "auth_block_minutes", "auth_critical_deny_minutes"),
    "risk": ("auth_risk_mode", "auth_risk_moderate", "auth_risk_high", "auth_risk_critical", "auth_global_attack_min",
             "auth_global_attack_factor", "auth_tenant_accounts_alert"),
    "step_up": ("auth_step_up_mfa_minutes", "auth_step_up_admin_minutes", "auth_email_code_ttl_minutes"),
    "alerts": ("auth_alert_stuffing_min", "auth_alert_stuffing_networks", "auth_alert_spraying_accounts", "auth_alert_account_failures",
               "auth_alert_account_networks", "auth_alert_admin_mfa_failures", "auth_alert_blocks_per_hour", "auth_alert_cross_tenant",
               "auth_alert_redis_memory_ratio"),
    "retention": ("auth_event_retention_days",),
    # Leak-Prüfung neuer Passwörter (SEC-AUTH-015) und Länder-Geolocation (Signal «neues Land»)
    "passwords": ("password_leak_check", "password_leak_min_count", "password_leak_timeout_seconds", "geoip_auto_update"),
}


@router.get("/auth-security/overview")
def auth_security_overview(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Kacheln der Sicherheits-Übersicht: Zähler 24 h, offene Warnungen, aktive Sperren."""
    alerts = read_service.platform_alerts(db)
    return {
        **read_service.platform_counters(db),
        "open_alerts": len(alerts),
        "critical_alerts": sum(1 for alert in alerts if alert["severity"] == "critical"),
        "active_blocks": len(read_service.active_blocks()),
    }


@router.get("/auth-security/alerts")
def auth_security_alerts(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Aktuell ausgelöste Alarmregeln (dieselben wie im Systemmonitor, nur Zahlen und Pseudonyme)."""
    return read_service.platform_alerts(db)


@router.get("/auth-security/policy")
def auth_security_policy(_admin: CurrentAdmin = Depends(require_admin_owner)):
    """Wirksame Anmeldeschutz-Einstellungen (read-only, ohne Geheimnisse)."""
    return {group: {name: getattr(settings, name) for name in names} for group, names in POLICY_SETTINGS.items()}


@router.get("/auth-security/events", dependencies=[Depends(require_admin_owner)])
def auth_security_events(
    db: Session = Depends(get_db),
    event_type: str | None = Query(None, max_length=64),
    outcome: Literal["success", "failure", "blocked", "challenged", "info"] | None = None,
    offset: int = Query(0, ge=0, le=MAX_QUERY_OFFSET),
    limit: int = Query(100, ge=1, le=500),
):
    return read_service.recent_events(db, limit=limit, offset=offset, event_type=event_type, outcome=outcome)


@router.get("/auth-security/blocks", dependencies=[Depends(require_admin_owner)])
def auth_security_blocks():
    return read_service.active_blocks()


@router.post("/auth-security/blocks", status_code=201, dependencies=[Depends(require_step_up("platform-settings"))])
def create_block(payload: BlockCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if not payload.ip and not payload.subject:
        raise HTTPException(status_code=422, detail="ip oder subject angeben")
    try:
        block = blocks.set_manual(ip=payload.ip, subject=payload.subject, scope=payload.scope, minutes=payload.minutes, reason=payload.reason, admin_id=admin.admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.log(db, action="admin.auth_block_set", actor_email=admin.email, details={"scope": block.scope, "minutes": payload.minutes, "reason": block.reason})
    return {"subject": block.subject, "until": block.until}


@router.delete("/auth-security/blocks/{subject}", status_code=204, dependencies=[Depends(require_step_up("platform-settings"))])
def delete_block(subject: str, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if len(subject) > 64 or not blocks.clear(subject, admin_id=admin.admin_id):
        raise HTTPException(status_code=404, detail="Sperre nicht gefunden")
    audit.log(db, action="admin.auth_block_cleared", actor_email=admin.email, details={"subject": subject[:12]})
    return Response(status_code=204)
