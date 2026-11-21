"""Plattform-Admin: Anmeldeschutz (Auth-Audit 2026-11-20) - Daten für das Sicherheits-Dashboard
(zweiter Schritt) und Verwaltung der IP-Sperren (Stufe 5, Entsperren).

1.5.1: Warnungen quittieren (Spalten an ``system_alert_state``, 0209), verschlüsselter Export von
Anmeldeereignissen und Audit-Log (Step-up ``security-export``) und Auflösung des pseudonymen
Subjekts eines Ereignisses zu einem Konto (Step-up ``security-resolve``, auditiert, nie die Adresse).

Lesen: nur owner (require_admin_owner; Anmeldeereignisse sind Personenbezug, Security-Review
Admin-Redesign M2). Sperren setzen/aufheben: require_admin_write, auditiert. Adressen
erscheinen nie im Klartext - nur gekürzte Pseudonyme; eine manuelle Sperre per IP wird beim Setzen
gehasht."""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth_security import blocks, read_service
from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner, require_admin_write
from app.core.config import settings
from app.core.admin_step_up import require_step_up
from app.core.db import get_db, release_for_stream
from app.core.rate_limit import enforce_rate_limit
from app.schemas.base import MAX_QUERY_OFFSET
from app.services import export_crypto
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
}


@router.get("/auth-security/overview")
def auth_security_overview(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Kacheln der Sicherheits-Übersicht: Zähler 24 h, offene (nicht quittierte) Warnungen, aktive Sperren."""
    alerts = _alerts_with_acks(db)
    open_alerts = [alert for alert in alerts if alert["acknowledged_at"] is None]
    return {
        **read_service.platform_counters(db),
        "open_alerts": len(open_alerts),
        "critical_alerts": sum(1 for alert in open_alerts if alert["severity"] == "critical"),
        "acknowledged_alerts": len(alerts) - len(open_alerts),
        "active_blocks": len(read_service.active_blocks()),
    }


def _ack_is_current(acknowledged_at, last_at) -> bool:
    """Eine Quittung gilt nur bis zum nächsten auslösenden Ereignis: kommt nach dem Quittieren ein
    neues (z. B. die nächste Anmeldung von einem neuen Gerät), ist die Warnung wieder offen."""
    return acknowledged_at is not None and (last_at is None or acknowledged_at >= last_at)


# Regeln, deren Subjekt eine interne ID ist (kein Pseudonym): für die Anzeige auflösen (nur owner sieht
# die Warnungen). Konten-Pseudonyme bleiben Pseudonyme (Auflösung nur über resolve-subject).
_ADMIN_SUBJECT_RULES = frozenset({"admin_mfa", "admin_new_device"})
_TENANT_SUBJECT_RULES = frozenset({"tenant"})


def _subject_labels(db: Session, alerts: list[dict]) -> dict[str, str]:
    def ids(rules) -> list[int]:
        return [int(alert["subject"]) for alert in alerts if alert["rule"] in rules and str(alert["subject"] or "").isdigit()]

    labels: dict[str, str] = {}
    admin_ids, tenant_ids = ids(_ADMIN_SUBJECT_RULES), ids(_TENANT_SUBJECT_RULES)
    if admin_ids:
        for admin_id, name in db.execute(text("SELECT id, display_name FROM platform_admin WHERE id = ANY(:ids)"), {"ids": admin_ids}):
            labels[f"admin:{admin_id}"] = name
    if tenant_ids:
        for tenant_id, name in db.execute(text("SELECT id, name FROM tenant WHERE id = ANY(:ids)"), {"ids": tenant_ids}):
            labels[f"tenant:{tenant_id}"] = name
    return labels


def _alerts_with_acks(db: Session) -> list[dict]:
    """Live-Alarmregeln plus Quittung aus system_alert_state (gleicher Schlüssel wie im Systemmonitor)."""
    alerts = read_service.platform_alerts(db)
    keys = [alert["key"] for alert in alerts]
    acks = {}
    if keys:
        acks = {
            row.problem_key: row
            for row in db.execute(
                text(
                    "SELECT s.problem_key, s.first_seen_at, s.acknowledged_at, s.acknowledged_note, a.display_name AS acknowledged_by "
                    "FROM system_alert_state s LEFT JOIN platform_admin a ON a.id = s.acknowledged_by_admin_id "
                    "WHERE s.problem_key = ANY(:keys)"
                ),
                {"keys": keys},
            )
        }
    labels = _subject_labels(db, alerts)
    result = []
    for alert in alerts:
        row = acks.get(alert["key"])
        current = bool(row) and _ack_is_current(row.acknowledged_at, alert.get("last_at"))
        kind = "admin" if alert["rule"] in _ADMIN_SUBJECT_RULES else "tenant" if alert["rule"] in _TENANT_SUBJECT_RULES else None
        result.append({
            **alert,
            "subject_label": labels.get(f"{kind}:{alert['subject']}") if kind else None,
            "first_seen_at": row.first_seen_at if row else None,
            "acknowledged_at": row.acknowledged_at if current else None,
            "acknowledged_by": row.acknowledged_by if current else None,
            "acknowledged_note": row.acknowledged_note if current else None,
        })
    return result


@router.get("/auth-security/alerts")
def auth_security_alerts(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Aktuell ausgelöste Alarmregeln (dieselben wie im Systemmonitor, nur Zahlen und Pseudonyme),
    mit Quittung."""
    return _alerts_with_acks(db)


class AlertAck(BaseModel):
    key: str = Field(min_length=5, max_length=200, pattern=r"^auth:[a-z_]+(:[A-Za-z0-9_-]+)?$")
    note: str | None = Field(default=None, max_length=500)


def _active_alert(db: Session, key: str) -> dict:
    alert = next((item for item in read_service.platform_alerts(db) if item["key"] == key), None)
    if alert is None:
        raise HTTPException(status_code=404, detail={"code": "alert_not_active", "message": "Die Warnung ist nicht (mehr) aktiv."})
    return alert


@router.post("/auth-security/alerts/ack")
def acknowledge_alert(payload: AlertAck, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Warnung quittieren: «gesehen, wird bearbeitet». Gilt, solange die Warnung offen ist - klingt
    sie ab und tritt später wieder auf, ist sie wieder offen (die Zeile in system_alert_state
    verschwindet mit dem Problem). Ändert nichts an Sperren oder Benachrichtigungen."""
    alert = _active_alert(db, payload.key)
    note = (payload.note or "").strip() or None
    # Der Systemmonitor legt die Zeile beim nächsten Durchlauf ohnehin an; existiert sie noch nicht,
    # mit denselben Werten anlegen (gleicher Schlüssel, first_seen jetzt).
    db.execute(
        text(
            "INSERT INTO system_alert_state (problem_key, severity, reason, title, message, first_seen_at, acknowledged_at, "
            "acknowledged_by_admin_id, acknowledged_note) VALUES (:key, :severity, :reason, :title, :message, now(), now(), :admin_id, :note) "
            "ON CONFLICT (problem_key) DO UPDATE SET acknowledged_at = now(), acknowledged_by_admin_id = :admin_id, acknowledged_note = :note"
        ),
        {"key": alert["key"], "severity": alert["severity"], "reason": alert["rule"], "title": alert["title"], "message": alert["message"],
         "admin_id": admin.admin_id, "note": note},
    )
    db.commit()
    audit.log(db, action="admin.security_alert_acknowledged", actor_email=admin.email, details={"key": alert["key"], "rule": alert["rule"]})
    _invalidate_nav_counts()
    return {"key": alert["key"], "acknowledged": True}


@router.post("/auth-security/alerts/unack")
def unacknowledge_alert(payload: AlertAck, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Quittung zurücknehmen (Warnung wieder als offen zählen)."""
    updated = db.execute(
        text(
            "UPDATE system_alert_state SET acknowledged_at = NULL, acknowledged_by_admin_id = NULL, acknowledged_note = NULL "
            "WHERE problem_key = :key AND acknowledged_at IS NOT NULL"
        ),
        {"key": payload.key},
    ).rowcount
    db.commit()
    if not updated:
        raise HTTPException(status_code=404, detail={"code": "alert_not_acknowledged", "message": "Die Warnung ist nicht quittiert."})
    audit.log(db, action="admin.security_alert_reopened", actor_email=admin.email, details={"key": payload.key})
    _invalidate_nav_counts()
    return {"key": payload.key, "acknowledged": False}


def _invalidate_nav_counts() -> None:
    from app.services.admin_overview_service import invalidate_nav_counts

    invalidate_nav_counts()


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


@router.post("/auth-security/blocks", status_code=201, dependencies=[Depends(require_step_up("security-block"))])
def create_block(payload: BlockCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if not payload.ip and not payload.subject:
        raise HTTPException(status_code=422, detail="ip oder subject angeben")
    try:
        block = blocks.set_manual(ip=payload.ip, subject=payload.subject, scope=payload.scope, minutes=payload.minutes, reason=payload.reason, admin_id=admin.admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.log(db, action="admin.auth_block_set", actor_email=admin.email, details={"scope": block.scope, "minutes": payload.minutes, "reason": block.reason})
    return {"subject": block.subject, "until": block.until}


@router.delete("/auth-security/blocks/{subject}", status_code=204, dependencies=[Depends(require_step_up("security-block"))])
def delete_block(subject: str, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if len(subject) > 64 or not blocks.clear(subject, admin_id=admin.admin_id):
        raise HTTPException(status_code=404, detail="Sperre nicht gefunden")
    audit.log(db, action="admin.auth_block_cleared", actor_email=admin.email, details={"subject": subject[:12]})
    return Response(status_code=204)


# ── Export (1.5.1, Plan §8.3 /security/export) ─────────────────────────────────────────────

EXPORT_MAX_DAYS = 92
EXPORT_MAX_ROWS = 500_000
_TZ = ZoneInfo("Europe/Zurich")


class SecurityExportRequest(BaseModel):
    kind: Literal["auth_events", "audit_log"]
    date_from: date
    date_to: date
    event_type: str | None = Field(default=None, max_length=64)
    outcome: Literal["success", "failure", "blocked", "challenged", "info"] | None = None
    action: str | None = Field(default=None, max_length=100)
    # Pflicht: der Export ist für Menschen bestimmt (Server-Schlüssel wäre nur auf dem Server lesbar)
    password: str = Field(min_length=export_crypto.MIN_PASSWORD_LENGTH, max_length=1024)


def _export_bounds(payload: SecurityExportRequest) -> tuple[datetime, datetime]:
    if payload.date_to < payload.date_from:
        raise HTTPException(status_code=422, detail={"code": "range_invalid", "message": "Das Enddatum liegt vor dem Startdatum."})
    if (payload.date_to - payload.date_from).days >= EXPORT_MAX_DAYS:
        raise HTTPException(status_code=422, detail={"code": "range_too_long", "message": f"Höchstens {EXPORT_MAX_DAYS} Tage pro Export."})
    start = datetime.combine(payload.date_from, time.min, tzinfo=_TZ)
    end = datetime.combine(payload.date_to + timedelta(days=1), time.min, tzinfo=_TZ)
    return start, end


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _write_auth_events(db: Session, handle, start: datetime, end: datetime, payload: SecurityExportRequest) -> int:
    rows = db.execute(
        text(
            "SELECT event_id, ts, event_type, outcome, actor_kind, actor_user_id, platform_admin_id, tenant_id, subject_hash, "
            "src_net_hash, device_hash, session_id, request_id, risk_score, risk_reasons, enforcement, policy_version, endpoint, "
            "host_kind, user_agent_family, details FROM auth_event WHERE ts >= :start AND ts < :end "
            "AND (CAST(:event_type AS text) IS NULL OR event_type = :event_type) AND (CAST(:outcome AS text) IS NULL OR outcome = :outcome) "
            "ORDER BY ts LIMIT :limit"
        ),
        {"start": start, "end": end, "event_type": payload.event_type, "outcome": payload.outcome, "limit": EXPORT_MAX_ROWS},
        execution_options={"stream_results": True, "yield_per": 2000},
    ).mappings()
    count = 0
    for row in rows:
        item = dict(row)
        # Pseudonyme gekürzt wie in der Ansicht (keine Adressen, auch nicht gehasht in voller Länge)
        for key in ("subject_hash", "src_net_hash", "device_hash"):
            item[key] = item[key][:12] if item[key] else None
        handle.write(json.dumps(item, default=_json_value, ensure_ascii=False) + "\n")
        count += 1
    return count


def _write_audit_log(db: Session, handle, start: datetime, end: datetime, payload: SecurityExportRequest) -> int:
    from app.core.sql_like import prefix_pattern

    rows = db.execute(
        text(
            "SELECT l.id, l.created_at, l.action, l.outcome, t.public_id AS tenant_id, l.actor_email, l.ip_hash, l.entity_type, "
            "l.entity_id, l.details_json AS details FROM audit_log l LEFT JOIN tenant t ON t.id = l.tenant_id "
            "WHERE l.created_at >= :start AND l.created_at < :end "
            "AND (CAST(:action AS text) IS NULL OR l.action LIKE :action ESCAPE '\\') ORDER BY l.created_at, l.id LIMIT :limit"
        ),
        {"start": start, "end": end, "action": prefix_pattern(payload.action) if payload.action else None, "limit": EXPORT_MAX_ROWS},
        execution_options={"stream_results": True, "yield_per": 2000},
    ).mappings()
    count = 0
    for row in rows:
        item = dict(row)
        # wie in der Ansicht nur gekürzt (volles Pseudonym erlaubte Korrelation, Security-Review N2)
        item["ip_hash"] = item["ip_hash"][:12] if item["ip_hash"] else None
        handle.write(json.dumps(item, default=_json_value, ensure_ascii=False) + "\n")
        count += 1
    return count


@router.post("/auth-security/export", dependencies=[Depends(require_step_up("security-export"))])
def export_security_data(payload: SecurityExportRequest, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Anmeldeereignisse oder Audit-Log eines Zeitraums als JSONL, nur verschlüsselt (export_crypto,
    Passwort Pflicht). Höchstens 92 Tage und 500 000 Zeilen, 10 Exporte pro Stunde je Admin;
    auditiert (Zeitraum, Art, Anzahl - ohne Filterwerte mit Personenbezug)."""
    start, end = _export_bounds(payload)
    enforce_rate_limit(f"admin-security-export:{admin.admin_id}", limit=10, period_seconds=60 * 60)
    try:
        password = export_crypto.validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    work_dir = Path(tempfile.mkdtemp(prefix="hocx-security-export-"))
    plain = work_dir / "export.jsonl"
    encrypted = work_dir / ("export.jsonl" + export_crypto.ENCRYPTED_SUFFIX)

    def cleanup() -> None:
        for path in (plain, encrypted):
            path.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    try:
        with plain.open("w", encoding="utf-8") as handle:
            writer = _write_auth_events if payload.kind == "auth_events" else _write_audit_log
            rows = writer(db, handle, start, end, payload)
        export_crypto.encrypt_file(plain, encrypted, password=password)
        plain.unlink(missing_ok=True)
        audit.log(
            db, action="admin.security_exported", actor_email=admin.email,
            details={"kind": payload.kind, "from": payload.date_from.isoformat(), "to": payload.date_to.isoformat(), "rows": rows,
                     "truncated": rows >= EXPORT_MAX_ROWS},
        )
        filename = f"hocx-{payload.kind.replace('_', '-')}-{payload.date_from.isoformat()}-{payload.date_to.isoformat()}.jsonl{export_crypto.ENCRYPTED_SUFFIX}"
        return release_for_stream(db, FileResponse(encrypted, filename=filename, media_type="application/octet-stream", background=BackgroundTask(cleanup)))
    except Exception:
        # Klartext und Verschlüsseltes nie liegen lassen (Security-Review N1); der Fehler läuft weiter
        # an den globalen Handler (Fehlerprotokoll).
        cleanup()
        raise


# ── Subjekt auflösen (1.5.1, Plan §8.3 resolve-subject) ─────────────────────────────────────

# Höchstens so viele Konten werden für die Hash-Suche (Fehlversuche ohne Kontobezug) gehasht.
RESOLVE_SCAN_LIMIT = 200_000


class ResolvedSubject(BaseModel):
    kind: Literal["user", "admin", "unknown"]
    via: Literal["event", "related_event", "hash", "none"]
    user_id: uuid.UUID | None = None
    admin_id: uuid.UUID | None = None
    display_name: str | None = None
    email: str | None = None
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    login_enabled: bool | None = None
    is_active: bool | None = None


def _resolve_by_hash(db: Session, subject_hash: str, admin_first: bool) -> tuple[str, int] | None:
    """Fehlversuch ohne Kontobezug: das Pseudonym gegen die Login-Adressen rechnen (kein Umkehren -
    nur Vergleich). Adressen, die kein Konto haben, bleiben «unbekannt»."""
    from app.core.auth_pseudonym import subject_hash as hash_of

    # Nur Login-Adressen: nur sie kommen in Anmeldeversuchen vor und sind eindeutig (Personen ohne
    # Login dürfen dieselbe Adresse haben - sonst träfe die Suche eine unbeteiligte Person).
    sources = [("admin", "SELECT id, email FROM platform_admin"), ("user", "SELECT id, email FROM app_user WHERE email IS NOT NULL AND login_enabled")]
    if not admin_first:
        sources.reverse()
    for kind, sql in sources:
        rows = db.execute(text(sql + " ORDER BY id LIMIT :limit"), {"limit": RESOLVE_SCAN_LIMIT},  # sql-ok: feste Abfragen aus dieser Funktion
                          execution_options={"stream_results": True, "yield_per": 5000})
        try:
            for internal_id, email in rows:
                if email and hash_of(email) == subject_hash:
                    return kind, int(internal_id)
        finally:
            rows.close()
    return None


@router.post("/auth-security/events/{event_id}/resolve-subject", response_model=ResolvedSubject,
             dependencies=[Depends(require_step_up("security-resolve"))])
def resolve_event_subject(event_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Welches Konto steckt hinter dem Pseudonym eines Ereignisses? Nur Konto (Name, Login-Adresse,
    Mandant), nie Netz oder Adresse. Je Auflösung ein Audit-Eintrag (mit Mandant des Kontos, damit
    auch dessen Verlauf zeigt, dass aufgelöst wurde); höchstens 30 pro Stunde je Admin."""
    enforce_rate_limit(f"admin-security-resolve:{admin.admin_id}", limit=30, period_seconds=60 * 60)
    event = db.execute(
        text("SELECT actor_kind, actor_user_id, platform_admin_id, subject_hash FROM auth_event WHERE event_id = :id"),
        {"id": event_id},
    ).mappings().first()
    if event is None:
        raise HTTPException(status_code=404, detail="Ereignis nicht gefunden")
    found: tuple[str, int] | None = None
    via = "none"
    if event["platform_admin_id"] is not None:
        found, via = ("admin", int(event["platform_admin_id"])), "event"
    elif event["actor_user_id"] is not None:
        found, via = ("user", int(event["actor_user_id"])), "event"
    elif event["subject_hash"]:
        related = db.execute(
            text(
                "SELECT platform_admin_id, actor_user_id FROM auth_event WHERE subject_hash = :hash "
                "AND (platform_admin_id IS NOT NULL OR actor_user_id IS NOT NULL) ORDER BY ts DESC LIMIT 1"
            ),
            {"hash": event["subject_hash"]},
        ).first()
        if related is not None:
            found = ("admin", int(related[0])) if related[0] is not None else ("user", int(related[1]))
            via = "related_event"
        else:
            found = _resolve_by_hash(db, event["subject_hash"], admin_first=event["actor_kind"] == "admin")
            via = "hash" if found else "none"

    result = ResolvedSubject(kind="unknown", via=via)
    tenant_internal_id = None
    entity_type = None
    if found and found[0] == "admin":
        row = db.execute(text("SELECT public_id, display_name, email, is_active FROM platform_admin WHERE id = :id"), {"id": found[1]}).first()
        if row is not None:
            result = ResolvedSubject(kind="admin", via=via, admin_id=row.public_id, display_name=row.display_name, email=row.email, is_active=row.is_active)
            entity_type = "platform_admin"
    elif found:
        row = db.execute(
            text(
                "SELECT u.public_id, u.display_name, u.email, u.login_enabled, u.is_active, u.tenant_id, t.public_id AS tenant_public_id, "
                "t.name AS tenant_name FROM app_user u JOIN tenant t ON t.id = u.tenant_id WHERE u.id = :id"
            ),
            {"id": found[1]},
        ).first()
        if row is not None:
            result = ResolvedSubject(
                kind="user", via=via, user_id=row.public_id, display_name=row.display_name, email=row.email, tenant_id=row.tenant_public_id,
                tenant_name=row.tenant_name, login_enabled=row.login_enabled, is_active=row.is_active,
            )
            tenant_internal_id = row.tenant_id
            entity_type = "user"
    audit.log(
        db, action="admin.security_subject_resolved", actor_email=admin.email, tenant_id=tenant_internal_id,
        entity_type=entity_type, entity_id=found[1] if found and result.kind != "unknown" else None,
        details={"event_id": str(event_id), "kind": result.kind, "via": via},
    )
    return result
