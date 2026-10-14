"""Sammelt den Systemzustand für /admin/system: Container (über den docker-socket-proxy) und
Prüfungen der Dienste, von denen hocX abhängt (Postgres, Redis, ClamAV, Speicherplatz, ...).

Läuft im Loop system_monitor (main.py) alle settings.system_monitor_interval_seconds. Der
Snapshot liegt in Redis, damit jeder uvicorn-Worker die Seite ohne eigene Docker-Abfragen
ausliefern kann. Die Schwellwerte hier bestimmen zugleich, was system_alert_service als
Problem meldet - eine Stelle, damit Seite und ntfy nie unterschiedlich urteilen."""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timedelta, timezone

import pyclamd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import docker_api
from app.core.config import settings
from app.core.error_log import record_system_error
from app.core.redis_client import get_redis_sync
from app.models import StoredFile, SystemErrorLog, SystemHealthEvent
from app.models.entities import PhotoAnalysisJob
from app.schemas.admin import ContainerStatusRead, HealthCheckRead, HealthStatus, SystemHealthSnapshot

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
PHOTO_QUEUE_WARNING_AGE = timedelta(hours=6)
# Restlaufzeit des Signaturzertifikats, ab der gewarnt wird
SIGNING_CERT_WARNING_DAYS = 30
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


def evaluate_container(container: ContainerStatusRead) -> ContainerStatusRead:
    reasons: list[str] = []
    status: HealthStatus = "ok"
    if container.state != "running":
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
        )
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


def _check_photo_queue(db: Session, now: datetime) -> HealthCheckRead:
    queued, oldest = db.execute(
        select(func.count(), func.min(PhotoAnalysisJob.created_at)).where(PhotoAnalysisJob.status == "queued")
    ).one()
    oldest_minutes = round((now - oldest).total_seconds() / 60) if oldest else 0
    status: HealthStatus = "warning" if oldest and now - oldest > PHOTO_QUEUE_WARNING_AGE else "ok"
    return HealthCheckRead(key="photo_queue", status=status, params={"queued": queued, "oldestMinutes": oldest_minutes})


def _check_document_signing() -> HealthCheckRead:
    """Signaturzertifikat der Dokument-Engine: vorhanden, lesbar, nicht bald abgelaufen.
    Fehlende Konfiguration ist nur in Produktion ein Alarm (dort startet das Backend ohnehin nicht)."""
    from app.documents.signing import certificate_status

    cert = certificate_status()
    if not cert.configured:
        return HealthCheckRead(
            key="document_signing", status="critical" if settings.is_production else "unknown",
            params={"state": "missing", "daysLeft": 0, "notAfter": "-"},
        )
    if not cert.readable:
        return HealthCheckRead(key="document_signing", status="critical", params={"state": "unreadable", "daysLeft": 0, "notAfter": "-", "reason": cert.error or "-"})
    days_left = cert.days_left or 0
    state, status = "ok", "ok"
    if days_left < SIGNING_CERT_WARNING_DAYS:
        state, status = "expiring", "warning"
    if days_left < 0:
        state, status = "expired", "critical"
    return HealthCheckRead(
        key="document_signing", status=status,
        params={"state": state, "daysLeft": max(days_left, 0), "notAfter": f"{cert.not_after:%d.%m.%Y}" if cert.not_after else "-"},
    )


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
    # Reine DB-Auswertungen: ein Fehler hier ist ein Bug, kein Ausfall - "unknown" statt Alarm.
    checks += _run_check("error_rate", lambda: _check_error_rate(db), failure_status="unknown", db=db)
    checks += _run_check("scan_backlog", lambda: _check_scan_backlog(db), failure_status="unknown", db=db)
    checks += _run_check("photo_queue", lambda: _check_photo_queue(db, now), failure_status="unknown", db=db)
    checks += _run_check("document_signing", _check_document_signing)
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
        containers=containers,
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
