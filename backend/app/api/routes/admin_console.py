"""Plattform-Admin 1.5.1: Einstellungsseiten (Sicherheit, Integrationen, Technik), Verläufe für
Betrieb (Datenbank/Redis aus ``system_metric_sample``) und Mandanten-Detail-Tabs (Features,
Nutzung, Sicherheit).

Alles nur lesend. Rechte:
- Sicherheitseinstellungen (welche Aktion welche Passkey-Bestätigung braucht, Sitzungsdauer) sieht
  jeder Plattform-Admin - keine Geheimnisse, keine Personendaten.
- Integrationen und Technik (Infrastruktur: Hosts, Domains, Profile) nur owner.
- Verläufe Betrieb nur owner (wie /admin/system).
- Mandant: Features und Nutzung (Zählwerte aus tenant_metric_daily) jeder Admin; Sicherheit
  (Anmeldeereignisse mit Kontonamen) nur owner, Ansehen auditiert (gedrosselt).

Keine Geheimnisse in Antworten: von Zugangsdaten nur «gesetzt ja/nein» (Test
test_settings_have_no_secrets).
"""
from __future__ import annotations

import os
import platform
import uuid
from datetime import date, timedelta
from functools import cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner
from app.core.config import settings
from app.core.db import get_db
from app.models import PlatformNotificationSettings, Tenant
from app.services import public_id_service
from app.services.audit_service import AuditService
from app.services.metrics_rollup_service import today_local

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


def _tenant_internal_id(db: Session, tenant_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)  # nosemgrep: public-id-lookup-without-tenant -- Plattform-Admin (mandantenübergreifend, AdminGate)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return internal_id


# ── Einstellungen › Sicherheit & Anmeldung ─────────────────────────────────────────────────

# Router unter /api/admin, deren mutierende Routen auf Step-up geprüft werden (wie
# tests/test_admin_step_up.py, dort gegen main.py abgeglichen).
_ADMIN_ROUTE_MODULES = (
    "admin", "admin_identity_verification", "admin_document_templates", "admin_storage", "admin_maintenance",
    "admin_backups", "admin_cashflow", "admin_auth_security", "admin_analytics", "admin_overview", "admin_console",
)


@cache
def step_up_inventory() -> tuple[tuple[str, str, str], ...]:
    """(Methode, Pfad, Zweck) aller Admin-Routen mit Passkey-Bestätigung - aus den Dependencies
    abgeleitet, damit die Seite nie von der Wirklichkeit abweicht."""
    import importlib

    from app.core.admin_step_up import PURPOSES, require_step_up, step_up_proof

    def calls(dependant) -> set:
        found = {dependant.call}
        for sub in dependant.dependencies:
            found |= calls(sub)
        return found

    by_call = {require_step_up(purpose): purpose for purpose in PURPOSES} | {step_up_proof(purpose): purpose for purpose in PURPOSES}
    result: list[tuple[str, str, str]] = []
    for module_name in _ADMIN_ROUTE_MODULES:
        module = importlib.import_module(f"app.api.routes.{module_name}")
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            route_calls = calls(route.dependant)
            purpose = next((by_call[call] for call in route_calls if call in by_call), None)
            if purpose is None:
                continue
            for method in sorted(route.methods & {"POST", "PUT", "PATCH", "DELETE"}):
                result.append((method, f"/api/admin{route.path}", purpose))
    return tuple(sorted(result, key=lambda item: (item[2], item[1], item[0])))


@router.get("/settings/security")
def settings_security():
    """Wirksame Anmelderegeln der Plattform-Admins (read-only, aus Code und Umgebung)."""
    return {
        "admin_login": {"password": True, "passkey_required": True, "totp_allowed": False},
        "admin_session_ttl_hours": settings.admin_session_ttl_hours,
        "step_up_flow_minutes": 2,
        "step_up_actions": [{"method": method, "path": path, "purpose": purpose} for method, path, purpose in step_up_inventory()],
    }


# ── Einstellungen › Integrationen ──────────────────────────────────────────────────────────

IntegrationStatus = Literal["ok", "warning", "critical", "unknown", "off"]


def _host_only(url: str | None) -> str | None:
    """Nur Schema, Host und Port - nie Zugangsdaten aus einer URL (Security-Review N3)."""
    if not url:
        return None
    from urllib.parse import urlsplit

    parts = urlsplit(url if "://" in url else f"//{url}")
    if not parts.hostname:
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}" if parts.scheme else f"{parts.hostname}{port}"


def _check_status(snapshot, key: str) -> str:
    if snapshot is None:
        return "unknown"
    check = next((item for item in snapshot.checks if item.key == key), None)
    return check.status if check is not None else "unknown"


@router.get("/settings/integrations")
def settings_integrations(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Übersicht der angebundenen Dienste: eingerichtet ja/nein und Zustand aus dem Systemstatus.
    Nie Zugangsdaten, nur ob sie gesetzt sind."""
    from app.models.storage_entities import StorageProfile, StorageState
    from app.services import system_health_service

    snapshot = system_health_service.load_snapshot()
    notify = db.get(PlatformNotificationSettings, 1)
    smtp_ready = bool(notify and notify.email_enabled and notify.smtp_host and notify.email_from_address)
    ntfy_ready = bool(notify and notify.ntfy_enabled and notify.ntfy_server_url and notify.ntfy_topic)
    state = db.get(StorageState, 1)
    profile = db.get(StorageProfile, state.active_profile_id) if state is not None else None
    captcha_eu = "eu-api.friendlycaptcha.eu" in (settings.friendly_captcha_verify_url or "")
    items = [
        {
            "key": "smtp",
            "configured": smtp_ready,
            "status": ("critical" if notify and notify.last_send_error else "ok") if smtp_ready else "off",
            "params": {"host": _host_only(notify.smtp_host) if notify else None, "port": notify.smtp_port if notify else None,
                       "security": notify.smtp_security if notify else None, "password_set": bool(notify and notify.smtp_password_encrypted)},
            "href": "/admin/settings/notifications",
        },
        {
            "key": "ntfy",
            "configured": ntfy_ready,
            "status": ("warning" if notify and notify.last_send_error else "ok") if ntfy_ready else "off",
            "params": {"server": _host_only(notify.ntfy_server_url) if notify else None, "token_set": bool(notify and notify.ntfy_token_encrypted),
                       "last_sent_at": notify.last_sent_at.isoformat() if notify and notify.last_sent_at else None},
            "href": "/admin/settings/notifications",
        },
        {
            "key": "status_endpoint",
            "configured": bool(notify and notify.status_token_hash),
            "status": "ok" if notify and notify.status_token_hash else "off",
            "params": {},
            "href": "/admin/settings/notifications",
        },
        {
            "key": "object_storage",
            "configured": profile is not None,
            "status": _check_status(snapshot, "object_storage"),
            "params": {"profile": profile.name if profile else None, "provider": profile.provider if profile else None,
                       "location": getattr(profile, "location", None) if profile else None},
            "href": "/admin/storage",
        },
        {
            "key": "captcha",
            "configured": True,
            "status": _check_status(snapshot, "captcha_endpoint"),
            "params": {"region": "eu" if captcha_eu else "global"},
            "href": "/admin/system",
        },
        {
            "key": "clamav",
            "configured": bool(settings.clamav_host),
            "status": _check_status(snapshot, "clamav"),
            "params": {},
            "href": "/admin/system",
        },
        {
            "key": "docker_proxy",
            "configured": bool(settings.docker_api_url),
            "status": ("ok" if snapshot.docker_available else "critical") if snapshot is not None and snapshot.docker_configured else ("unknown" if settings.docker_api_url else "off"),
            "params": {},
            "href": "/admin/system",
        },
        {
            "key": "backup",
            "configured": _check_status(snapshot, "backup") not in ("unknown",),
            "status": _check_status(snapshot, "backup"),
            "params": {},
            "href": "/admin/backups",
        },
    ]
    return {"collected_at": snapshot.collected_at if snapshot is not None else None, "items": items}


# ── Einstellungen › Technik ────────────────────────────────────────────────────────────────


@router.get("/settings/system")
def settings_system(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    """Version, Umgebung, Datenbankstand, Kataloge und Domains der Plattform (read-only)."""
    from app.core.features_generated import FEATURES
    from app.core.locale_config_generated import LOCALES
    from app.core.permissions_generated import CATALOG

    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    server_version = db.execute(text("SHOW server_version")).scalar()
    feature_rows = db.execute(text("SELECT count(*) FROM feature")).scalar()
    return {
        "version": os.environ.get("HOCX_VERSION") or None,
        "environment": settings.environment,
        "server_location": settings.hocx_server_location,
        "alembic_revision": revision,
        "postgres_version": server_version,
        "python_version": platform.python_version(),
        "catalogs": {
            "permissions": len(CATALOG),
            "features": len(FEATURES),
            "features_in_database": int(feature_rows or 0),
            "locales": list(LOCALES),
        },
        "domains": {
            "app": settings.traefik_domain,
            "admin": settings.traefik_admin_domain,
            "abgabebox": settings.traefik_abgabebox_domain,
            "docs": settings.traefik_docs_domain,
            "website": settings.traefik_website_domain,
        },
    }


# ── Betrieb › Verlauf Datenbank und Redis ──────────────────────────────────────────────────

HISTORY_RANGES = {"24h": (timedelta(hours=24), 15), "7d": (timedelta(days=7), 120), "14d": (timedelta(days=14), 240)}
HISTORY_METRICS = ("postgres.latency_ms", "postgres.connections", "postgres.size_mb", "redis.latency_ms", "redis.used_mb")


@router.get("/system-status/history")
def system_status_history(
    range_: Literal["24h", "7d", "14d"] = Query("24h", alias="range"),
    db: Session = Depends(get_db),
    _admin: CurrentAdmin = Depends(require_admin_owner),
):
    """Verläufe aus den Ressourcen-Stichproben (alle ~5 min, 14 Tage aufbewahrt), je Raster
    gemittelt (Durchschnitt und Maximum)."""
    span, bucket_minutes = HISTORY_RANGES[range_]
    rows = db.execute(
        text(
            "SELECT to_timestamp(floor(extract(epoch FROM ts) / (:bucket * 60)) * (:bucket * 60)) AS bucket, metric, "
            "avg(value) AS avg_value, max(value) AS max_value FROM system_metric_sample "
            "WHERE metric = ANY(:metrics) AND subject = '' AND ts > now() - make_interval(secs => :secs) GROUP BY 1, 2 ORDER BY 1"
        ),
        {"bucket": bucket_minutes, "metrics": list(HISTORY_METRICS), "secs": int(span.total_seconds())},
    ).all()
    points: dict[str, dict[str, float]] = {}
    for bucket, metric, avg_value, max_value in rows:
        values = points.setdefault(bucket.isoformat(), {})
        values[f"{metric}.avg"] = round(float(avg_value), 2)
        values[f"{metric}.max"] = round(float(max_value), 2)
    first = db.execute(text("SELECT min(ts) FROM system_metric_sample")).scalar()
    return {
        "range": range_,
        "bucket_minutes": bucket_minutes,
        "metrics": list(HISTORY_METRICS),
        "collecting_since": first,
        "points": [{"bucket": bucket, "values": values} for bucket, values in points.items()],
    }


# ── Mandant › Features, Nutzung, Sicherheit ────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}/features")
def tenant_features(tenant_id: uuid.UUID, db: Session = Depends(get_db)):
    """Alle Katalog-Features mit dem Stand dieses Mandanten: Zugriff (voll/nur lesen/keiner),
    Quelle (Plan/Add-on) und seit wann."""
    internal_id = _tenant_internal_id(db, tenant_id)
    rows = db.execute(
        text(
            "SELECT f.code, f.name, tf.access, tf.source, tf.enabled_at FROM feature f "
            "LEFT JOIN tenant_feature tf ON tf.feature_code = f.code AND tf.tenant_id = :tenant_id ORDER BY f.code"
        ),
        {"tenant_id": internal_id},
    ).all()
    return [
        {"code": code, "name": name, "access": access or "none", "source": source, "enabled_at": enabled_at}
        for code, name, access, source, enabled_at in rows
    ]


USAGE_METRICS = ("logins", "users.active", "usage.protocols", "usage.files", "usage.events", "storage.bytes")
USAGE_RANGES = {"30d": 30, "90d": 90, "12m": 365}


@router.get("/tenants/{tenant_id}/usage")
def tenant_usage(tenant_id: uuid.UUID, range_: Literal["30d", "90d", "12m"] = Query("30d", alias="range"), db: Session = Depends(get_db)):
    """Tageswerte des Mandanten aus dem Kennzahlen-Rollup (nur Zählwerte, keine Personendaten).
    12 Monate: Monatsraster (Speicher = letzter Wert, sonst Summe)."""
    internal_id = _tenant_internal_id(db, tenant_id)
    start = today_local() - timedelta(days=USAGE_RANGES[range_])
    rows = db.execute(
        text(
            "SELECT day, metric, value FROM tenant_metric_daily WHERE tenant_id = :tenant_id AND metric = ANY(:metrics) "
            "AND day >= :start ORDER BY day"
        ),
        {"tenant_id": internal_id, "metrics": list(USAGE_METRICS), "start": start},
    ).all()
    by_day: dict[date, dict[str, float]] = {}
    for day, metric, value in rows:
        by_day.setdefault(day, {})[metric] = float(value)
    if range_ == "12m":
        months: dict[str, dict[str, float]] = {}
        for day, values in sorted(by_day.items()):
            bucket = months.setdefault(day.strftime("%Y-%m"), {})
            for metric, value in values.items():
                bucket[metric] = value if metric == "storage.bytes" else bucket.get(metric, 0.0) + value
        points = [{"bucket": month, "values": values} for month, values in months.items()]
    else:
        points = [{"bucket": day.isoformat(), "values": values} for day, values in sorted(by_day.items())]
    collecting_since = db.execute(text("SELECT min(day) FROM tenant_metric_daily")).scalar()
    totals: dict[str, float] = {}
    for point in points:
        for metric, value in point["values"].items():
            if metric != "storage.bytes":
                totals[metric] = totals.get(metric, 0.0) + value
    return {
        "range": range_,
        "bucket": "month" if range_ == "12m" else "day",
        "metrics": list(USAGE_METRICS),
        "collecting_since": collecting_since,
        "totals": totals,
        "points": points,
    }


TENANT_SECURITY_VIEW_MINUTES = 10


@router.get("/tenants/{tenant_id}/security")
def tenant_security(tenant_id: uuid.UUID, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_owner)):
    """Fehlversuche, Sperren und Warnungen dieses Mandanten (dieselben datensparsamen Abfragen wie
    die Seite «Sicherheit & Anmeldungen» des Vereins: Konto mit Anzeigename, keine Netze/Adressen).
    Ansehen auditiert, höchstens einmal pro Admin und Mandant in 10 Minuten."""
    from app.auth_security import read_service

    internal_id = _tenant_internal_id(db, tenant_id)
    result = {
        "summary": read_service.tenant_summary(db, internal_id),
        "warnings": read_service.tenant_warnings(db, internal_id),
        "events": read_service.tenant_events(db, internal_id, limit=50),
    }
    recent = db.scalar(
        text(
            "SELECT 1 FROM audit_log WHERE tenant_id = :tenant_id AND action = 'admin.tenant_security_viewed' AND actor_email = :email "
            "AND created_at > now() - make_interval(mins => :minutes) LIMIT 1"
        ),
        {"tenant_id": internal_id, "email": current_admin.email, "minutes": TENANT_SECURITY_VIEW_MINUTES},
    )
    if recent is None:
        audit.log(db, action="admin.tenant_security_viewed", actor_email=current_admin.email, tenant_id=internal_id, entity_type="tenant", entity_id=internal_id)
    return result

