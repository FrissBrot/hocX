"""Verzeichnis aller periodischen Jobs, die /admin/jobs anzeigt und (ab Phase 3) per ntfy überwacht.

Was ein Job tatsächlich gemeldet hat, steht in system_job_status (Migration 0105). Hier steht,
was es geben *sollte*: so fällt auch ein Job auf, der nie gelaufen ist (z. B. ein Loop, der beim
Start an einem KeyError stirbt - siehe die Vorfälle in background_loops.py - oder ein Cronjob,
der nie eingetragen wurde). Jobs, die melden, aber hier fehlen, zeigt die Seite trotzdem an
(als "nicht registriert"), damit ein neuer Host-Cronjob sofort sichtbar ist.

Jeder Schlüssel in BACKGROUND_LOCK_IDS braucht hier einen Eintrag - das prüft der Import unten,
genauso wie die Eindeutigkeit der Lock-IDs in background_loops.py."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from app.core.background_loops import BACKGROUND_LOCK_IDS
from app.core.config import settings

JobKind = Literal["loop", "worker", "host_cron"]
JobCategory = Literal["virus_scan", "photo_analysis", "uploads", "cleanup", "maintenance", "backup", "storage", "documents"]
JobService = Literal["backend", "abgabebox-backend", "photo-analysis-worker", "storage-worker", "backup-worker", "document-worker", "host"]

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
    # Läuft auch während voller Wartung weiter (Überwachung, Wartungssteuerung). Alle anderen
    # Backend-Loops pausieren dann (run_advisory_locked_loop), damit kein Hintergrundjob
    # während einer Erstmigration Daten verändert.
    runs_during_maintenance: bool = False


def _loop(
    name: str, category: JobCategory, interval_minutes: float, *, max_silence_seconds: int | None = None,
    runs_during_maintenance: bool = False,
) -> JobDefinition:
    interval_seconds = int(interval_minutes * 60)
    return JobDefinition(
        name=name,
        kind="loop",
        service="backend",
        category=category,
        interval_seconds=interval_seconds,
        max_silence_seconds=max_silence_seconds or max(interval_seconds * 3, _MIN_MAX_SILENCE_SECONDS),
        keep_history=interval_seconds >= 60,
        runs_during_maintenance=runs_during_maintenance,
    )


JOB_DEFINITIONS: tuple[JobDefinition, ...] = (
    _loop("upload_pipeline_rescan", "virus_scan", settings.upload_pipeline_rescan_interval_minutes),
    _loop("abgabebox_rescan", "virus_scan", settings.abgabebox_rescan_interval_minutes),
    # Ein grosser ZIP-Import kann einen einzelnen Tick lange blockieren - 3 x 5 s wäre ein Fehlalarm.
    _loop("gallery_upload_ingest", "uploads", 5 / 60, max_silence_seconds=60 * 60),
    # Vereinsexport (Datenschutz-Audit Paket 6): ein grosser Export mit allen Fotos kann Stunden dauern.
    _loop("tenant_data_export", "documents", 1, max_silence_seconds=6 * 60 * 60),
    _loop("retention_proposals", "cleanup", 24 * 60),
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
    _loop("task_package_rollover", "maintenance", settings.task_package_rollover_interval_minutes),
    _loop("export_cleanup", "cleanup", settings.export_cleanup_interval_minutes),
    _loop("log_cleanup", "cleanup", settings.log_cleanup_interval_minutes),
    # Sammelt den Systemstatus und verschickt ntfy-Alarme. Hängt er, fällt das nicht hier auf
    # (er wertet sich selbst aus), sondern über den veralteten Snapshot: Seite und der
    # Summary-Endpoint für Uptime Kuma melden dann "veraltet".
    _loop("system_monitor", "maintenance", settings.system_monitor_interval_seconds / 60, runs_during_maintenance=True),
    # Steuert geplante/manuelle Wartungsfenster, markiert Überschreitungen und führt Schätzungen
    # nach. Beendet nie eine Wartung (die Freigabe hängt an den Bedingungen).
    _loop(
        "maintenance_supervisor", "maintenance", settings.maintenance_supervisor_interval_seconds / 60,
        runs_during_maintenance=True,
    ),
    # Entfernt alte Einträge des Speicher-Änderungsjournals, die keine offene Migration mehr braucht.
    _loop("storage_journal_cleanup", "storage", 24 * 60),
    # Legt Dokumente für Abgabebox-Uploads und den Bestand an, räumt verwaiste Dokumentdateien auf.
    _loop("document_sync", "documents", settings.document_sync_interval_minutes),
    # Entfernt gelöschte Objekte physisch, sobald die Löschung committet ist (Tombstones, S3-008).
    # Pausiert während voller Wartung; ein Write-Fence beendet den Tick ohne Fehler.
    _loop("storage_purge", "storage", 1),
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
    # Backup-Worker (eigener Container backup-worker, docs-site/docs/technik/backup/): Heartbeat aus
    # der Poll-Schleife plus je Auftragsart ein Lauf. Die Frische der Sicherungen (Intervall
    # überschritten), Repository und Prüfungen überwacht system_health_service (Checks backup*);
    # max_silence ist hier darum bewusst grosszügig - sonst gäbe es zwei Alarme für dasselbe Problem.
    JobDefinition(
        name="backup_worker",
        kind="worker",
        service="backup-worker",
        category="backup",
        interval_seconds=None,
        max_silence_seconds=10 * 60,
    ),
    JobDefinition(
        name="cleanup_storage",
        kind="host_cron",
        service="host",
        category="cleanup",
        interval_seconds=24 * 60 * 60,
        max_silence_seconds=26 * 60 * 60,
    ),
    # Storage-Migrations-Worker (eigener Container storage-worker): Heartbeat aus der Poll-Schleife.
    JobDefinition(
        name="storage_migration_worker",
        kind="worker",
        service="storage-worker",
        category="storage",
        interval_seconds=None,
        max_silence_seconds=5 * 60,
    ),
    # Host-seitiger Controller für den lokalen S3-Container (scripts/storage_controller.sh,
    # Cron alle 5 Minuten über run_job.sh).
    JobDefinition(
        name="storage_controller",
        kind="host_cron",
        service="host",
        category="storage",
        interval_seconds=5 * 60,
        max_silence_seconds=30 * 60,
    ),
    # PDF-Konvertierung und Textextraktion (eigener Container document-worker): Heartbeat aus der
    # Poll-Schleife (spätestens jede Minute, auch während eines langen Auftrags nicht seltener als
    # die Lease-Verlängerung), Läufe nur bei Arbeit.
    JobDefinition(
        name="document_worker",
        kind="worker",
        service="document-worker",
        category="documents",
        interval_seconds=None,
        max_silence_seconds=15 * 60,
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

# Läufe des Backup-Workers - nur registriert, wenn das Borg-Backup eingerichtet ist (sonst
# meldete die Übersicht sie als "nie gelaufen").
_BACKUP_RUN_JOBS: tuple[JobDefinition, ...] = (
    JobDefinition(name="backup_run", kind="worker", service="backup-worker", category="backup",
                  interval_seconds=6 * 60 * 60, max_silence_seconds=7 * 24 * 60 * 60),
    JobDefinition(name="backup_retention", kind="worker", service="backup-worker", category="backup",
                  interval_seconds=24 * 60 * 60, max_silence_seconds=7 * 24 * 60 * 60),
    JobDefinition(name="backup_verify", kind="worker", service="backup-worker", category="backup",
                  interval_seconds=7 * 24 * 60 * 60, max_silence_seconds=21 * 24 * 60 * 60),
    JobDefinition(name="backup_restore_test", kind="worker", service="backup-worker", category="backup",
                  interval_seconds=30 * 24 * 60 * 60, max_silence_seconds=75 * 24 * 60 * 60),
)

# Bisherige Host-Cronjobs (scripts/backup_db.sh, scripts/backup_storage.sh): nur registriert,
# solange das Borg-Backup nicht aktiv ist - danach verweigern die Skripte den Lauf (Umstellung
# siehe RUNBOOK) und dürfen nicht als "überfällig" alarmieren.
_BORG_BACKUP_ENABLED = os.environ.get("BACKUP_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
if _BORG_BACKUP_ENABLED:
    JOB_DEFINITIONS += _BACKUP_RUN_JOBS
else:
    JOB_DEFINITIONS += (
        JobDefinition(
            name="backup_db",
            kind="host_cron",
            service="host",
            category="backup",
            interval_seconds=24 * 60 * 60,
            max_silence_seconds=26 * 60 * 60,
        ),
        # Objekt-Backup der aktiven Speichergeneration nach dem DB-Backup (scripts/backup_storage.sh).
        JobDefinition(
            name="backup_storage",
            kind="host_cron",
            service="host",
            category="backup",
            interval_seconds=24 * 60 * 60,
            max_silence_seconds=26 * 60 * 60,
        ),
    )

JOBS_BY_NAME: dict[str, JobDefinition] = {job.name: job for job in JOB_DEFINITIONS}
assert len(JOBS_BY_NAME) == len(JOB_DEFINITIONS), "duplicate job name in JOB_DEFINITIONS"

_missing_loops = set(BACKGROUND_LOCK_IDS) - {job.name for job in JOB_DEFINITIONS if job.service == "backend"}
assert not _missing_loops, f"BACKGROUND_LOCK_IDS has loop(s) without a JOB_DEFINITIONS entry: {sorted(_missing_loops)}"
