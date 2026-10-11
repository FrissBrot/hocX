"""Verzeichnis aller periodischen Jobs, die /admin/jobs anzeigt und (ab Phase 3) per ntfy überwacht.

Was ein Job tatsächlich gemeldet hat, steht in system_job_status (Migration 0105). Hier steht,
was es geben *sollte*: so fällt auch ein Job auf, der nie gelaufen ist (z. B. ein Loop, der beim
Start an einem KeyError stirbt - siehe die Vorfälle in background_loops.py - oder ein Cronjob,
der nie eingetragen wurde). Jobs, die melden, aber hier fehlen, zeigt die Seite trotzdem an
(als "nicht registriert"), damit ein neuer Host-Cronjob sofort sichtbar ist.

Jeder Schlüssel in BACKGROUND_LOCK_IDS braucht hier einen Eintrag - das prüft der Import unten,
genauso wie die Eindeutigkeit der Lock-IDs in background_loops.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.background_loops import BACKGROUND_LOCK_IDS
from app.core.config import settings

JobKind = Literal["loop", "worker", "host_cron"]
JobService = Literal["backend", "abgabebox-backend", "photo-analysis-worker", "host"]
JobCategory = Literal["virus_scan", "photo_analysis", "uploads", "cleanup", "maintenance", "backup"]

# Mindestspielraum, bevor ein Job als überfällig gilt - ein langer Tick (grosser ZIP-Import,
# viele Dateien im Rescan) verschiebt den nächsten Lauf, ohne dass etwas kaputt ist.
_MIN_MAX_SILENCE_SECONDS = 15 * 60


@dataclass(frozen=True)
class JobDefinition:
    name: str
    kind: JobKind
    service: JobService
    category: JobCategory
    # None = kein fester Takt (z. B. Worker, der nur bei Arbeit läuft).
    interval_seconds: int | None
    # Wie lange der Job höchstens ohne Lebenszeichen (Lauf oder Heartbeat) bleiben darf.
    max_silence_seconds: int
    # False bei hochfrequenten Jobs: Verlauf enthält dann nur Fehler und den ersten Erfolg danach.
    keep_history: bool = True


def _loop(name: str, category: JobCategory, interval_minutes: float, *, max_silence_seconds: int | None = None) -> JobDefinition:
    interval_seconds = int(interval_minutes * 60)
    return JobDefinition(
        name=name,
        kind="loop",
        service="backend",
        category=category,
        interval_seconds=interval_seconds,
        max_silence_seconds=max_silence_seconds or max(interval_seconds * 3, _MIN_MAX_SILENCE_SECONDS),
        keep_history=interval_seconds >= 60,
    )


JOB_DEFINITIONS: tuple[JobDefinition, ...] = (
    _loop("upload_pipeline_rescan", "virus_scan", settings.upload_pipeline_rescan_interval_minutes),
    _loop("abgabebox_rescan", "virus_scan", settings.abgabebox_rescan_interval_minutes),
    # Ein grosser ZIP-Import kann einen einzelnen Tick lange blockieren - 3 x 5 s wäre ein Fehlalarm.
    _loop("gallery_upload_ingest", "uploads", 5 / 60, max_silence_seconds=60 * 60),
    # Läuft nur im konfigurierten Zeitfenster und bei niedriger Host-Last (should_run) - ein
    # Tag ohne Lauf ist darum noch kein Fehler.
    _loop(
        "photo_analysis_auto_queue",
        "photo_analysis",
        settings.photo_analysis_auto_queue_interval_minutes,
        max_silence_seconds=26 * 60 * 60,
    ),
    _loop("photo_quality_backfill", "photo_analysis", settings.photo_quality_backfill_interval_minutes),
    _loop("photo_album_sync", "photo_analysis", settings.photo_album_sync_interval_minutes),
    _loop("domain_health_check", "maintenance", settings.domain_health_check_interval_minutes),
    _loop("cycle_snapshot", "maintenance", settings.cycle_snapshot_check_interval_minutes),
    _loop("export_cleanup", "cleanup", settings.export_cleanup_interval_minutes),
    _loop("log_cleanup", "cleanup", settings.log_cleanup_interval_minutes),
    # Sammelt den Systemstatus und verschickt ntfy-Alarme. Hängt er, fällt das nicht hier auf
    # (er wertet sich selbst aus), sondern über den veralteten Snapshot: Seite und der
    # Summary-Endpoint für Uptime Kuma melden dann "veraltet".
    _loop("system_monitor", "maintenance", settings.system_monitor_interval_seconds / 60),
    # Takt kommt aus abgabebox-backend/app/config.py (ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES,
    # Default 30) - das Backend kennt die Einstellung nicht, darum hier mit Reserve.
    JobDefinition(
        name="abgabebox_quarantine_cleanup",
        kind="loop",
        service="abgabebox-backend",
        category="cleanup",
        interval_seconds=30 * 60,
        max_silence_seconds=3 * 60 * 60,
    ),
    # Läuft nur, wenn es Analyse-Aufträge gibt; überwacht wird darum der Heartbeat aus der
    # Poll-Schleife (alle PHOTO_WORKER_POLL_INTERVAL_SECONDS, Default 10 s), nicht die Läufe.
    # Host-Cronjobs (crontab des Deploy-Users, siehe RUNBOOK Abschnitt 10), gestartet über
    # scripts/run_job.sh. Solange sie nicht eingerichtet sind, zeigt die Seite "Nie gelaufen" -
    # ohne Alarm (system_alert_service meldet never_run nur für Loops/Worker).
    JobDefinition(
        name="backup_db",
        kind="host_cron",
        service="host",
        category="backup",
        interval_seconds=24 * 60 * 60,
        max_silence_seconds=26 * 60 * 60,
    ),
    JobDefinition(
        name="cleanup_storage",
        kind="host_cron",
        service="host",
        category="cleanup",
        interval_seconds=24 * 60 * 60,
        max_silence_seconds=26 * 60 * 60,
    ),
    JobDefinition(
        name="photo_analysis_worker",
        kind="worker",
        service="photo-analysis-worker",
        category="photo_analysis",
        interval_seconds=None,
        max_silence_seconds=5 * 60,
    ),
)

JOBS_BY_NAME: dict[str, JobDefinition] = {job.name: job for job in JOB_DEFINITIONS}
assert len(JOBS_BY_NAME) == len(JOB_DEFINITIONS), "duplicate job name in JOB_DEFINITIONS"

_missing_loops = set(BACKGROUND_LOCK_IDS) - {job.name for job in JOB_DEFINITIONS if job.service == "backend"}
assert not _missing_loops, f"BACKGROUND_LOCK_IDS has loop(s) without a JOB_DEFINITIONS entry: {sorted(_missing_loops)}"
