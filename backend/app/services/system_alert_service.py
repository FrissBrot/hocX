"""Leitet aus Systemstatus-Snapshot und Job-Übersicht die aktuellen Probleme ab und
benachrichtigt per ntfy bei Statuswechseln: neu (nach einer Karenzzeit), verschärft
(warning -> critical), weiterhin offen (Erinnerung) und behoben.

Die Karenzzeit (NOTIFY_GRACE) verhindert Alarme durch Deploys: Container sind beim Neuerstellen
kurz weg oder "starting" - ein Problem wird erst gemeldet, wenn es mehrere Durchläufe übersteht.
Probleme, die vorher wieder verschwinden, hinterlassen weder Nachricht noch Ereignis.

Problem-Schlüssel sind "<quelle>:<subjekt>[:<zusatz>]" (z. B. "job:export_cleanup",
"container:backend:restarts"); Titel und Text sind deutsch und gehen so an ntfy. Die Admin-
Oberfläche übersetzt dagegen anhand von source/subject/reason."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.error_log import record_system_error
from app.core.job_registry import JOBS_BY_NAME
from app.models import SystemAlertState, SystemHealthEvent
from app.schemas.admin import JobStatusOverview, SystemHealthSnapshot, SystemProblemRead
from app.services import ntfy_client, system_health_service
from app.services.admin_job_status_service import AdminJobStatusService
from app.services.notification_settings_service import NotificationSettingsService

_logger = logging.getLogger(__name__)

NOTIFY_GRACE = timedelta(seconds=90)
RESTART_LOOP_WINDOW = timedelta(minutes=15)
RESTART_LOOP_COUNT = 3
# Ein Loop, der nie gemeldet hat, ist direkt nach dem Start normal (erster Tick läuft noch).
NEVER_RUN_GRACE = timedelta(minutes=30)
# Mehr gleichzeitige Meldungen werden zu einer Sammelnachricht zusammengefasst (z. B. nach dem
# ersten Aktivieren oder wenn der ganze Host hängt).
MAX_INDIVIDUAL_MESSAGES = 5
CONTAINER_STARTING_GRACE = timedelta(minutes=10)

_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_SEVERITY_RANK = {"warning": 1, "critical": 2}
_PRIORITY = {"critical": 4, "warning": 3, "resolved": 2}
_TAGS = {"critical": ["rotating_light"], "warning": ["warning"], "resolved": ["white_check_mark"]}

_CONTAINER_REASONS_DE = {
    "not_running": "läuft nicht",
    "unhealthy": "ist unhealthy",
    "oom_killed": "wurde wegen Speichermangel beendet",
    "starting": "kommt nicht aus dem Start heraus",
    "memory_high": "hat fast keinen Speicher mehr",
}
_CHECK_TITLES_DE = {
    "postgres": "Datenbank (Postgres)",
    "redis": "Redis",
    "clamav": "Virenscanner (ClamAV)",
    "clamav_signatures": "Virensignaturen",
    "storage": "Speicherplatz",
    "error_rate": "Fehlerrate",
    "scan_backlog": "Virenprüfung im Rückstand",
    "photo_queue": "Bildanalyse-Warteschlange",
    "object_storage": "Dateispeicher",
    "storage_migration": "Storage-Migration",
}
# Titel, wenn die Prüfung lief, aber einen Schwellwert reisst (sonst "<Name> nicht erreichbar").
_CHECK_PROBLEM_TITLES_DE = {
    "postgres": "Datenbank langsam oder ausgelastet",
    "redis": "Redis-Speicher fast voll",
    "clamav_signatures": "Virensignaturen veraltet",
    "storage": "Speicherplatz knapp",
    "error_rate": "Viele Einträge im Fehlerprotokoll",
    "scan_backlog": "Virenprüfung im Rückstand",
    "photo_queue": "Bildanalyse-Warteschlange staut sich",
    "object_storage": "Dateispeicher nicht erreichbar",
    "storage_migration": "Storage-Migration braucht Aufmerksamkeit",
}
_JOB_REASONS_DE = {
    "failing": "ist fehlgeschlagen",
    "overdue": "ist überfällig",
    "never_run": "ist noch nie gelaufen",
}


def _instance_label() -> str:
    return f"hocX {settings.traefik_domain}" if settings.traefik_domain else "hocX"


def _problem(key: str, source: str, subject: str, reason: str, severity: str, title: str, message: str) -> SystemProblemRead:
    return SystemProblemRead(key=key, source=source, subject=subject, reason=reason, severity=severity, title=title, message=message)


def _de(value) -> str:
    """Zahl mit deutschem Dezimalkomma für ntfy-Texte (5.8 -> "5,8")."""
    return str(value).replace(".", ",") if isinstance(value, float) else str(value)


def _check_message(check) -> str:
    if check.error:
        return f"Prüfung fehlgeschlagen: {check.error}"
    params = {key: _de(value) for key, value in check.params.items()}
    match check.key:
        case "postgres":
            return f"Antwortzeit {params.get('latencyMs')} ms, {params.get('connections')}/{params.get('maxConnections')} Verbindungen."
        case "redis":
            return f"Antwortzeit {params.get('latencyMs')} ms, {params.get('usedMb')} MB belegt."
        case "clamav_signatures":
            return f"Signaturen sind {params.get('ageHours')} Stunden alt (Version {params.get('signatureVersion')}) - freshclam prüfen."
        case "storage":
            return f"Nur noch {params.get('freePercent')} % frei ({params.get('freeGb')} von {params.get('totalGb')} GB)."
        case "error_rate":
            return f"{params.get('lastHour')} Fehler in der letzten Stunde, {params.get('lastDay')} in 24 Stunden - siehe Fehlerprotokoll."
        case "scan_backlog":
            return f"{params.get('count')} Dateien warten seit über einer Stunde auf die Virenprüfung."
        case "photo_queue":
            return f"{params.get('queued')} Aufträge warten, der älteste seit {params.get('oldestMinutes')} Minuten."
        case "object_storage":
            return "Der aktive Dateispeicher (S3) antwortet nicht - Uploads und Downloads schlagen fehl."
        case "storage_migration":
            return f"{params.get('verified')} von {params.get('total')} Objekten geprüft, {params.get('dead')} dauerhaft fehlgeschlagen - siehe Adminportal, Storage."
    return "Siehe Systemstatus."


def derive_problems(
    snapshot: SystemHealthSnapshot | None,
    jobs: JobStatusOverview,
    *,
    now: datetime,
    restart_counts: dict[str, int] | None = None,
) -> list[SystemProblemRead]:
    problems: list[SystemProblemRead] = []

    if system_health_service.is_stale(snapshot, now):
        problems.append(_problem(
            "monitor:snapshot", "monitor", "snapshot", "stale", "critical",
            "Systemmonitoring liefert keine Daten",
            "Der Systemstatus wurde seit über drei Minuten nicht aktualisiert - der Monitoring-Loop im Backend hängt oder läuft nicht.",
        ))
    if snapshot is not None:
        if snapshot.docker_configured and not snapshot.docker_available:
            problems.append(_problem(
                "monitor:docker", "monitor", "docker", "unavailable", "warning",
                "Container-Status nicht verfügbar",
                f"docker-socket-proxy nicht erreichbar: {snapshot.docker_error}",
            ))
        for container in snapshot.containers:
            reasons = [
                reason for reason in container.reasons
                if not (reason == "starting" and container.started_at and now - container.started_at < CONTAINER_STARTING_GRACE)
            ]
            if not reasons:
                continue
            critical = [reason for reason in reasons if reason in ("not_running", "unhealthy", "oom_killed")]
            reason = (critical or reasons)[0]
            detail = ""
            if reason == "not_running":
                detail = f" Status: {container.state}" + (f", Exit-Code {container.exit_code}." if container.exit_code is not None else ".")
            elif reason == "unhealthy" and container.health_output:
                detail = f" Letzter Healthcheck: {container.health_output[:200]}"
            elif reason == "memory_high" and container.memory_bytes and container.memory_limit_bytes:
                detail = f" {round(container.memory_bytes / container.memory_limit_bytes * 100)} % des Limits belegt."
            problems.append(_problem(
                f"container:{container.service}", "container", container.service, reason,
                "critical" if critical else "warning",
                f"Container {container.service} {_CONTAINER_REASONS_DE.get(reason, reason)}",
                f"{container.name}.{detail}".strip(),
            ))
        for service, count in (restart_counts or {}).items():
            if count >= RESTART_LOOP_COUNT:
                problems.append(_problem(
                    f"container:{service}:restarts", "container", service, "restart_loop", "critical",
                    f"Container {service} startet ständig neu",
                    f"{count} Neustarts in den letzten {int(RESTART_LOOP_WINDOW.total_seconds() // 60)} Minuten.",
                ))
        for check in snapshot.checks:
            if check.status not in ("warning", "critical"):
                continue
            problems.append(_problem(
                f"check:{check.key}", "check", check.key, "unreachable" if check.error else check.status, check.status,
                f"{_CHECK_TITLES_DE.get(check.key, check.key)} nicht erreichbar" if check.error
                else _CHECK_PROBLEM_TITLES_DE.get(check.key, _CHECK_TITLES_DE.get(check.key, check.key)),
                _check_message(check),
            ))

    for job in jobs.items:
        definition = JOBS_BY_NAME.get(job.name)
        if job.state == "failing":
            severity = "critical" if job.consecutive_failures >= 3 else "warning"
            message = f"{job.consecutive_failures} Fehlschläge in Folge. Letzter Fehler: {(job.last_error or '-')[:300]}"
        elif job.state == "overdue":
            severity = "critical" if definition and definition.category == "backup" else "warning"
            last = max((value for value in (job.last_finished_at, job.last_heartbeat_at) if value), default=None)
            message = f"Letztes Lebenszeichen: {last:%d.%m.%Y %H:%M} UTC." if last else "Noch kein Lebenszeichen."
        elif job.state == "never_run" and definition and definition.kind in ("loop", "worker"):
            # Host-Cronjobs bewusst nicht: die sind registriert, bevor sie eingerichtet werden.
            # Die Schonfrist nach dem Start gilt nur für die erste Meldung (evaluate_and_notify) -
            # hier ausgeblendet, würde jeder Backend-Neustart ein offenes Problem kurz als
            # "behoben" melden und 30 min später erneut (2026-10-11 im Dev-Stack beobachtet).
            severity = "warning"
            message = "Seit dem Start des Backends kein einziger Lauf gemeldet."
        else:
            continue
        problems.append(_problem(
            f"job:{job.name}", "job", job.name, job.state, severity,
            f"Job {job.name} {_JOB_REASONS_DE[job.state]}",
            message,
        ))
    return problems


def recent_restart_counts(db: Session, now: datetime) -> dict[str, int]:
    rows = db.execute(
        select(SystemHealthEvent.subject, func.count())
        .where(SystemHealthEvent.kind == "container_restart", SystemHealthEvent.created_at >= now - RESTART_LOOP_WINDOW)
        .group_by(SystemHealthEvent.subject)
    ).all()
    return {subject.removeprefix("container:"): count for subject, count in rows}


def current_problems(db: Session, snapshot: SystemHealthSnapshot | None, *, now: datetime | None = None) -> list[SystemProblemRead]:
    """Live-Probleme mit first_seen_at aus system_alert_state (für Seite und Summary-Endpoint)."""
    now = now or datetime.now(timezone.utc)
    problems = derive_problems(
        snapshot, AdminJobStatusService().get_overview(db, now=now), now=now, restart_counts=recent_restart_counts(db, now)
    )
    first_seen = {row.problem_key: row.first_seen_at for row in db.scalars(select(SystemAlertState))}
    return [problem.model_copy(update={"first_seen_at": first_seen.get(problem.key)}) for problem in problems]


def _click_path(source: str) -> str:
    return "/admin/jobs" if source == "job" else "/admin/system"


def _event(kind: str, subject: str, reason: str | None, severity: str, title: str, message: str, now: datetime) -> SystemHealthEvent:
    return SystemHealthEvent(kind=kind, subject=subject, reason=reason, severity=severity, title=title, message=message, created_at=now, notified_at=now)


def evaluate_and_notify(db: Session, snapshot: SystemHealthSnapshot | None, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    settings_service = NotificationSettingsService()
    notification_settings = settings_service.get_row(db)
    reminder = timedelta(hours=notification_settings.reminder_hours) if notification_settings.reminder_hours else None

    problems = {problem.key: problem for problem in derive_problems(
        snapshot, AdminJobStatusService().get_overview(db, now=now), now=now, restart_counts=recent_restart_counts(db, now)
    )}
    states = {row.problem_key: row for row in db.scalars(select(SystemAlertState))}
    outgoing: list[ntfy_client.NtfyMessage] = []

    for key, problem in problems.items():
        row = states.get(key)
        if row is None:
            row = SystemAlertState(
                problem_key=key, severity=problem.severity, reason=problem.reason, title=problem.title,
                message=problem.message, first_seen_at=now,
            )
            db.add(row)
        else:
            row.severity, row.reason, row.title, row.message = problem.severity, problem.reason, problem.title, problem.message

        prefix = None
        if row.notified_severity is None:
            grace_over = now - row.first_seen_at >= NOTIFY_GRACE
            if problem.reason == "never_run":
                # Direkt nach dem Start hat noch kein Loop getickt - erst melden, wenn er es in
                # der Schonfrist nicht geschafft hat.
                grace_over = grace_over and now - _PROCESS_STARTED_AT >= NEVER_RUN_GRACE
            if grace_over:
                prefix = ""
        elif _SEVERITY_RANK[problem.severity] > _SEVERITY_RANK[row.notified_severity]:
            prefix = "Verschärft: "
        elif reminder and row.last_notified_at and now - row.last_notified_at >= reminder:
            prefix = "Weiterhin: "
        if prefix is None:
            continue
        if prefix != "Weiterhin: ":
            db.add(_event("problem", key, problem.reason, problem.severity, problem.title, problem.message, now))
        row.notified_severity = problem.severity
        row.last_notified_at = now
        outgoing.append(ntfy_client.NtfyMessage(
            title=f"[{_instance_label()}] {prefix}{problem.title}",
            message=problem.message,
            priority=_PRIORITY[problem.severity],
            tags=_TAGS[problem.severity],
            click=_click_path(problem.source),
        ))

    for key, row in states.items():
        if key in problems:
            continue
        if row.notified_severity is not None:
            db.add(_event("resolved", key, row.reason, "info", f"Behoben: {row.title}", row.message, now))
            outgoing.append(ntfy_client.NtfyMessage(
                title=f"[{_instance_label()}] Behoben: {row.title}",
                message=f"Seit {row.first_seen_at:%d.%m.%Y %H:%M} UTC offen gewesen.",
                priority=_PRIORITY["resolved"],
                tags=_TAGS["resolved"],
                click=_click_path(key.split(":", 1)[0]),
            ))
        db.execute(delete(SystemAlertState).where(SystemAlertState.problem_key == key))

    for event in db.scalars(select(SystemHealthEvent).where(SystemHealthEvent.kind == "container_restart", SystemHealthEvent.notified_at.is_(None))):
        event.notified_at = now
        outgoing.append(ntfy_client.NtfyMessage(
            title=f"[{_instance_label()}] {event.title}", message=event.message,
            priority=_PRIORITY["warning"], tags=["arrows_counterclockwise"], click="/admin/system",
        ))
    db.commit()

    if outgoing and notification_settings.ntfy_enabled:
        _send_all(db, settings_service, outgoing)


def _send_all(db: Session, settings_service: NotificationSettingsService, messages: list[ntfy_client.NtfyMessage]) -> None:
    if len(messages) > MAX_INDIVIDUAL_MESSAGES:
        worst = max(messages, key=lambda message: message.priority)
        messages = [ntfy_client.NtfyMessage(
            title=f"[{_instance_label()}] {len(messages)} Statusänderungen",
            message="\n".join(f"• {message.title.split('] ', 1)[-1]}" for message in messages),
            priority=worst.priority,
            tags=worst.tags,
            click="/admin/system",
        )]
    previous_error = settings_service.get_row(db).last_send_error
    for message in messages:
        try:
            settings_service.send(db, message)
        except ntfy_client.NtfyError as exc:
            # Nur beim ersten Auftreten bzw. bei geänderter Ursache ins Fehlerprotokoll - sonst
            # schriebe ein ausgefallener ntfy-Server alle 30 s einen Eintrag. Der aktuelle Fehler
            # steht ohnehin auf der Einstellungsseite.
            if str(exc)[:500] != previous_error:
                record_system_error(db, exc=exc)
            _logger.warning("ntfy-Benachrichtigung fehlgeschlagen: %s", exc)
            return


def run_monitor_tick(db: Session) -> None:
    """Task des Loops system_monitor (main.py): sammeln, speichern, auswerten, benachrichtigen."""
    snapshot = system_health_service.run_collection(db)
    evaluate_and_notify(db, snapshot)


def cleanup_old_events(db: Session, *, retention_days: int) -> dict:
    deleted = db.execute(
        delete(SystemHealthEvent).where(SystemHealthEvent.created_at < func.now() - timedelta(days=retention_days))
    ).rowcount
    db.commit()
    return {"deleted": deleted}
