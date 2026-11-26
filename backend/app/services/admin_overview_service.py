"""Plattform-Admin: Übersicht (Dashboard), Navigationszähler und Ctrl+K-Suche (Admin-Redesign §3, §4.3, §6.1).

Grundsätze:
- Nur Aggregate. Kein Endpunkt hier liefert Mandantenbenutzer-Daten ausser der Suche (Gruppe
  ``users``, nur owner, E-Mail maskiert).
- Felder aus Quellen, die heute nur ``owner`` lesen darf (Systemstatus, Fehlerprotokoll, Audit-Log,
  Jobs, Anmeldeereignisse), sind für ``support`` ``None``.
- Redis-Cache je Rolle (60 s), teure Kennzahlen (aktive Benutzer 30 T) 15 min. Redis weg: es wird
  direkt gerechnet (Cache ist reine Entlastung).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.job_registry import JOB_DEFINITIONS
from app.core.redis_client import get_redis_sync
from app.core.sql_like import LIKE_ESCAPE, contains_pattern, prefix_pattern

_logger = logging.getLogger(__name__)

OVERVIEW_TTL_SECONDS = 60
NAV_COUNTS_TTL_SECONDS = 60
ACTIVE_USERS_TTL_SECONDS = 15 * 60
STORAGE_WARN_RATIO = 0.85
FEED_LIMIT = 20
SEARCH_GROUP_LIMIT = 5

# Fehlgeschlagene Anmeldeversuche (wie app/auth_security/threats.py::_FAILURE, plus Admin-Login).
_LOGIN_FAILURE_SQL = "outcome = 'failure' AND event_type LIKE 'login.%'"
_LOGIN_SUCCESS_SQL = "event_type = 'login.success'"

Range = Literal["24h", "7d", "30d", "90d"]
# Zeitraum → (Stunden, Bucket-Grösse in Stunden) gemäss Plan §3.4
RANGES: dict[str, tuple[int, int]] = {"24h": (24, 1), "7d": (24 * 7, 6), "30d": (24 * 30, 24), "90d": (24 * 90, 24)}


# ── Cache ──────────────────────────────────────────────────────────────────


def _cached(key: str, ttl: int, compute: Callable[[], Any]) -> Any:
    try:
        raw = get_redis_sync().get(key)
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001 - Cache ist optional, Redis weg = direkt rechnen
        _logger.warning("Admin-Übersicht: Redis-Cache nicht lesbar (%s)", key, exc_info=True)
    value = compute()
    try:
        get_redis_sync().set(key, json.dumps(value, default=_json_default), ex=ttl)
    except Exception:  # noqa: BLE001 - s. o.
        _logger.warning("Admin-Übersicht: Redis-Cache nicht schreibbar (%s)", key, exc_info=True)
    return json.loads(json.dumps(value, default=_json_default))


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"nicht serialisierbar: {type(value).__name__}")


# ── Bausteine ──────────────────────────────────────────────────────────────


def _scalar(db: Session, sql: str, params: dict | None = None) -> int:
    return int(db.execute(text(sql), params or {}).scalar() or 0)


def _system_status(db: Session, now: datetime) -> dict:
    """Eingaben für die Statusregel §3.2 (abgeleitet wird im Frontend: derivePlatformStatus)."""
    from app.services import maintenance_service, system_alert_service, system_health_service

    snapshot = system_health_service.load_snapshot()
    stale = system_health_service.is_stale(snapshot, now)
    problems = system_alert_service.current_problems(db, snapshot, now=now)
    runtime_warning = False
    docker_unavailable = False
    if snapshot is not None:
        runtime_warning = any(check.key == "runtime" and check.status in ("warning", "critical") for check in snapshot.checks)
        docker_unavailable = snapshot.docker_configured and not snapshot.docker_available
    maintenance = maintenance_service.public_status(db)
    overload_recent = _scalar(db, "SELECT count(*) FROM overload_rejection WHERE created_at > now() - interval '5 minutes'")
    severity_rank = {"critical": 0, "warning": 1}
    ordered = sorted(problems, key=lambda problem: (severity_rank.get(problem.severity, 2), problem.key))
    return {
        "snapshot_at": snapshot.collected_at if snapshot else None,
        "stale": stale,
        "docker_unavailable": docker_unavailable,
        "critical": sum(1 for problem in problems if problem.severity == "critical"),
        "warning": sum(1 for problem in problems if problem.severity == "warning"),
        "maintenance_active": bool(maintenance.get("active") or maintenance.get("partial")),
        "maintenance_started_at": maintenance.get("started_at"),
        "runtime_warning": runtime_warning,
        "overload_recent": overload_recent,
        # Höchstens 5 auslösende Probleme (Schlüssel + Quelle, für Tooltip/Links) - keine Texte mit Details.
        "problems": [
            {"key": problem.key, "source": problem.source, "subject": problem.subject, "reason": problem.reason, "severity": problem.severity}
            for problem in ordered[:5]
        ],
    }


def _count_with_previous(db: Session, table: str, column: str, where: str, hours: int) -> dict:
    """Anzahl im Fenster (jetzt - hours) und im Fenster davor. ``table``/``column``/``where`` sind feste
    Konstanten dieses Moduls, nie Benutzereingaben."""
    row = db.execute(
        text(  # sql-ok: table/column/where sind feste Konstanten dieses Moduls
            f"SELECT count(*) FILTER (WHERE {column} > now() - make_interval(hours => :h)) AS current, "  # sql-ok: feste Konstanten
            f"count(*) FILTER (WHERE {column} <= now() - make_interval(hours => :h)) AS previous "
            f"FROM {table} WHERE {column} > now() - make_interval(hours => :h2) AND ({where})"
        ),
        {"h": hours, "h2": hours * 2},
    ).one()
    return {"value": int(row.current or 0), "previous": int(row.previous or 0)}


def _active_users(db: Session) -> dict:
    """Distinct Benutzer mit erfolgreicher Anmeldung in 30 T (audit_log user.login, 730 T Historie)."""

    def compute() -> dict:
        row = db.execute(
            text(
                "SELECT count(DISTINCT actor_user_id) FILTER (WHERE created_at > now() - interval '30 days') AS current, "
                "count(DISTINCT actor_user_id) FILTER (WHERE created_at <= now() - interval '30 days') AS previous "
                "FROM audit_log WHERE action = 'user.login' AND created_at > now() - interval '60 days' AND actor_user_id IS NOT NULL"
            )
        ).one()
        return {"value": int(row.current or 0), "previous": int(row.previous or 0)}

    return _cached("admin-overview:active-users", ACTIVE_USERS_TTL_SECONDS, compute)


def _storage_hot_tenants(db: Session) -> int:
    from app.services.storage_service import StorageService

    totals = StorageService().total_bytes_by_tenant(db)
    hot = 0
    for tenant_id, quota in db.execute(text("SELECT id, storage_quota_bytes FROM tenant WHERE storage_quota_bytes > 0")):
        if totals.get(tenant_id, 0) >= quota * STORAGE_WARN_RATIO:
            hot += 1
    return hot


def _todos(db: Session, *, owner: bool, jobs_problem: int | None, backup_overall: str | None, today: date) -> list[dict]:
    from app.services.cashflow_service import PAYMENT_TERM_DAYS

    todos: list[dict] = []

    def add(key: str, count: int | None, href: str, severity: str = "warning", **params: Any) -> None:
        if count:
            todos.append({"key": key, "count": count, "href": href, "severity": severity, "params": params})

    add("verifications", _scalar(db, "SELECT count(*) FROM identity_verification_request WHERE status = 'pending'"), "/admin/verifications", "info")
    add(
        "rebooking",
        _scalar(
            db,
            "SELECT count(*) FROM tenant t WHERE t.plan_code IN (SELECT code FROM plan WHERE NOT is_bookable) "
            "OR t.id IN (SELECT tsp.tenant_id FROM tenant_storage_package tsp JOIN storage_package sp ON sp.code = tsp.package_code WHERE NOT sp.is_bookable)",
        ),
        "/admin/plans",
        "info",
    )
    add(
        "overdueCharges",
        _scalar(db, "SELECT count(*) FROM tenant_charge WHERE status = 'open' AND period_start < :limit", {"limit": today - timedelta(days=PAYMENT_TERM_DAYS)}),
        "/admin/cashflow",
    )
    add("unhealthyDomains", _scalar(db, "SELECT count(*) FROM tenant_domain WHERE status = 'verified' AND NOT is_healthy"), "/admin/domains")
    add("storageHot", _storage_hot_tenants(db), "/admin/tenants?storage_min_ratio=0.85&sort=storage&dir=desc")
    if owner:
        add("jobs", jobs_problem, "/admin/jobs", "critical" if jobs_problem and jobs_problem > 2 else "warning")
        if backup_overall in ("warning", "critical"):
            todos.append({"key": "backups", "count": 1, "href": "/admin/backups", "severity": backup_overall, "params": {}})
    return todos


def _feed(db: Session) -> list[dict]:
    """Letzte Admin-/Backup-Aktionen und Systemereignisse. Akteur nur als Admin-Anzeigename (aus
    platform_admin), nie die E-Mail eines Mandantenbenutzers; keine Details-JSONs."""
    rows = db.execute(
        text(
            "SELECT a.id, a.action, a.created_at, a.outcome, a.entity_type, t.public_id AS tenant_public_id, t.name AS tenant_name, "
            "pa.display_name AS admin_name "
            "FROM audit_log a "
            "LEFT JOIN tenant t ON t.id = a.tenant_id "
            "LEFT JOIN platform_admin pa ON lower(pa.email) = lower(a.actor_email) "
            "WHERE (a.action LIKE 'admin.%' OR a.action LIKE 'backup.%') "
            "ORDER BY a.created_at DESC LIMIT :limit"
        ),
        {"limit": FEED_LIMIT},
    ).mappings()
    items: list[dict] = []
    for row in rows:
        href = f"/admin/security/audit?id={row['id']}"
        if row["tenant_public_id"] and row["action"].startswith("admin.tenant"):
            href = f"/admin/tenants/{row['tenant_public_id']}"
        elif row["action"].startswith("backup."):
            href = "/admin/backups"
        items.append({
            "id": f"audit:{row['id']}", "kind": "admin", "at": row["created_at"], "action": row["action"], "outcome": row["outcome"],
            "severity": "warning" if row["outcome"] == "failure" else "info",
            "tenant": row["tenant_name"], "actor": row["admin_name"], "subject": None, "href": href,
        })
    for row in db.execute(
        text("SELECT id, kind, subject, reason, severity, created_at FROM system_health_event ORDER BY created_at DESC LIMIT :limit"),
        {"limit": FEED_LIMIT},
    ).mappings():
        subject = row["subject"] or ""
        if subject.startswith("job:"):
            href = f"/admin/jobs?job={subject[4:]}"
        else:
            href = f"/admin/system?check={subject}"
        items.append({
            "id": f"event:{row['id']}", "kind": "system", "at": row["created_at"], "action": row["kind"], "outcome": row["reason"],
            "severity": row["severity"], "tenant": None, "actor": None, "subject": subject, "href": href,
        })
    items.sort(key=lambda item: item["at"], reverse=True)
    return items[:FEED_LIMIT]


def _mrr(db: Session, today: date) -> dict:
    from app.services import cashflow_service

    overview = cashflow_service.overview(db, today.year, today=today)
    month_index = today.month - 1
    previous = overview.months[month_index - 1].income_rp if month_index > 0 else None
    return {
        "value_rp": overview.run_rate.income_rp,
        "paying_tenants": overview.run_rate.paying_tenants,
        "previous_month_income_rp": previous,
        "overdue_count": overview.overdue.count,
    }


def build_overview(db: Session, *, owner: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    from app.services.cashflow_service import today_local

    today = today_local()
    tenants_total = _scalar(db, "SELECT count(*) FROM tenant")
    tenants_new = _scalar(db, "SELECT count(*) FROM tenant WHERE created_at > now() - interval '30 days'")
    status = None
    errors = None
    login_failures = None
    feed = None
    jobs_problem = None
    backup_overall = None
    if owner:
        from app.services import backup_admin_service
        from app.services.admin_job_status_service import AdminJobStatusService

        status = _system_status(db, now)
        errors = _count_with_previous(db, "system_error_log", "created_at", "TRUE", 24)
        login_failures = _count_with_previous(db, "auth_event", "ts", _LOGIN_FAILURE_SQL, 24)
        feed = _feed(db)
        jobs = AdminJobStatusService().get_overview(db, now=now)
        jobs_problem = sum(1 for job in jobs.items if job.state in ("failing", "overdue"))
        backup_overall, _ = backup_admin_service.evaluate(db, now)
    mrr = _mrr(db, today)
    return {
        "generated_at": now,
        "role": "owner" if owner else "support",
        "status": status,
        "kpis": {
            "tenants": {"value": tenants_total, "new_30d": tenants_new},
            "active_users_30d": _active_users(db),  # bewusst A: reine Anzahl ohne Personenbezug (Security-Review N1)
            "mrr": mrr,
            "errors_24h": errors,
            "login_failures_24h": login_failures,
        },
        "todos": _todos(db, owner=owner, jobs_problem=jobs_problem, backup_overall=backup_overall, today=today),
        "feed": feed,
    }


def overview(db: Session, *, owner: bool) -> dict:
    return _cached(f"admin-overview:v1:{'owner' if owner else 'support'}", OVERVIEW_TTL_SECONDS, lambda: build_overview(db, owner=owner))


def series(db: Session, *, kind: Literal["logins", "errors"], range_: str) -> dict:
    hours, bucket_hours = RANGES[range_]
    bucket_seconds = bucket_hours * 3600
    if kind == "logins":
        sql = (
            "SELECT to_timestamp(floor(extract(epoch FROM ts) / :bucket) * :bucket) AS bucket, "
            f"count(*) FILTER (WHERE {_LOGIN_SUCCESS_SQL}) AS success, "  # sql-ok: feste Konstanten
            f"count(*) FILTER (WHERE {_LOGIN_FAILURE_SQL}) AS failure "
            "FROM auth_event WHERE ts > now() - make_interval(hours => :hours) GROUP BY 1 ORDER BY 1"
        )
    else:
        sql = (
            "SELECT to_timestamp(floor(extract(epoch FROM created_at) / :bucket) * :bucket) AS bucket, count(*) AS errors "
            "FROM system_error_log WHERE created_at > now() - make_interval(hours => :hours) GROUP BY 1 ORDER BY 1"
        )
    rows = [dict(row) for row in db.execute(text(sql), {"bucket": bucket_seconds, "hours": hours}).mappings()]
    by_bucket = {int(row["bucket"].timestamp()): row for row in rows}
    now = datetime.now(UTC)
    start = int((now - timedelta(hours=hours)).timestamp()) // bucket_seconds * bucket_seconds
    end = int(now.timestamp()) // bucket_seconds * bucket_seconds
    points: list[dict] = []
    for epoch in range(start, end + 1, bucket_seconds):
        row = by_bucket.get(epoch, {})
        point: dict[str, Any] = {"bucket": datetime.fromtimestamp(epoch, UTC)}
        if kind == "logins":
            point.update(success=int(row.get("success") or 0), failure=int(row.get("failure") or 0))
        else:
            point.update(errors=int(row.get("errors") or 0))
        points.append(point)
    top_types: list[dict] = []
    if kind == "errors":
        top_types = [
            {"error_type": row.error_type, "count": int(row.count)}
            for row in db.execute(
                text(
                    "SELECT error_type, count(*) AS count FROM system_error_log WHERE created_at > now() - make_interval(hours => :hours) "
                    "GROUP BY error_type ORDER BY count(*) DESC LIMIT 3"
                ),
                {"hours": hours},
            )
        ]
    return {"kind": kind, "range": range_, "bucket_hours": bucket_hours, "points": points, "top_types": top_types}


def _backup_status(db: Session) -> str | None:
    """Status-Punkt am Navigationseintrag Backups (für alle Admins, die Seite lesen dürfen):
    kritisch/Warnung aus derselben Bewertung wie /admin/backups, sonst «läuft» bei offenem Auftrag."""
    from app.models import BackupJob, BackupRestoreJob
    from app.services import backup_admin_service

    if not backup_admin_service.backup_enabled():
        return None
    overall, _ = backup_admin_service.evaluate(db)
    if overall in ("critical", "warning"):
        return overall
    running = db.scalar(select(BackupJob.id).where(BackupJob.state.in_(backup_admin_service.OPEN_JOB_STATES)).limit(1)) or \
        db.scalar(select(BackupRestoreJob.id).where(BackupRestoreJob.state.in_(backup_admin_service.OPEN_RESTORE_STATES)).limit(1))
    return "running" if running is not None else None


def nav_counts(db: Session, *, owner: bool) -> dict:
    def compute() -> dict:
        result: dict[str, int | None] = {
            "tenants": _scalar(db, "SELECT count(*) FROM tenant"),
            "verifications_open": _scalar(db, "SELECT count(*) FROM identity_verification_request WHERE status = 'pending'"),
            "security_alerts": None,
            "operations_problems": None,
            "backup_status": _backup_status(db),
        }
        if owner:
            from app.services import system_alert_service, system_health_service

            now = datetime.now(UTC)
            problems = system_alert_service.current_problems(db, system_health_service.load_snapshot(), now=now)
            # 1.6: Vorfälle im Status «Neu» (noch niemand hat übernommen) statt nicht quittierter Warnungen
            from app.auth_security import incidents

            result["security_alerts"] = incidents.open_new_count(db)
            result["operations_problems"] = sum(1 for problem in problems if problem.source != "auth")
        return result

    return _cached(f"admin-nav-counts:v2:{'owner' if owner else 'support'}", NAV_COUNTS_TTL_SECONDS, compute)


def invalidate_nav_counts() -> None:
    """Nach einer Änderung an einem Vorfall: Zähler sofort neu rechnen statt bis zu 60 s alt zeigen."""
    try:
        get_redis_sync().delete("admin-nav-counts:v2:owner", "admin-nav-counts:v2:support")
    except Exception:  # noqa: BLE001 - Cache ist optional
        _logger.warning("Admin-Übersicht: Zähler-Cache nicht löschbar", exc_info=True)


# ── Suche (Ctrl+K) ─────────────────────────────────────────────────────────


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


_JOB_OR_CHECK = re.compile(r"^[a-z0-9_.:-]+$")


def search(db: Session, q: str, *, owner: bool) -> tuple[list[dict], bool]:
    """Liefert (Gruppen, users_abgefragt). Höchstens SEARCH_GROUP_LIMIT Treffer pro Gruppe."""
    term = q.strip()
    groups: list[dict] = []
    contains = contains_pattern(term)

    tenants = db.execute(
        text(
            "SELECT public_id, name, plan_code FROM tenant WHERE name ILIKE :pattern ESCAPE :esc "
            "ORDER BY (lower(name) = lower(:term)) DESC, (name ILIKE :prefix ESCAPE :esc) DESC, name LIMIT :limit"
        ),
        {"pattern": contains, "prefix": prefix_pattern(term), "term": term, "esc": LIKE_ESCAPE, "limit": SEARCH_GROUP_LIMIT},
    ).all()
    groups.append({"group": "tenants", "items": [
        {"id": str(row.public_id), "label": row.name, "sublabel": row.plan_code, "href": f"/admin/tenants/{row.public_id}"} for row in tenants
    ]})

    domains = db.execute(
        text(
            "SELECT d.public_id, d.domain, d.status, t.public_id AS tenant_public_id, t.name AS tenant_name "
            "FROM tenant_domain d JOIN tenant t ON t.id = d.tenant_id WHERE d.domain ILIKE :pattern ESCAPE :esc ORDER BY d.domain LIMIT :limit"
        ),
        {"pattern": contains, "esc": LIKE_ESCAPE, "limit": SEARCH_GROUP_LIMIT},
    ).all()
    groups.append({"group": "domains", "items": [
        {"id": str(row.public_id), "label": row.domain, "sublabel": row.tenant_name, "href": f"/admin/tenants/{row.tenant_public_id}/domains"}
        for row in domains
    ]})

    users_queried = False
    if owner and len(term) >= 3:
        users_queried = True
        users = db.execute(
            text(
                "SELECT u.public_id, coalesce(nullif(u.display_name, ''), nullif(trim(concat_ws(' ', u.first_name, u.last_name)), ''), u.name) AS label, "
                "u.email, t.public_id AS tenant_public_id, t.name AS tenant_name "
                "FROM app_user u JOIN tenant t ON t.id = u.tenant_id "
                "WHERE u.email ILIKE :pattern ESCAPE :esc OR u.display_name ILIKE :pattern ESCAPE :esc "
                "OR concat_ws(' ', u.first_name, u.last_name) ILIKE :pattern ESCAPE :esc "
                "ORDER BY t.name, label LIMIT :limit"
            ),
            {"pattern": contains, "esc": LIKE_ESCAPE, "limit": SEARCH_GROUP_LIMIT},
        ).all()
        groups.append({"group": "users", "items": [
            {
                "id": str(row.public_id),
                "label": row.label or mask_email(row.email) or "",
                "sublabel": " · ".join(part for part in (row.tenant_name, mask_email(row.email)) if part),
                "href": f"/admin/tenants/{row.tenant_public_id}/users",
            }
            for row in users
        ]})

    if owner:
        lowered = term.lower()
        if _JOB_OR_CHECK.match(lowered):
            job_names = sorted({definition.name for definition in JOB_DEFINITIONS})
            jobs = [name for name in job_names if name.startswith(lowered)] + [name for name in job_names if lowered in name and not name.startswith(lowered)]
            groups.append({"group": "jobs", "items": [
                {"id": name, "label": name, "sublabel": None, "href": f"/admin/jobs?job={name}"} for name in jobs[:SEARCH_GROUP_LIMIT]
            ]})
            from app.services import system_health_service

            snapshot = system_health_service.load_snapshot()
            check_keys = sorted({check.key for check in snapshot.checks}) if snapshot else []
            checks = [key for key in check_keys if key.startswith(lowered.removeprefix("check:"))]
            groups.append({"group": "checks", "items": [
                {"id": key, "label": key, "sublabel": None, "href": f"/admin/system?check=check:{key}"} for key in checks[:SEARCH_GROUP_LIMIT]
            ]})
            # Audit nur über Aktions-Code-Präfix (kein Freitext in Details) oder numerische ID.
            if lowered.isdigit():
                audit_rows = db.execute(text("SELECT id, action, created_at FROM audit_log WHERE id = :id"), {"id": int(lowered)}).all()
            elif "." in lowered or lowered.startswith(("admin", "user", "backup", "tenant")):
                audit_rows = db.execute(
                    text("SELECT id, action, created_at FROM audit_log WHERE action LIKE :prefix ESCAPE :esc ORDER BY created_at DESC LIMIT :limit"),
                    {"prefix": prefix_pattern(lowered), "esc": LIKE_ESCAPE, "limit": SEARCH_GROUP_LIMIT},
                ).all()
            else:
                audit_rows = []
            groups.append({"group": "audit", "items": [
                {"id": str(row.id), "label": row.action, "sublabel": row.created_at.isoformat(), "href": f"/admin/security/audit?id={row.id}"}
                for row in audit_rows
            ]})
    return [group for group in groups if group["items"]], users_queried
