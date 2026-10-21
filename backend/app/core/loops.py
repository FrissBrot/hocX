"""Alle periodischen Hintergrund-Loops (vorher in main.py) und ihre Zuordnung zu Prozessen.

Concurrency-Audit Paket 10: schwere Loops (Galerie-Ingest, Qualitäts-Backfill, Vereinsexport,
Virenscan-Rescans, Thumbnail-Backfill, Album-Sync, Aufräumjobs, PDF-Export-Aufträge) laufen im eigenen Container
job-worker (app/workers/job_worker.py) statt in den uvicorn-Workern - dort konkurrierten sie mit
den Requests um CPU, RAM, Threadpool und DB-Pool aller Mandanten. Leichte Steuer- und
Überwachungsloops bleiben im Backend. Welcher Prozess welchen Loop startet, steht in
BACKEND_LOOPS / JOB_WORKER_LOOPS; job_registry.py ordnet die Jobs demselben Dienst zu.

Jeder Loop läuft über run_advisory_locked_loop (Singleton über alle Prozesse per Advisory Lock),
deshalb ist ein vorübergehendes Doppelstarten (z. B. HOCX_HEAVY_JOBS_IN_BACKEND im Dev) harmlos.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from app.core.background_loops import run_advisory_locked_loop
from app.core.config import settings
from app.services import document_sync_service, domain_health_check_service, erasure_journal, retention_service
from app.services import maintenance_service, photo_album_service, storage_migration_service, system_alert_service
from app.services.admin_error_log_service import AdminErrorLogService
from app.services.admin_job_status_service import AdminJobStatusService
from app.services.audit_service import AuditService
from app.services.file_service import FileService
from app.services.submission_service import SubmissionService
from app.services.table_snapshot_service import TableSnapshotService, run_due_cycle_snapshots
from app.services.task_package_service import run_due_task_packages


async def domain_health_check_loop() -> None:
    """Re-checks active custom domains on an interval. Runs in every uvicorn worker (there's no
    single-instance process in this deployment), so each tick is guarded by a Postgres advisory
    lock - only the worker that acquires it does the check, the other(s) skip that tick."""
    await run_advisory_locked_loop(
        name="domain_health_check",
        interval_seconds=settings.domain_health_check_interval_minutes * 60,
        task=domain_health_check_service.run_health_check,
    )


async def abgabebox_rescan_loop() -> None:
    """Periodic sweep for submission_upload files stuck in scan_status='pending' (ClamAV was
    unreachable at upload time - see abgabebox-backend/app/scanner.py's fail-open comment).
    Same every-worker-but-advisory-locked pattern as domain_health_check_loop above. Stays
    separate from upload_pipeline_rescan_loop below - unlike the three internal upload paths,
    abgabebox files that are still pending sit in a quarantine directory the restricted
    abgabebox DB role can't itself move them out of, so this needs SubmissionService's own
    move-from-quarantine logic, not FileService's."""
    await run_advisory_locked_loop(
        name="abgabebox_rescan",
        interval_seconds=settings.abgabebox_rescan_interval_minutes * 60,
        task=SubmissionService().rescan_all_pending,
    )


async def upload_pipeline_rescan_loop() -> None:
    """Periodic sweep for the three internal upload paths' (protocol image, gallery upload,
    word import) StoredFile rows stuck in scan_status='pending' (ClamAV was unreachable at
    upload time). One consolidated loop instead of three near-identical ones - see
    FileService.rescan_pending_internal_files and the upload-pipeline unification plan."""
    await run_advisory_locked_loop(
        name="upload_pipeline_rescan",
        interval_seconds=settings.upload_pipeline_rescan_interval_minutes * 60,
        task=FileService().rescan_pending_internal_files,
    )


async def export_cleanup_loop() -> None:
    """Periodic retention sweep for old generated export files under EXPORT_ROOT/generated
    (see app/documents/service.py's cleanup_old_generated_exports). Unlike the rescan loops above
    this isn't a stuck/pending-state repair, just age-based deletion - every export run
    writes a brand-new uuid-suffixed file and never reuses an old one, so without this the
    directory grows unbounded on repeated re-exports. Same every-worker-but-advisory-locked
    pattern as the loops above."""
    from app.documents.service import cleanup_old_generated_exports

    await run_advisory_locked_loop(
        name="export_cleanup",
        interval_seconds=settings.export_cleanup_interval_minutes * 60,
        task=cleanup_old_generated_exports,
    )


async def log_cleanup_loop() -> None:
    """Periodic retention sweep for audit_log/system_error_log (audit finding, 2026-08-26:
    neither table had any cleanup, both grew unbounded forever - unlike the export cleanup
    loop above, which already existed). Same every-worker-but-advisory-locked pattern."""
    audit_service = AuditService()
    error_log_service = AdminErrorLogService()
    job_status_service = AdminJobStatusService()

    def _cleanup(db) -> None:
        audit_service.cleanup_old_entries(db, retention_days=settings.audit_log_retention_days)
        error_log_service.cleanup_old_entries(db, retention_days=settings.error_log_retention_days)
        job_status_service.cleanup_old_runs(db, retention_days=settings.job_run_retention_days)
        system_alert_service.cleanup_old_events(db, retention_days=settings.health_event_retention_days)
        retention_service.cleanup(db)
        erasure_journal.purge(db, retention_days=settings.erasure_journal_retention_days)

    await run_advisory_locked_loop(
        name="log_cleanup",
        interval_seconds=settings.log_cleanup_interval_minutes * 60,
        task=_cleanup,
    )


async def cycle_snapshot_loop() -> None:
    """Daily check (see settings.cycle_snapshot_check_interval_minutes): for every
    CycleConfig, creates a table_snapshot for the most recently completed cycle if one
    doesn't exist yet (see table_snapshot_service.run_due_cycle_snapshots for the
    idempotent/self-healing boundary-crossing logic). Same every-worker-but-advisory-
    locked pattern as the loops above - lock id comes from the shared BACKGROUND_LOCK_IDS
    ledger (see app.core.background_loops), which is exactly what a 2026-09-10 incident
    (this loop's lock id copy-pasted from protocol_image_rescan_loop, never changed,
    silently starving one of the two loops every tick) argued for."""
    snapshot_service = TableSnapshotService()
    await run_advisory_locked_loop(
        name="cycle_snapshot",
        interval_seconds=settings.cycle_snapshot_check_interval_minutes * 60,
        task=lambda db: run_due_cycle_snapshots(db, snapshot_service),
    )


async def task_package_rollover_loop() -> None:
    """Täglich: legt für jedes aktive Aufgabenpaket die Aufgaben des laufenden Zyklus an
    (beim Zykluswechsel also die des neuen Zyklus) und ergänzt neue Wiederholungen, z. B.
    neu erfasste Termine. Idempotent - siehe task_package_service.run_due_task_packages."""
    await run_advisory_locked_loop(
        name="task_package_rollover",
        interval_seconds=settings.task_package_rollover_interval_minutes * 60,
        task=lambda db: run_due_task_packages(db),
    )


def _photo_analysis_auto_queue_window_is_open() -> bool:
    hour = datetime.now(timezone.utc).hour
    start, end = settings.photo_analysis_auto_queue_start_hour, settings.photo_analysis_auto_queue_end_hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps past midnight, e.g. 22..5


def _host_load_is_low() -> bool:
    try:
        load_1min, _, _ = os.getloadavg()
    except OSError:
        # Not available on this platform (e.g. Windows) - don't block automatic queuing on
        # a check that can't run; the request-path/worker resource limits are the actual
        # backstop against overload either way.
        return True
    cpu_count = os.cpu_count() or 1
    return load_1min <= cpu_count * settings.photo_analysis_auto_queue_max_load_factor


async def photo_analysis_auto_queue_loop() -> None:
    """Automatically queues Phase 3 (face-quality) analysis for images nobody has manually
    requested it for yet (see FileService.create_pending_analysis_jobs), but only during a
    configured low-traffic UTC hour window and only when the host doesn't already look
    busy - this work competes with live request traffic and the dedicated worker container
    for the same constrained host (see photo-analysis-worker/README.md), so it must never
    fire just because it's due. Routes through run_advisory_locked_loop's should_run gate
    (2026-09-17 audit fix) instead of hand-rolling its own lock/sleep loop - previously this
    was the one loop that reimplemented that skeleton itself, which is exactly how it ended
    up missing the to_thread offload and exception isolation every other loop has."""
    file_service = FileService()
    await run_advisory_locked_loop(
        name="photo_analysis_auto_queue",
        interval_seconds=settings.photo_analysis_auto_queue_interval_minutes * 60,
        task=file_service.create_pending_analysis_jobs,
        should_run=lambda: _photo_analysis_auto_queue_window_is_open() and _host_load_is_low(),
    )


async def photo_quality_backfill_loop() -> None:
    """Fills in sharpness_score/exposure_score for images the abgabebox submission-upload
    path never computes them for (see FileService.backfill_missing_quality_scores) - cheap
    enough per image that this runs continuously, not just in an off-peak window like
    photo_analysis_auto_queue_loop. Same every-worker-but-advisory-locked pattern."""
    file_service = FileService()
    await run_advisory_locked_loop(
        name="photo_quality_backfill",
        interval_seconds=settings.photo_quality_backfill_interval_minutes * 60,
        task=file_service.backfill_missing_quality_scores,
    )


async def photo_album_sync_loop() -> None:
    """Folds newly-submitted (and newly removed) abgabebox submission files into their
    Zyklus/Abgabe/Abgabe-Element albums - see photo_album_service.sync_submission_uploads
    for why this can't happen inline in that public upload request. Same every-worker-but-
    advisory-locked pattern as the loops above."""
    file_service = FileService()
    await run_advisory_locked_loop(
        name="photo_album_sync",
        interval_seconds=settings.photo_album_sync_interval_minutes * 60,
        task=lambda db: photo_album_service.sync_submission_uploads(db, file_service),
    )


async def thumbnail_backfill_loop() -> None:
    """Vorschaubilder für Bilder ohne eigene Vorschau nachziehen, vor allem Abgabebox-Uploads
    (FileService.backfill_missing_thumbnails, CONC-014) - sonst erzeugt die erste Galerie-
    Ansicht sie alle gleichzeitig auf Abruf im Backend."""
    file_service = FileService()
    await run_advisory_locked_loop(
        name="thumbnail_backfill",
        interval_seconds=settings.thumbnail_backfill_interval_minutes * 60,
        task=file_service.backfill_missing_thumbnails,
    )


async def gallery_upload_ingest_loop() -> None:
    """Processes queued gallery_upload_job rows (see FileService.process_pending_gallery_upload_jobs) -
    scanning/thumbnailing/StoredFile-creation for the "Bilder hochladen" window, deferred
    here so a multi-GB ZIP upload request only has to stream bytes to disk and return, not
    hold the whole batch in memory. Unlike photo_analysis_auto_queue_loop, this is a direct
    result of a user action (not ambient background work) and runs continuously with a
    short interval, same as photo_quality_backfill_loop, so a freshly queued upload starts
    within a few seconds rather than waiting for an off-peak window."""
    file_service = FileService()
    await run_advisory_locked_loop(
        name="gallery_upload_ingest",
        interval_seconds=5,
        task=file_service.process_pending_gallery_upload_jobs,
    )


async def tenant_data_export_loop() -> None:
    """Baut bestellte Vereinsexporte und löscht abgelaufene (services/data_export/tenant.py)."""
    from app.services.data_export import tenant as tenant_data_export_service

    await run_advisory_locked_loop(
        name="tenant_data_export",
        interval_seconds=60,
        task=tenant_data_export_service.process_pending,
    )


async def retention_proposals_loop() -> None:
    """Aufbewahrungsfristen der Vereine: Vorschläge anlegen, bei auto_apply umsetzen
    (services/tenant_retention_service.py)."""
    from app.services import tenant_retention_service

    await run_advisory_locked_loop(
        name="retention_proposals",
        interval_seconds=24 * 60 * 60,
        task=tenant_retention_service.run_job,
    )


async def system_monitor_loop() -> None:
    """Systemstatus sammeln (Container, Dienste) und bei Statuswechseln per ntfy benachrichtigen -
    siehe system_health_service/system_alert_service. Same every-worker-but-advisory-locked
    pattern as the loops above."""
    await run_advisory_locked_loop(
        name="system_monitor",
        interval_seconds=settings.system_monitor_interval_seconds,
        task=system_alert_service.run_monitor_tick,
    )


async def maintenance_supervisor_loop() -> None:
    """Wartungsfenster steuern (geplante Starts, Überschreitungen, Neuschätzung) - läuft auch
    während voller Wartung, siehe job_registry.runs_during_maintenance."""
    await run_advisory_locked_loop(
        name="maintenance_supervisor",
        interval_seconds=settings.maintenance_supervisor_interval_seconds,
        task=maintenance_service.supervise,
    )


async def storage_journal_cleanup_loop() -> None:
    """Alte Einträge des Speicher-Änderungsjournals entfernen (nie solche, die eine offene
    Migration noch nachziehen muss)."""
    await run_advisory_locked_loop(
        name="storage_journal_cleanup",
        interval_seconds=24 * 60 * 60,
        task=storage_migration_service.cleanup_journal,
    )


async def document_sync_loop() -> None:
    """Dokumente für Abgabebox-Uploads und den Bestand anlegen, verwaiste Dokumentdateien
    entfernen (app/services/document_sync_service.py). Die eigentliche Verarbeitung macht der
    document-worker."""
    await run_advisory_locked_loop(
        name="document_sync",
        interval_seconds=settings.document_sync_interval_minutes * 60,
        task=document_sync_service.run_tick,
    )


async def storage_purge_loop() -> None:
    """Gelöschte Objekte nach dem Commit physisch entfernen (Tombstones, S3-008)."""
    await run_advisory_locked_loop(
        name="storage_purge",
        interval_seconds=60,
        task=storage_migration_service.purge_deleted_objects,
    )


LoopFactory = Callable[[], Coroutine[Any, Any, None]]

# Leicht: Steuerung, Überwachung, kurze Abfragen - bleiben in den uvicorn-Workern.
BACKEND_LOOPS: tuple[LoopFactory, ...] = (
    domain_health_check_loop,
    cycle_snapshot_loop,
    task_package_rollover_loop,
    photo_analysis_auto_queue_loop,
    retention_proposals_loop,
    system_monitor_loop,
    maintenance_supervisor_loop,
    storage_journal_cleanup_loop,
    document_sync_loop,
    storage_purge_loop,
)

# Schwer: CPU, Speicher, ClamAV, lange Transaktionen oder grosse Löschläufe - job-worker.
JOB_WORKER_LOOPS: tuple[LoopFactory, ...] = (
    abgabebox_rescan_loop,
    upload_pipeline_rescan_loop,
    export_cleanup_loop,
    log_cleanup_loop,
    photo_quality_backfill_loop,
    thumbnail_backfill_loop,
    photo_album_sync_loop,
    gallery_upload_ingest_loop,
    tenant_data_export_loop,
)
