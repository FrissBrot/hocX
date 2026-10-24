"""Sammelt den Systemzustand für /admin/system: Container (über den docker-socket-proxy) und
Prüfungen der Dienste, von denen hocX abhängt (Postgres, Redis, ClamAV, Speicherplatz, ...).

Läuft im Loop system_monitor (main.py) alle settings.system_monitor_interval_seconds. Der
Snapshot liegt in Redis, damit jeder uvicorn-Worker die Seite ohne eigene Docker-Abfragen
ausliefern kann. Die Schwellwerte hier bestimmen zugleich, was system_alert_service als
Problem meldet - eine Stelle, damit Seite und ntfy nie unterschiedlich urteilen."""

from __future__ import annotations

import json
import logging
import shutil
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pyclamd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import docker_api
from app.core.config import settings
from app.core.error_log import record_system_error
from app.core.redis_client import get_redis_sync
from app.models import StoredFile, SystemErrorLog, SystemHealthEvent
from app.models.document_entities import DocumentJob
from app.models.entities import PhotoAnalysisJob
from app.schemas.admin import ContainerStatusRead, HealthCheckRead, HealthStatus, OverloadTenantRead, SystemHealthSnapshot

_logger = logging.getLogger(__name__)

SNAPSHOT_REDIS_KEY = "hocx:system_monitor:snapshot"
# Ab hier gilt der Snapshot als veraltet (Loop hängt oder läuft nicht) - 6 verpasste Durchläufe.
SNAPSHOT_MAX_AGE = timedelta(minutes=3)

POSTGRES_SLOW_MS = 500
CONNECTIONS_WARNING_RATIO = 0.8
CONNECTIONS_CRITICAL_RATIO = 0.95
REDIS_MEMORY_WARNING_RATIO = 0.9
CLAMAV_SIGNATURES_WARNING_HOURS = 48
CLAMAV_SIGNATURES_CRITICAL_HOURS = 7 * 24
STORAGE_FREE_WARNING_PERCENT = 15
STORAGE_FREE_CRITICAL_PERCENT = 5
ERRORS_PER_HOUR_WARNING = 20
ERRORS_PER_HOUR_CRITICAL = 100
SCAN_BACKLOG_MIN_AGE = timedelta(hours=1)
# Verwaiste Dateien erst nach einem Tag melden (Uploads committen Zeile und Bezug nicht immer zusammen).
ORPHAN_MIN_AGE = timedelta(hours=24)
PHOTO_QUEUE_WARNING_AGE = timedelta(hours=6)
# Dokumentverarbeitung (document-worker): fällige Aufträge, die so lange warten, bzw. Aufträge,
# die in diesem Zeitraum endgültig gescheitert sind (nach max_attempts, «Erneut verarbeiten»).
DOCUMENT_QUEUE_WARNING_AGE = timedelta(minutes=30)
DOCUMENT_FAILED_WINDOW = timedelta(hours=24)
CONTAINER_MEMORY_WARNING_RATIO = 0.9
_HEALTH_OUTPUT_MAX_LENGTH = 500

_STATUS_RANK: dict[HealthStatus, int] = {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}


def _worst(*statuses: HealthStatus) -> HealthStatus:
    return max(statuses, key=lambda status: _STATUS_RANK[status])


def _parse_docker_time(value: str | None) -> datetime | None:
    # Docker liefert RFC 3339 mit Nanosekunden ("2026-10-11T12:00:00.123456789Z"); "0001-..."
    # steht für "nie".
    if not value or value.startswith("0001-"):
        return None
    head, _, fraction = value.rstrip("Z").partition(".")
    try:
        parsed = datetime.fromisoformat(head).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if fraction:
        parsed += timedelta(microseconds=int(fraction[:6].ljust(6, "0")))
    return parsed


# ── Container ─────────────────────────────────────────────────────────────────────────────


def _cpu_percent(stats: dict | None) -> float | None:
    if not stats:
        return None
    cpu, precpu = stats.get("cpu_stats") or {}, stats.get("precpu_stats") or {}
    try:
        cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
        system_delta = cpu["system_cpu_usage"] - precpu["system_cpu_usage"]
    except (KeyError, TypeError):
        return None
    online_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
    if system_delta <= 0 or cpu_delta < 0:
        return None
    return round(cpu_delta / system_delta * online_cpus * 100, 1)


def _memory(stats: dict | None) -> tuple[int | None, int | None]:
    memory = (stats or {}).get("memory_stats") or {}
    usage = memory.get("usage")
    if usage is None:
        return None, None
    # Wie `docker stats`: Page-Cache abziehen, sonst wirkt jeder Container mit Dateizugriffen voll.
    cache = (memory.get("stats") or {}).get("inactive_file", 0)
    return max(0, usage - cache), memory.get("limit")


def image_tag(image: str | None) -> str | None:
    """"ghcr.io/x/hocx-backend:1.2.0" -> "1.2.0"; per Digest gepinnte Images ("clamav/clamav@sha256:...")
    und Images ohne Tag haben keine lesbare Version."""
    if not image:
        return None
    name = image.split("@", 1)[0].rsplit("/", 1)[-1]
    return name.rsplit(":", 1)[1] if ":" in name else None


def evaluate_container(container: ContainerStatusRead, *, one_shot: bool = False) -> ContainerStatusRead:
    reasons: list[str] = []
    status: HealthStatus = "ok"
    # Einmal-Dienste (restart: "no", z. B. storage-init) laufen beim Start durch und beenden sich;
    # sauber mit Exit 0 beendet ist ihr Sollzustand, nur ein Fehler-Exit ist ein Problem.
    finished_cleanly = one_shot and container.state == "exited" and container.exit_code == 0
    if container.state != "running" and not finished_cleanly:
        reasons.append("not_running")
        status = "critical"
    if container.health == "unhealthy":
        reasons.append("unhealthy")
        status = "critical"
    elif container.health == "starting":
        reasons.append("starting")
        status = _worst(status, "warning")
    if container.oom_killed:
        reasons.append("oom_killed")
        status = "critical"
    if container.memory_bytes and container.memory_limit_bytes and container.memory_bytes / container.memory_limit_bytes >= CONTAINER_MEMORY_WARNING_RATIO:
        reasons.append("memory_high")
        status = _worst(status, "warning")
    return container.model_copy(update={"status": status, "reasons": reasons})


def _container_from_docker(summary: dict, details: dict, stats: dict | None) -> ContainerStatusRead:
    labels = details.get("Config", {}).get("Labels") or {}
    state = details.get("State") or {}
    health = state.get("Health") or {}
    health_log = health.get("Log") or []
    image = details.get("Config", {}).get("Image") or summary.get("Image")
    memory_bytes, memory_limit = _memory(stats)
    name = (summary.get("Names") or [details.get("Name", "")])[0].lstrip("/")
    restart_policy = ((details.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name")
    return evaluate_container(
        ContainerStatusRead(
            name=name,
            service=labels.get("com.docker.compose.service") or name,
            container_id=details.get("Id", "")[:12],
            state=state.get("Status", "unknown"),
            health=health.get("Status"),
            health_output=(health_log[-1].get("Output") or "").strip()[:_HEALTH_OUTPUT_MAX_LENGTH] if health_log else None,
            restart_count=details.get("RestartCount", 0),
            started_at=_parse_docker_time(state.get("StartedAt")),
            exit_code=state.get("ExitCode") if state.get("Status") != "running" else None,
            oom_killed=bool(state.get("OOMKilled")),
            image=image,
            version=labels.get("org.opencontainers.image.version") or image_tag(image),
            cpu_percent=_cpu_percent(stats),
            memory_bytes=memory_bytes,
            memory_limit_bytes=memory_limit,
            status="ok",
        ),
        one_shot=restart_policy in ("", "no"),
    )


def collect_containers() -> tuple[str | None, list[ContainerStatusRead]]:
    project = docker_api.own_compose_project()
    summaries = [
        summary
        for summary in docker_api.list_containers(project)
        # `docker compose run`-Container (Migrationen, Tests, Skripte) sind keine Dienste.
        if (summary.get("Labels") or {}).get("com.docker.compose.oneoff") != "True"
    ]
    details = {summary["Id"]: docker_api.inspect_container(summary["Id"]) for summary in summaries}
    stats = docker_api.container_stats([summary["Id"] for summary in summaries if summary.get("State") == "running"])
    containers = [_container_from_docker(summary, details[summary["Id"]], stats.get(summary["Id"])) for summary in summaries]
    return project, sorted(containers, key=lambda container: container.service)


# Service-Name des lokalen S3 (Garage) in den Compose-Dateien; scripts/storage_controller.sh stoppt
# ihn, wenn der Speicher woanders liegt (storage_local_s3_decision, Migration 0113).
LOCAL_S3_SERVICE = "local-s3"


def local_s3_decision(db: Session) -> tuple[bool, str]:
    needed, reason = db.execute(text("SELECT needed, reason FROM storage_local_s3_decision()")).one()
    return bool(needed), str(reason)


def mark_intentionally_stopped_local_s3(db: Session, containers: list[ContainerStatusRead]) -> list[ContainerStatusRead]:
    """Ein vom Storage-Controller gestopptes lokales S3 ist der Sollzustand, kein Ausfall: ohne diese
    Ausnahme meldete der Systemstatus (und ntfy) den Container als "läuft nicht", sobald die Dateien
    bei einem externen Anbieter liegen."""
    if not any(c.service == LOCAL_S3_SERVICE and c.state != "running" for c in containers):
        return containers
    try:
        needed, _reason = local_s3_decision(db)
    except Exception:
        # Im Zweifel als "benötigt" behandeln: lieber ein Alarm zu viel als ein verschwiegener Ausfall.
        db.rollback()
        _logger.warning("Bedarf des lokalen S3 nicht ermittelbar", exc_info=True)
        return containers
    if needed:
        return containers
    return [
        c.model_copy(update={"status": "ok", "reasons": ["not_needed"]})
        if c.service == LOCAL_S3_SERVICE and c.state != "running"
        else c
        for c in containers
    ]


# ── Dienst-Prüfungen ──────────────────────────────────────────────────────────────────────


def _check_postgres(db: Session) -> HealthCheckRead:
    started = time.monotonic()
    db.execute(text("SELECT 1"))
    latency_ms = round((time.monotonic() - started) * 1000)
    row = db.execute(
        text(
            "SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS connections, "
            "current_setting('max_connections')::int AS max_connections, "
            "pg_database_size(current_database()) AS size_bytes"
        )
    ).one()
    ratio = row.connections / row.max_connections if row.max_connections else 0
    status: HealthStatus = "ok"
    if latency_ms > POSTGRES_SLOW_MS or ratio >= CONNECTIONS_WARNING_RATIO:
        status = "warning"
    if ratio >= CONNECTIONS_CRITICAL_RATIO:
        status = "critical"
    return HealthCheckRead(
        key="postgres",
        status=status,
        params={"latencyMs": latency_ms, "connections": row.connections, "maxConnections": row.max_connections, "sizeMb": round(row.size_bytes / 1024 / 1024)},
    )


def _check_redis() -> HealthCheckRead:
    client = get_redis_sync()
    started = time.monotonic()
    client.ping()
    latency_ms = round((time.monotonic() - started) * 1000)
    memory = client.info("memory")
    used, maximum = memory.get("used_memory", 0), memory.get("maxmemory", 0)
    status: HealthStatus = "warning" if maximum and used / maximum >= REDIS_MEMORY_WARNING_RATIO else "ok"
    return HealthCheckRead(key="redis", status=status, params={"latencyMs": latency_ms, "usedMb": round(used / 1024 / 1024, 1)})


def parse_clamav_version(version: str) -> tuple[str | None, datetime | None]:
    """"ClamAV 1.4.3/27790/Sat Oct 11 08:23:03 2026" -> ("27790", Zeitpunkt der Signaturen).
    clamd gibt die Zeit ohne Zone aus; die offiziellen Images laufen in UTC."""
    parts = version.strip().split("/")
    if len(parts) < 3:
        return None, None
    try:
        signature_time = datetime.strptime(" ".join(parts[2].split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        signature_time = None
    return parts[1], signature_time


def _check_clamav(now: datetime) -> list[HealthCheckRead]:
    clamd = pyclamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=5)
    started = time.monotonic()
    if not clamd.ping():
        raise ConnectionError("clamd antwortet nicht auf PING")
    latency_ms = round((time.monotonic() - started) * 1000)
    version = clamd.version() or ""
    signature_version, signature_time = parse_clamav_version(version)
    checks = [HealthCheckRead(key="clamav", status="ok", params={"latencyMs": latency_ms, "version": version.split("/")[0].strip()})]
    if signature_time is None:
        checks.append(HealthCheckRead(key="clamav_signatures", status="unknown", error=version or None))
    else:
        age_hours = max(0, round((now - signature_time).total_seconds() / 3600))
        status: HealthStatus = "ok"
        if age_hours >= CLAMAV_SIGNATURES_WARNING_HOURS:
            status = "warning"
        if age_hours >= CLAMAV_SIGNATURES_CRITICAL_HOURS:
            status = "critical"
        checks.append(HealthCheckRead(key="clamav_signatures", status=status, params={"ageHours": age_hours, "signatureVersion": signature_version}))
    return checks


def _check_storage() -> HealthCheckRead:
    usage = shutil.disk_usage(settings.storage_root)
    free_percent = round(usage.free / usage.total * 100, 1) if usage.total else 0
    status: HealthStatus = "ok"
    if free_percent < STORAGE_FREE_WARNING_PERCENT:
        status = "warning"
    if free_percent < STORAGE_FREE_CRITICAL_PERCENT:
        status = "critical"
    gb = 1024**3
    return HealthCheckRead(
        key="storage",
        status=status,
        params={"freePercent": free_percent, "freeGb": round(usage.free / gb, 1), "totalGb": round(usage.total / gb, 1)},
    )


def _check_object_storage() -> HealthCheckRead:
    """Aktiver Objektspeicher erreichbar? HEAD auf einen nie existierenden Key: "nicht gefunden"
    heisst erreichbar, ein Verbindungs-/Rechtefehler ist kritisch (Uploads und Downloads stehen)."""
    from app.core.storage import get_object_store

    store = get_object_store()
    state = store.active_state(force=True)
    started = time.monotonic()
    store.active_backend().head("main", "_hocx-health/probe")
    return HealthCheckRead(
        key="object_storage",
        status="ok",
        params={"generation": state.config.generation, "latencyMs": round((time.monotonic() - started) * 1000), "fenced": int(state.fenced)},
    )


def _check_local_s3(db: Session) -> list[HealthCheckRead]:
    """Lokales S3 (Garage): wird es gebraucht und warum, und was liegt dort. Die Zahlen stammen aus
    der Datenbank (Objektverzeichnis bzw. Generationen), nicht aus Garage selbst - dessen Admin-API
    ist bewusst nur im Garage-Container erreichbar (infra/garage/garage.toml). Ohne lokales Profil
    (nie eingerichtet) entfällt die Prüfung."""
    needed, reason = local_s3_decision(db)
    if reason == "no_local_profile":
        return []
    active = db.execute(
        text(
            "SELECT s.active_generation FROM storage_state s JOIN storage_profile p ON p.id = s.active_profile_id "
            "WHERE p.provider = 'garage_local'"
        )
    ).scalar()
    if active is not None:
        objects, size = db.execute(
            text(
                "SELECT count(*), COALESCE(sum(size_bytes), 0) FROM storage_object "
                "WHERE generation = :generation AND status = 'active' AND NOT purge_pending"
            ),
            {"generation": active},
        ).one()
    else:
        # Nicht mehr aktiv: was eine noch nicht bereinigte Generation (Rückfallfrist) dort belegt.
        objects, size = db.execute(
            text(
                "SELECT COALESCE(sum(g.object_count), 0), COALESCE(sum(g.total_bytes), 0) FROM storage_generation g "
                "JOIN storage_profile p ON p.id = g.profile_id WHERE p.provider = 'garage_local' AND g.purged_at IS NULL"
            )
        ).one()
    return [
        HealthCheckRead(
            key="local_s3",
            status="ok",
            params={"needed": int(needed), "reason": reason, "objects": int(objects), "gb": round(int(size) / 1024**3, 2)},
        )
    ]


def _check_storage_migration(db: Session, now: datetime) -> HealthCheckRead:
    """Offene Storage-Migration: hängt der Worker, braucht sie einen Eingriff oder ist ein
    Rollback nötig?"""
    from app.models import StorageMigration, StorageMigrationObject

    migration = db.scalars(select(StorageMigration).where(StorageMigration.state.notin_(("completed", "failed", "cancelled"))).limit(1)).first()
    if migration is None:
        return HealthCheckRead(key="storage_migration", status="ok", params={"verified": 0, "total": 0, "dead": 0})
    dead = db.scalar(select(func.count()).select_from(StorageMigrationObject).where(
        StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "dead")) or 0
    status: HealthStatus = "ok"
    waiting = migration.state in ("awaiting_confirmation", "paused")
    heartbeat_age = (now - migration.heartbeat_at).total_seconds() if migration.heartbeat_at else None
    if dead or migration.state == "retrying" or (not waiting and heartbeat_age is not None and heartbeat_age > 600):
        status = "warning"
    if migration.state == "rollback_required":
        status = "critical"
    return HealthCheckRead(key="storage_migration", status=status, params={"verified": migration.verified_objects, "total": migration.total_objects, "dead": dead})


_BACKUP_CHECK_CODES = {
    "backup": {"disabled", "configuration", "never_succeeded", "overdue", "schedule_disabled"},
    "backup_repository": {"repository_unreachable", "repository_id_mismatch", "repository_not_encrypted", "passphrase_wrong",
                          "host_key_mismatch", "capacity_low", "staging_low"},
    # Fehlgeschlagene Prüfungen/Restore-Tests melden die Job-Läufe (backup_verify,
    # backup_restore_test) - hier nur, wenn sie zu lange ausbleiben.
    "backup_verification": {"verify_overdue", "restore_test_overdue"},
}


def _check_backup(db: Session, now: datetime) -> list[HealthCheckRead]:
    """Backup-System (docs-site/docs/technik/backup/): Frische der Sicherungen, Repository auf der
    Storage Box und regelmässige Prüfungen. Bewertung aus backup_admin_service.evaluate - dieselbe
    wie im Admin-Portal."""
    from app.models import BackupSet
    from app.services import backup_admin_service

    overall, problems = backup_admin_service.evaluate(db, now)
    row = backup_admin_service.settings_row(db)
    repo = dict(row.repository_status or {})
    last_ok = db.scalar(select(func.max(BackupSet.snapshot_at)).where(BackupSet.state == "completed"))
    points = db.scalar(select(func.count()).select_from(BackupSet).where(BackupSet.state.in_(("completed", "partial")))) or 0
    verified = db.scalar(select(func.max(BackupSet.verified_at)).where(BackupSet.verify_state == "verified"))
    tested = db.scalar(select(func.max(BackupSet.restore_tested_at)).where(BackupSet.restore_test_state == "passed"))
    used = repo.get("used_percent")

    def status_for(key: str) -> tuple[HealthStatus, str | None]:
        relevant = [p for p in problems if p.code in _BACKUP_CHECK_CODES[key]]
        if not relevant:
            return ("unknown" if overall == "disabled" else "ok"), None
        worst: HealthStatus = "critical" if any(p.severity == "critical" for p in relevant) else "warning"
        return worst, relevant[0].code

    checks: list[HealthCheckRead] = []
    backup_status, backup_code = status_for("backup")
    checks.append(HealthCheckRead(key="backup", status=backup_status, params={
        "state": "disabled" if overall == "disabled" else ("never" if last_ok is None else "ok"),
        "hours": int((now - last_ok).total_seconds() // 3600) if last_ok else 0, "points": int(points), "code": backup_code,
    }))
    repo_status, repo_code = status_for("backup_repository")
    checks.append(HealthCheckRead(key="backup_repository", status=repo_status if overall != "disabled" else "unknown", params={
        "reachable": "yes" if repo.get("ok") else "no", "quota": "yes" if isinstance(used, (int, float)) else "no",
        "usedPercent": used if isinstance(used, (int, float)) else 0, "code": repo_code or repo.get("error_code"),
    }))
    verify_status, verify_code = status_for("backup_verification")
    checks.append(HealthCheckRead(key="backup_verification", status=verify_status if overall != "disabled" else "unknown", params={
        "verified": "yes" if verified else "no", "verifyDays": int((now - verified).days) if verified else 0,
        "tested": "yes" if tested else "no", "testDays": int((now - tested).days) if tested else 0, "code": verify_code,
    }))
    return checks


def _check_error_rate(db: Session) -> HealthCheckRead:
    last_hour = db.scalar(select(func.count()).select_from(SystemErrorLog).where(SystemErrorLog.created_at >= func.now() - timedelta(hours=1))) or 0
    last_day = db.scalar(select(func.count()).select_from(SystemErrorLog).where(SystemErrorLog.created_at >= func.now() - timedelta(days=1))) or 0
    status: HealthStatus = "ok"
    if last_hour >= ERRORS_PER_HOUR_WARNING:
        status = "warning"
    if last_hour >= ERRORS_PER_HOUR_CRITICAL:
        status = "critical"
    return HealthCheckRead(key="error_rate", status=status, params={"lastHour": last_hour, "lastDay": last_day})


def _check_scan_backlog(db: Session) -> HealthCheckRead:
    count = db.scalar(
        select(func.count())
        .select_from(StoredFile)
        .where(StoredFile.scan_status == "pending", StoredFile.created_at < func.now() - SCAN_BACKLOG_MIN_AGE)
    ) or 0
    return HealthCheckRead(key="scan_backlog", status="warning" if count else "ok", params={"count": count})


_EXPORT_ACTIONS = ("admin.tenant_exported", "tenant.exported", "personal_data.exported")
_ADMIN_CHANGE_ACTIONS = ("admin.admin_created", "admin.user_mfa_factor_deleted", "user.mfa_factor_deleted")


def _check_security(db: Session) -> HealthCheckRead:
    """Auffällige Ereignisse im Audit-Log (Datenschutz-Audit PRIV-022): viele Fehlversuche beim
    Anmelden (gesamt und je Konto, 15 min), mehrere Exporte in einer Stunde, Restores und
    Änderungen an Admin-Konten/MFA (24 h), optional jede Plattform-Anmeldung (1 h)."""
    from sqlalchemy import text

    failure_window = (
        "outcome = 'failure' AND action IN ('user.login_failed', 'admin.login_failed', 'user.mfa_failed') "
        "AND created_at > now() - interval '15 minutes'"
    )
    total_failed = db.scalar(text("SELECT count(*) FROM audit_log WHERE " + failure_window)) or 0
    # Je Konto, sonst je E-Mail eines Admins, sonst je Quelle (IP-Hash)
    max_per_account = db.scalar(
        text(
            "SELECT COALESCE(max(n), 0) FROM (SELECT count(*) AS n FROM audit_log WHERE " + failure_window
            + " GROUP BY COALESCE(actor_user_id::text, actor_email, ip_hash, '?')) per_account"
        )
    ) or 0
    exports = db.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = ANY(:actions) AND created_at > now() - interval '1 hour'"),
        {"actions": list(_EXPORT_ACTIONS)},
    ) or 0
    restores = db.scalar(text("SELECT count(*) FROM audit_log WHERE action = 'backup.restore.create' AND created_at > now() - interval '24 hours'")) or 0
    admin_changes = db.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = ANY(:actions) AND created_at > now() - interval '24 hours'"),
        {"actions": list(_ADMIN_CHANGE_ACTIONS)},
    ) or 0
    admin_logins = db.scalar(text("SELECT count(*) FROM audit_log WHERE action = 'admin.login' AND created_at > now() - interval '1 hour'")) or 0
    max_per_account = int(max_per_account)

    status = "ok"
    if (
        total_failed >= settings.security_failed_logins_warning
        or max_per_account >= settings.security_failed_logins_per_account
        or exports > settings.security_exports_per_hour
        or restores
        or admin_changes
        or (settings.security_alert_admin_logins and admin_logins)
    ):
        status = "warning"
    if total_failed >= settings.security_failed_logins_critical:
        status = "critical"
    return HealthCheckRead(
        key="security",
        status=status,
        params={
            "failedLogins": int(total_failed),
            "maxPerAccount": max_per_account,
            "exports": int(exports),
            "restores": int(restores),
            "adminChanges": int(admin_changes),
            "adminLogins": int(admin_logins),
        },
    )


def _check_orphaned_files(db: Session) -> HealthCheckRead:
    """Dateien, auf die nichts mehr zeigt (Datenschutz-Audit PRIV-003/004): sie sind in keiner Ansicht
    erreichbar, liegen aber im Speicher und in Backups. Neue Fälle deuten auf einen Löschpfad, der
    file_eraser.FileEraser umgeht - z. B. das Löschen eines Termins mit Abgabebox-Einreichungen."""
    from app.models.document_entities import DocumentFile
    from app.services.file_eraser import _REFERENCES

    conditions = [~select(column).where(column == StoredFile.id).exists() for column in (*_REFERENCES, DocumentFile.stored_file_id)]
    count = db.scalar(
        select(func.count()).select_from(StoredFile).where(StoredFile.created_at < func.now() - ORPHAN_MIN_AGE, *conditions)
    ) or 0
    return HealthCheckRead(key="orphaned_files", status="warning" if count else "ok", params={"count": count})


def _check_captcha_endpoint() -> HealthCheckRead:
    """Friendly Captcha der Abgabebox: EU-Endpunkt (Verarbeitung in der EU) oder globaler Endpunkt.
    Nur ein Hinweis - beides funktioniert, der EU-Endpunkt setzt einen passenden Plan voraus."""
    from urllib.parse import urlparse

    host = (urlparse(settings.friendly_captcha_verify_url).hostname or "").lower()
    region = "eu" if host.endswith(".eu") else "global"
    return HealthCheckRead(key="captcha_endpoint", status="ok", params={"region": region})


def _check_tenant_offboarding(db: Session) -> HealthCheckRead:
    """Mandanten nach Vertragsende plus Exportfenster (Datenschutz-Audit G): ihre Daten gehören
    gelöscht. Gelöscht wird bewusst von Hand (Adminportal → Mandant löschen), nie automatisch."""
    from app.services.tenant_retention_service import offboarding_due

    due = offboarding_due(db, grace_days=settings.tenant_offboarding_grace_days)
    return HealthCheckRead(
        key="tenant_offboarding", status="warning" if due else "ok",
        params={"count": len(due), "days": settings.tenant_offboarding_grace_days},
    )


def _check_photo_queue(db: Session, now: datetime) -> HealthCheckRead:
    queued, oldest = db.execute(
        select(func.count(), func.min(PhotoAnalysisJob.created_at)).where(PhotoAnalysisJob.status == "queued")
    ).one()
    oldest_minutes = round((now - oldest).total_seconds() / 60) if oldest else 0
    status: HealthStatus = "warning" if oldest and now - oldest > PHOTO_QUEUE_WARNING_AGE else "ok"
    return HealthCheckRead(key="photo_queue", status=status, params={"queued": queued, "oldestMinutes": oldest_minutes})


def _check_document_queue(db: Session, now: datetime) -> HealthCheckRead:
    """Warteschlange des document-worker (PDF-Ansicht, Textextraktion): staut sie sich, läuft
    der Worker nicht oder kommt nicht nach; endgültig gescheiterte Aufträge brauchen eine
    Entscheidung (Datei prüfen, «Erneut verarbeiten», document_admin requeue)."""
    queued, oldest = db.execute(
        select(func.count(), func.min(DocumentJob.run_after)).where(DocumentJob.status == "queued", DocumentJob.run_after <= now)
    ).one()
    failed = db.scalar(
        select(func.count()).where(DocumentJob.status == "failed", DocumentJob.updated_at >= now - DOCUMENT_FAILED_WINDOW)
    ) or 0
    oldest_minutes = round((now - oldest).total_seconds() / 60) if oldest else 0
    stalled = bool(oldest and now - oldest > DOCUMENT_QUEUE_WARNING_AGE)
    status: HealthStatus = "warning" if stalled or failed else "ok"
    return HealthCheckRead(key="document_queue", status=status, params={"queued": queued, "oldestMinutes": oldest_minutes, "failed": failed})


# Hash ohne Treffer (64 Nullen) für den Systemcheck der Prüfseite - nie ein echtes Dokument.
VERIFY_PROBE_SHA256 = "0" * 64
VERIFY_LATENCY_WARNING_MS = 2000


def _check_document_verification() -> HealthCheckRead:
    """Öffentliche Prüfseite: Prüf-Endpoint der Abgabebox erreichbar und die Funktion
    verify_document (Rechte der Rolle hocx_abgabebox) lesbar. Intern ohne Traefik, damit das
    Rate-Limit nicht zählt. Erwartet 200 {"found": false}."""
    url = f"{settings.abgabebox_internal_url.rstrip('/')}/api/public/verify"
    request = urllib.request.Request(
        url, data=json.dumps({"sha256": VERIFY_PROBE_SHA256}).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.loads(response.read().decode() or "{}")
    latency_ms = round((time.monotonic() - started) * 1000)
    if body != {"found": False}:
        raise RuntimeError(f"Unerwartete Antwort: {str(body)[:200]}")
    status: HealthStatus = "warning" if latency_ms > VERIFY_LATENCY_WARNING_MS else "ok"
    return HealthCheckRead(key="document_verification", status=status, params={"latencyMs": latency_ms})


RENDER_QUEUE_WARNING_AGE = timedelta(minutes=10)
RENDER_FAILED_WINDOW = timedelta(hours=24)


def _check_render_queue(db: Session, now: datetime) -> HealthCheckRead:
    """PDF-Aufträge (document_render_job, job-worker): staut sich die Warteschlange, läuft der
    job-worker nicht oder kommt nicht nach; gescheiterte Aufträge zeigen Vorlagen- oder
    Renderprobleme (Details im Fehlerprotokoll)."""
    queued, oldest = db.execute(
        text("SELECT count(*), min(created_at) FROM document_render_job WHERE status = 'queued'")
    ).one()
    failed = db.scalar(
        text("SELECT count(*) FROM document_render_job WHERE status = 'failed' AND finished_at >= :since AND error_status >= 500"),
        {"since": now - RENDER_FAILED_WINDOW},
    ) or 0
    oldest_minutes = round((now - oldest).total_seconds() / 60) if oldest else 0
    stalled = bool(oldest and now - oldest > RENDER_QUEUE_WARNING_AGE)
    status: HealthStatus = "warning" if stalled or failed else "ok"
    return HealthCheckRead(key="render_queue", status=status, params={"queued": queued, "oldestMinutes": oldest_minutes, "failed": failed})


# Laufzeitkennzahlen der Dienstprozesse (core/runtime_metrics.py, Migration 0148).
RUNTIME_REPORT_MAX_AGE = timedelta(seconds=60)
RUNTIME_LAG_WARNING_MS = 1000
RUNTIME_LAG_CRITICAL_MS = 10000


def _check_runtime(db: Session, now: datetime) -> HealthCheckRead:
    """Event-Loop-Verzögerung und Pool-/Threadpool-Sättigung aller Prozesse der letzten Minute.
    Ein blockierter Event-Loop oder ein voller Pool trifft alle Mandanten dieses Workers - das
    soll auffallen, bevor Nutzer Zeitüberschreitungen melden."""
    rows = db.execute(
        text("SELECT process_kind, metrics FROM system_runtime_metric WHERE reported_at >= :since"),
        {"since": now - RUNTIME_REPORT_MAX_AGE},
    ).all()
    if not rows:
        return HealthCheckRead(key="runtime", status="unknown", params={"instances": 0})
    max_lag = pool_peak = thread_peak = timeouts = 0
    for row in rows:
        metrics = row.metrics or {}
        max_lag = max(max_lag, int(metrics.get("loop_lag_max_ms") or 0))
        # Abgewiesen wegen Überlast: Pool-Timeout oder kein Platz in der Request-Annahme
        timeouts += int(metrics.get("pool_timeouts") or 0) + int(metrics.get("admission_timeouts") or 0)
        if metrics.get("pool_capacity"):
            pool_peak = max(pool_peak, round(100 * int(metrics.get("pool_checked_out_max") or 0) / int(metrics["pool_capacity"])))
        if metrics.get("threadpool_total"):
            thread_peak = max(thread_peak, round(100 * int(metrics.get("threadpool_busy_max") or 0) / int(metrics["threadpool_total"])))
    status: HealthStatus = "ok"
    if max_lag >= RUNTIME_LAG_WARNING_MS or pool_peak >= 100 or thread_peak >= 100 or timeouts:
        status = "warning"
    if max_lag >= RUNTIME_LAG_CRITICAL_MS:
        status = "critical"
    return HealthCheckRead(
        key="runtime",
        status=status,
        params={"instances": len(rows), "maxLagMs": max_lag, "poolPeakPercent": pool_peak, "threadPeakPercent": thread_peak, "poolTimeouts": timeouts},
    )


# Abgewiesene neue Nutzer bei Überlast (db_admission.py, Migration 0151). Ein Fenster von fünf
# Minuten, damit eine Überlast-Phase nicht zwischen zwei Prüfungen (alle 30 s) und den
# 15-s-Meldungen der Worker flackernd "behoben" wirkt.
OVERLOAD_WINDOW = timedelta(minutes=5)


def _check_overload(db: Session, now: datetime) -> HealthCheckRead:
    """Warnung, solange Nutzer wegen Überlast die Überlast-Seite sehen."""
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(rejected), 0) AS rejected, COALESCE(SUM(users), 0) AS users, "
            "COUNT(DISTINCT tenant_id) AS tenants, COALESCE(MAX(pressure_percent), 0) AS pressure "
            "FROM overload_rejection WHERE created_at >= :since"
        ),
        {"since": now - OVERLOAD_WINDOW},
    ).one()
    return HealthCheckRead(
        key="overload",
        status="warning" if row.rejected else "ok",
        params={
            "minutes": int(OVERLOAD_WINDOW.total_seconds() // 60),
            "rejected": int(row.rejected),
            "users": int(row.users),
            "tenants": int(row.tenants),
            "pressurePercent": int(row.pressure),
        },
    )


OVERLOAD_HISTORY_DAYS = 7


def overload_by_tenant(db: Session, now: datetime) -> list[OverloadTenantRead]:
    """Abweisungen der letzten Tage je Mandant und Stufe für /admin/system, neueste zuerst.
    "users" summiert die Zählung je Meldung - ein Nutzer, der über mehrere Meldungen hinweg
    abgewiesen wurde, zählt mehrfach (Obergrenze, nicht exakt)."""
    rows = db.execute(
        text(
            "SELECT t.public_id, t.name AS tenant_name, p.name AS plan_name, r.load_priority, "
            "SUM(r.rejected) AS rejected, SUM(r.users) AS users, MIN(r.created_at) AS first_at, MAX(r.created_at) AS last_at "
            "FROM overload_rejection r LEFT JOIN tenant t ON t.id = r.tenant_id LEFT JOIN plan p ON p.code = t.plan_code "
            "WHERE r.created_at >= :since "
            "GROUP BY t.public_id, t.name, p.name, r.load_priority ORDER BY MAX(r.created_at) DESC LIMIT 100"
        ),
        {"since": now - timedelta(days=OVERLOAD_HISTORY_DAYS)},
    ).all()
    return [
        OverloadTenantRead(
            tenant_id=str(row.public_id) if row.public_id else None,
            tenant_name=row.tenant_name,
            plan_name=row.plan_name,
            load_priority=int(row.load_priority),
            rejected=int(row.rejected),
            users=int(row.users),
            first_at=row.first_at,
            last_at=row.last_at,
        )
        for row in rows
    ]


# Teure Vollzählungen (verwaiste Dateien über alle Referenzen, Belegung des lokalen S3) ändern sich
# langsam - je Prozess höchstens stündlich rechnen statt bei jedem 30-s-Tick (Concurrency-Audit
# CONC-024: mit wachsendem Bestand näherten sie sich dem statement_timeout).
SLOW_CHECK_TTL_SECONDS = 3600
_slow_check_cache: dict[str, tuple[float, object]] = {}


def _cached_slow_check(key: str, fn):
    now = time.monotonic()
    cached = _slow_check_cache.get(key)
    if cached is not None and now - cached[0] < SLOW_CHECK_TTL_SECONDS:
        return cached[1]
    result = fn()
    _slow_check_cache[key] = (now, result)
    return result


def _run_check(key: str, fn, *, failure_status: HealthStatus = "critical", db: Session | None = None) -> list[HealthCheckRead]:
    """Ein Ausfall einer Prüfung ist selbst ein Befund (Dienst nicht erreichbar) - er darf aber
    die übrigen Prüfungen nicht verhindern."""
    try:
        result = fn()
    except Exception as exc:
        if db is not None:
            db.rollback()
        return [HealthCheckRead(key=key, status=failure_status, error=f"{type(exc).__name__}: {exc}"[:500])]
    return result if isinstance(result, list) else [result]


def collect_checks(db: Session, now: datetime) -> list[HealthCheckRead]:
    checks: list[HealthCheckRead] = []
    checks += _run_check("postgres", lambda: _check_postgres(db), db=db)
    checks += _run_check("redis", _check_redis)
    clamav = _run_check("clamav", lambda: _check_clamav(now))
    if len(clamav) == 1 and clamav[0].key == "clamav":
        # Nicht erreichbar - Signaturalter ist dann unbekannt, kein eigener Alarm.
        clamav.append(HealthCheckRead(key="clamav_signatures", status="unknown"))
    checks += clamav
    checks += _run_check("storage", _check_storage)
    checks += _run_check("object_storage", _check_object_storage)
    # Reine DB-Auswertungen: ein Fehler hier ist ein Bug, kein Ausfall - "unknown" statt Alarm.
    checks += _run_check("error_rate", lambda: _check_error_rate(db), failure_status="unknown", db=db)
    checks += _run_check("scan_backlog", lambda: _check_scan_backlog(db), failure_status="unknown", db=db)
    checks += _run_check("orphaned_files", lambda: _cached_slow_check("orphaned_files", lambda: _check_orphaned_files(db)), failure_status="unknown", db=db)
    checks += _run_check("tenant_offboarding", lambda: _check_tenant_offboarding(db), failure_status="unknown", db=db)
    checks += _run_check("captcha_endpoint", _check_captcha_endpoint, failure_status="unknown", db=db)
    checks += _run_check("security", lambda: _check_security(db), failure_status="unknown", db=db)
    checks += _run_check("photo_queue", lambda: _check_photo_queue(db, now), failure_status="unknown", db=db)
    checks += _run_check("document_queue", lambda: _check_document_queue(db, now), failure_status="unknown", db=db)
    checks += _run_check("render_queue", lambda: _check_render_queue(db, now), failure_status="unknown", db=db)
    checks += _run_check("runtime", lambda: _check_runtime(db, now), failure_status="unknown", db=db)
    checks += _run_check("overload", lambda: _check_overload(db, now), failure_status="unknown", db=db)
    checks += _run_check("document_verification", _check_document_verification)
    checks += _run_check("storage_migration", lambda: _check_storage_migration(db, now), failure_status="unknown", db=db)
    checks += _run_check("local_s3", lambda: _cached_slow_check("local_s3", lambda: _check_local_s3(db)), failure_status="unknown", db=db)
    checks += _run_check("backup", lambda: _check_backup(db, now), failure_status="unknown", db=db)
    return checks


# ── Snapshot ──────────────────────────────────────────────────────────────────────────────


def collect_snapshot(db: Session, *, now: datetime | None = None) -> SystemHealthSnapshot:
    now = now or datetime.now(timezone.utc)
    docker_configured = bool(settings.docker_api_url)
    project, containers, docker_error = None, [], None
    if docker_configured:
        try:
            project, containers = collect_containers()
        except docker_api.DockerApiUnavailable as exc:
            docker_error = str(exc)[:500]
    return SystemHealthSnapshot(
        collected_at=now,
        docker_configured=docker_configured,
        docker_available=docker_configured and docker_error is None,
        docker_error=docker_error,
        compose_project=project,
        containers=mark_intentionally_stopped_local_s3(db, containers),
        checks=collect_checks(db, now),
    )


def load_snapshot() -> SystemHealthSnapshot | None:
    try:
        raw = get_redis_sync().get(SNAPSHOT_REDIS_KEY)
    except Exception:
        _logger.warning("Systemstatus-Snapshot konnte nicht aus Redis gelesen werden", exc_info=True)
        return None
    return SystemHealthSnapshot.model_validate_json(raw) if raw else None


def store_snapshot(snapshot: SystemHealthSnapshot) -> None:
    get_redis_sync().set(SNAPSHOT_REDIS_KEY, snapshot.model_dump_json())


def is_stale(snapshot: SystemHealthSnapshot | None, now: datetime) -> bool:
    return snapshot is None or now - snapshot.collected_at > SNAPSHOT_MAX_AGE


def detect_container_restarts(db: Session, previous: SystemHealthSnapshot | None, current: SystemHealthSnapshot) -> None:
    """Neustart = gleicher Container (gleiche ID), aber neuer Startzeitpunkt - also Absturz mit
    Restart-Policy oder `docker restart`. Ein neu erstellter Container (Deploy: neue ID) zählt
    bewusst nicht, sonst meldete jeder Deploy jeden Dienst als "neu gestartet"."""
    if previous is None:
        return
    before = {container.service: container for container in previous.containers}
    for container in current.containers:
        old = before.get(container.service)
        if old is None or old.container_id != container.container_id or old.started_at == container.started_at or container.started_at is None:
            continue
        db.add(
            SystemHealthEvent(
                kind="container_restart",
                subject=f"container:{container.service}",
                reason="restarted",
                severity="warning",
                title=f"Container {container.service} wurde neu gestartet",
                message=f"{container.name} läuft seit {container.started_at:%d.%m.%Y %H:%M:%S} UTC wieder (Neustarts insgesamt: {container.restart_count}).",
            )
        )
    db.commit()


def run_collection(db: Session) -> SystemHealthSnapshot:
    previous = load_snapshot()
    snapshot = collect_snapshot(db)
    try:
        detect_container_restarts(db, previous, snapshot)
    except Exception as exc:
        db.rollback()
        record_system_error(db, exc=exc)
    try:
        store_snapshot(snapshot)
    except Exception:
        # Redis weg: der Tick muss trotzdem weiter zur Auswertung, sonst würde ausgerechnet der
        # Redis-Ausfall (Prüfung "redis" = critical) nie gemeldet. Die Seite zeigt dann "veraltet".
        _logger.warning("Systemstatus-Snapshot konnte nicht in Redis gespeichert werden", exc_info=True)
    return snapshot
