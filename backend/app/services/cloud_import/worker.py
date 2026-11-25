"""Hintergrundverarbeitung des Datei-Imports (Loop ``cloud_import`` im job-worker).

Je Tick:
1. Aufräumen: nie gestartete Aufträge nach 7 Tagen verwerfen, liegengebliebene Ordner-Uploads
   abschliessen, Berichte ohne importierte Datei löschen (E-12), Staging verwaister Aufträge weg.
2. Aufträge abarbeiten: Claim per ``FOR UPDATE SKIP LOCKED`` mit Lease (ein abgestürzter Worker
   gibt den Auftrag nach LEASE automatisch frei), faire Reihenfolge (am längsten nicht bedienter
   Auftrag zuerst - je Mandant läuft höchstens einer), Zeitscheibe SLICE_SECONDS je Auftrag.

Ein Batch = Dateien mit gleichem Regel-Ergebnis (group_key: Art, Tags, Schätzdatum). Er läuft
durch FileService.save_gallery_uploads bzw. save_document_uploads - Virenscan, Magic-Byte,
Grössenlimit, Duplikate, Kontingent, HEIC, Thumbnails, Auto-Termin wie bei jedem Upload. Der
Status der Import-Einträge wird im before_commit-Hook in derselben Transaktion geschrieben wie
die neuen Dateien: eine Wiederaufnahme nach einem Absturz verarbeitet nie etwas doppelt.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
import zipfile
import zlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import PhotoAlbum, StoredFile
from app.models.import_entities import IMPORT_JOB_TERMINAL_STATUSES, ImportItem, ImportJob
from app.services.audit_service import AuditService
from app.services.cloud_import import jobs, paths
from app.services.file_service import FileService, _gallery_job_viewer
from app.services.upload_lock import UploadLockBusy

_logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
SLICE_SECONDS = 60
MAX_CLAIMS_PER_TICK = 20
IMAGE_BATCH_FILES = 4  # wie FileService.GALLERY_INGEST_BATCH_SIZE (Speicher: je Bild bis 100 MB)
DOCUMENT_BATCH_FILES = 10
BATCH_CANDIDATES = 40
MAX_ATTEMPTS = 3
UPLOAD_IDLE_TIMEOUT = timedelta(days=7)
REPORT_MIN_AGE = timedelta(days=7)
# listing: API-Quellen listen im Worker (services/cloud_import/remote.py)
ACTIVE_WORK_STATUSES = ("listing", "queued", "running", "cancel_requested")

_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Statistik nach grossen Importen auffrischen (Hinweis aus fix/search-perf-1.5.1): alle
# ANALYZE_EVERY_FILES neu importierten Dateien und am Ende eines Auftrags.
ANALYZE_EVERY_FILES = 5000
_imported_since_analyze: dict[uuid.UUID, int] = {}


def analyze_upload_tables(db: Session) -> None:
    """ANALYZE stored_file, gallery_image, photo_search_doc über die SECURITY-DEFINER-Funktion aus
    Migration 0230. Best-Effort: ein Fehler wird nur geloggt, der Import bleibt gültig."""
    try:
        db.execute(text("SELECT public.hocx_analyze_upload_tables()"))
        db.commit()
    except Exception:  # noqa: BLE001 - nur Planner-Statistik; Autoanalyze holt es ohnehin nach
        db.rollback()
        _logger.warning("ANALYZE nach Datei-Import fehlgeschlagen", exc_info=True)


def _note_imported(db: Session, job: ImportJob, count: int) -> None:
    if count <= 0:
        return
    total = _imported_since_analyze.get(job.id, 0) + count
    if total >= ANALYZE_EVERY_FILES:
        analyze_upload_tables(db)
        total = 0
    _imported_since_analyze[job.id] = total


class _Slice:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + SLICE_SECONDS
        self.archives: dict[int, tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]] = {}
        self.touched_albums: set[uuid.UUID] = set()

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline

    def close(self) -> None:
        for archive, _infos in self.archives.values():
            archive.close()
        self.archives.clear()


def process_pending(db: Session) -> None:
    """Task des Loops (run_advisory_locked_loop: synchron im Worker-Thread)."""
    service = FileService()
    bind_tenant_scope(db, None)  # Aufräumen und Claim mandantenübergreifend (Systemjob)
    cleanup(db)
    served: set[uuid.UUID] = set()
    for _ in range(MAX_CLAIMS_PER_TICK):
        bind_tenant_scope(db, None)
        job = claim_next(db)
        if job is None or job.id in served:
            if job is not None:
                release(db, job)
            break
        served.add(job.id)
        run_slice(db, service, job)
    bind_tenant_scope(db, None)


def claim_next(db: Session) -> ImportJob | None:
    current = jobs.now()
    job = db.scalar(
        select(ImportJob)
        .where(
            ImportJob.status.in_(ACTIVE_WORK_STATUSES),
            (ImportJob.lease_until.is_(None)) | (ImportJob.lease_until < current),
            # Anbieter drosselt (Retry-After): erst danach wieder bedienen
            (ImportJob.not_before.is_(None)) | (ImportJob.not_before <= current),
        )
        .order_by(ImportJob.served_at.asc().nulls_first(), ImportJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.commit()  # nur gelesen
        return None
    job.lease_owner = _WORKER_ID
    job.lease_until = current + LEASE
    job.served_at = current
    db.commit()
    return job


def release(db: Session, job: ImportJob) -> None:
    db.refresh(job)
    if job.lease_owner == _WORKER_ID:
        job.lease_owner = None
        job.lease_until = None
    db.commit()


def run_slice(db: Session, service: FileService, job: ImportJob) -> None:
    # Zweites Sicherheitsnetz: ab hier nur der Mandant des Auftrags (RLS wie ein Request).
    bind_tenant_scope(db, job.tenant_id)
    work = _Slice()
    try:
        if job.status == "cancel_requested":
            _finish_cancel(db, job)
            return
        if job.status == "listing":
            from app.services.cloud_import import remote

            remote.run_listing(db, job, work.expired)
            return
        if job.status == "queued":
            job.status = "running"
            db.commit()
        from app.services.cloud_import import remote

        remote_source = remote.is_remote(job)
        while not work.expired():
            db.refresh(job)
            if job.status == "cancel_requested":
                _finish_cancel(db, job)
                return
            if job.status != "running":
                return
            fetched = None
            if remote_source:
                # API-Quelle: erst herunterladen (Stream auf Platte), dann dieselbe Pipeline wie P0
                fetched = remote.download_step(db, job)
                if fetched == "paused":
                    return
            batch = _next_batch(db, job)
            if not batch:
                if fetched == "downloaded":
                    continue
                _maybe_finish(db, job)
                return
            if not _process_batch(db, service, job, batch, work):
                return
            job.lease_until = jobs.now() + LEASE
            db.commit()
    except UploadLockBusy:
        # Upload-Lock des Mandanten länger belegt - nächster Tick versucht es erneut.
        db.rollback()
    except Exception as exc:  # noqa: BLE001 - Hintergrundjob: selbst ins Fehlerprotokoll
        from app.core.error_log import record_system_error

        db.rollback()
        record_system_error(db, exc=exc, tenant_id=job.tenant_id)
    finally:
        work.close()
        if work.touched_albums:
            _recompute_albums(db, service, work.touched_albums)
        try:
            release(db, job)
        except Exception as exc:  # noqa: BLE001
            from app.core.error_log import record_system_error

            db.rollback()
            record_system_error(db, exc=exc, tenant_id=job.tenant_id)


def _ready_status(job: ImportJob) -> str:
    return "queued" if job.source == "zip" else "staged"


def _next_batch(db: Session, job: ImportJob) -> list[ImportItem]:
    ready = _ready_status(job)
    first = db.scalar(
        select(ImportItem).where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == ready)
        .order_by(ImportItem.id).limit(1)
    )
    if first is None:
        return []
    candidates = db.scalars(
        select(ImportItem)
        .where(
            ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == ready,
            ImportItem.group_key == first.group_key, ImportItem.kind == first.kind,
        )
        .order_by(ImportItem.id)
        .limit(BATCH_CANDIDATES)
    )
    limit = IMAGE_BATCH_FILES if first.kind == paths.KIND_IMAGE else DOCUMENT_BATCH_FILES
    batch: list[ImportItem] = []
    names: set[str] = set()
    for item in candidates:
        # Ergebnisse der Pipeline kommen je Dateiname zurück - gleiche Namen (andere Ordner)
        # landen deshalb in verschiedenen Batches.
        name = paths.file_name(item.path)
        if name in names:
            continue
        names.add(name)
        batch.append(item)
        if len(batch) >= limit:
            break
    return batch


def _read_zip_entry(job: ImportJob, item: ImportItem, work: _Slice) -> bytes | str:
    """Bytes eines Eintrags oder ein Fehlercode. Gelesen wird höchstens Limit+1 Byte - die
    angegebene Grösse im ZIP zählt nicht (Zip-Bomb-Schutz), der Name nie als Pfad (Zip-Slip)."""
    if item.archive_index is None or item.entry_index is None or item.archive_index >= len(job.archives):
        return "internal"
    cached = work.archives.get(item.archive_index)
    if cached is None:
        archive_path = Path(settings.storage_root) / job.archives[item.archive_index]["path"]
        try:
            archive = zipfile.ZipFile(archive_path)
        except (zipfile.BadZipFile, OSError) as exc:
            _logger.warning("Import-Archiv nicht lesbar: %s", type(exc).__name__)
            return "source_gone"
        cached = (archive, archive.infolist())
        work.archives[item.archive_index] = cached
    archive, infos = cached
    if item.entry_index >= len(infos):
        return "corrupt_entry"
    info = infos[item.entry_index]
    if info.flag_bits & 0x1:
        return "encrypted"
    limit = paths.MAX_BYTES_BY_KIND[item.kind]
    # Nie mehr als Grenze+1 und nie mehr als angegeben+1 entpacken (Zip-Bomb: Speicher und Rechenzeit)
    try:
        with archive.open(info) as source:
            content = source.read(min(limit, int(info.file_size)) + 1)
    except (zipfile.BadZipFile, zlib.error, OSError, RuntimeError, NotImplementedError, EOFError, ValueError):
        return "corrupt_entry"
    if len(content) > limit:
        return "too_large"
    if len(content) > info.file_size:
        return "corrupt_entry"
    return content


def _read_staged(item: ImportItem) -> bytes | str | None:
    """None: gestagte Datei fehlt - der Eintrag wird erneut zum Hochladen freigegeben."""
    if not item.staged_path:
        return None
    path = Path(settings.storage_root) / item.staged_path
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size > paths.MAX_BYTES_BY_KIND[item.kind]:
        return "too_large"
    return path.read_bytes()


def _unlink_staged(items: list[ImportItem]) -> None:
    for item in items:
        if item.staged_path:
            (Path(settings.storage_root) / item.staged_path).unlink(missing_ok=True)


def _process_batch(db: Session, service: FileService, job: ImportJob, batch: list[ImportItem], work: _Slice) -> bool:
    """Ein Batch durch die Pipeline. False = Auftrag pausiert (Kontingent voll)."""
    first = batch[0]
    viewer = _gallery_job_viewer(db, job)
    if not _requester_allowed(viewer, first.kind):
        # Konto gesperrt/ausgetreten oder Rechte entzogen: nicht im Namen dieser Person weiterimportieren
        job.status = "failed"
        job.error = "requester_unauthorized"
        job.finished_at = jobs.now()
        from app.services import upload_job_service

        upload_job_service.finish_import_job(db, job)
        _notify_end(db, job)
        AuditService().log(
            db, action="file_import.stopped_unauthorized", actor_user_id=job.requested_by, tenant_id=job.tenant_id,
            entity_type="import_job", details={"job_id": str(job.id)}, commit=False,
        )
        db.commit()
        return False
    files: list[tuple[str, bytes]] = []
    by_name: dict[str, ImportItem] = {}
    read_failures: list[ImportItem] = []
    staged_items = [item for item in batch if item.staged_path]
    for item in batch:
        content = _read_zip_entry(job, item, work) if job.source == "zip" else _read_staged(item)
        if content is None:
            item.status = "queued"
            item.staged_path = None
            continue
        if isinstance(content, str):
            item.status = "failed"
            item.result_code = content
            read_failures.append(item)
            continue
        name = paths.file_name(item.path)
        files.append((name, content))
        by_name[name] = item
    if read_failures:
        from app.services import upload_job_service

        upload_job_service.record_items(
            db, upload_job_service.import_job_for(db, job),
            [upload_job_service.ItemIn(status="failed", name=paths.file_name(item.path), reason_code=item.result_code) for item in read_failures],
        )
    if not files:
        _unlink_staged(staged_items)
        job.last_progress_at = jobs.now()
        db.commit()
        return True

    results: list[dict] = []
    first = batch[0]

    def apply_results(*_args) -> None:
        _apply_results(db, job, by_name, results, work, viewer)

    try:
        if first.kind == paths.KIND_IMAGE:
            asyncio.run(
                service.save_gallery_uploads(
                    db, tenant_id=job.tenant_id, files=files, tags=list(first.tags or []), created_by=job.requested_by,
                    estimated_taken_on=first.estimated_date, include_gps=job.include_gps, file_results=results,
                    before_commit=apply_results, viewer=viewer,
                )
            )
        else:
            asyncio.run(
                service.save_document_uploads(
                    db, tenant_id=job.tenant_id, files=files, tags=list(first.tags or []), created_by=job.requested_by,
                    file_results=results, viewer=viewer, include_gps=job.include_gps, before_commit=apply_results,
                )
            )
            db.commit()  # Nur-Duplikate-Fall: save_document_uploads committet dann nicht selbst
    except UploadLockBusy:
        raise
    except Exception as exc:  # noqa: BLE001 - einzelner Batch: Fehlerprotokoll, Versuche zählen
        from app.core.error_log import record_system_error

        db.rollback()
        record_system_error(db, exc=exc, tenant_id=job.tenant_id)
        for item in by_name.values():
            db.refresh(item)
            item.attempts += 1
            if item.attempts >= MAX_ATTEMPTS:
                item.status = "failed"
                item.result_code = "internal"
        db.commit()
        return True
    _unlink_staged(staged_items)
    _note_imported(db, job, sum(1 for item in by_name.values() if item.status == "imported"))
    if any(item.result_code == "quota_exceeded" for item in by_name.values()):
        job.status = "failed"
        job.error = "quota_exceeded"
        job.finished_at = jobs.now()
        from app.services import upload_job_service

        upload_job_service.finish_import_job(db, job)
        _notify_end(db, job)
        db.commit()
        return False
    return True


def _requester_allowed(viewer, kind: str) -> bool:
    from app.core.permissions import P

    area = P.PHOTOS_MANAGE if kind == paths.KIND_IMAGE else P.FILES_MANAGE
    return viewer.can(P.FILES_IMPORT) and viewer.can(area)


_STATUS_BY_RESULT = {"uploaded": "imported", "skipped": "duplicate", "metadata_updated": "duplicate", "failed": "failed"}


def _apply_results(
    db: Session, job: ImportJob, by_name: dict[str, ImportItem], results: list[dict], work: _Slice, viewer=None
) -> None:
    """Pipeline-Ergebnis je Datei → Import-Eintrag, Alben; läuft vor dem Commit der Pipeline.
    Upload-Verlauf (0250): der Import ist ein Vorgang ``cloud_import``; die Items entstehen in
    derselben Transaktion wie die Dateien."""
    from app.services import upload_job_service

    upload_job_service.record_results(db, upload_job_service.import_job_for(db, job), results)
    seen: set[str] = set()
    imported_public: dict[str, ImportItem] = {}
    duplicate_public: dict[str, ImportItem] = {}
    for result in results:
        item = by_name.get(result.get("name") or "")
        if item is None or result["name"] in seen:
            continue
        seen.add(result["name"])
        status = _STATUS_BY_RESULT.get(result.get("status") or "", "failed")
        item.status = status
        item.staged_path = None
        if status == "failed":
            item.result_code = result.get("code") or "rejected"
        elif status == "duplicate":
            item.result_code = "duplicate"
            if result.get("file_id"):
                duplicate_public[result["file_id"]] = item
        elif result.get("file_id"):
            imported_public[result["file_id"]] = item
    for name, item in by_name.items():
        if name not in seen:
            item.status = "failed"
            item.result_code = "internal"
            item.staged_path = None
    if imported_public:
        rows = db.execute(
            select(StoredFile.id, StoredFile.public_id).where(
                StoredFile.tenant_id == job.tenant_id, StoredFile.public_id.in_([uuid.UUID(key) for key in imported_public])
            )
        )
        for stored_id, public_id in rows:
            imported_public[str(public_id)].stored_file_id = stored_id
        _assign_albums(db, job, [(uuid.UUID(key), item) for key, item in imported_public.items()], work)
    if duplicate_public and viewer is not None:
        _enrich_duplicates(db, job, duplicate_public, work, viewer)
    job.last_progress_at = jobs.now()
    job.lease_until = jobs.now() + LEASE
    jobs.touch(job)
    db.flush()


def _enrich_duplicates(db: Session, job: ImportJob, duplicates: dict[str, ImportItem], work: _Slice, viewer) -> None:
    """Bereits vorhandene Dateien (User-Entscheid 2026-11-22): Tags und Alben des Regel-Ergebnisses
    nur ergänzen, nie entfernen oder überschreiben. Nur Dateien, die die auftraggebende Person sieht
    (die Pipeline meldet nur sichtbare) und verwalten darf, nur im eigenen Mandanten."""
    from fastapi import HTTPException

    from app.services.access_service import AccessService
    from app.services.cloud_import.rules import normalize_tags
    from app.services.file_service import BLOCKED_SCAN_STATUSES
    from app.services.file_trash_service import may_manage

    access = AccessService()
    files = {
        str(stored.public_id): stored
        for stored in db.scalars(
            select(StoredFile)
            .where(StoredFile.tenant_id == job.tenant_id, StoredFile.public_id.in_([uuid.UUID(key) for key in duplicates]))
            .with_for_update()  # Tags lesen-ergänzen-schreiben ohne verlorene parallele Änderung (Review N3)
        )
    }
    album_targets: list[tuple[uuid.UUID, ImportItem]] = []
    for key, item in duplicates.items():
        stored = files.get(key)
        if stored is None or not may_manage(viewer, stored.mime_type):
            continue
        # Gleiche Schreibprüfung wie bulk-tags/Album-Einträge (nur Rollenrechte, z. B. keine Bilder
        # aus nicht lesbaren Protokollen) - Review M1
        try:
            access.ensure_can_read_stored_file(db, viewer, stored.id, allow_context_grant=False)
        except HTTPException:
            continue
        item.existing_file_id = stored.id
        changed = False
        current = list(stored.tags or [])
        merged = normalize_tags([*current, *(item.tags or [])])
        if merged != current and set(current) <= set(merged):
            stored.tags = merged
            changed = True
        if item.kind == paths.KIND_IMAGE and item.albums and stored.scan_status not in BLOCKED_SCAN_STATUSES:
            album_targets.append((stored.public_id, item))
            changed = True
        if changed:
            item.result_code = "duplicate_enriched"
    if album_targets:
        _assign_albums(db, job, album_targets, work, existing=True)


def _album_for_key(db: Session, job: ImportJob, key: str) -> PhotoAlbum | None:
    kind, _sep, value = key.partition(":")
    if kind == "id":
        try:
            album_id = uuid.UUID(value)
        except ValueError:
            return None
        return db.scalar(
            select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == job.tenant_id, PhotoAlbum.kind == "manual")
        )
    if kind != "name" or not value:
        return None
    known = (job.album_map or {}).get(value)
    if known:
        album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == uuid.UUID(known), PhotoAlbum.tenant_id == job.tenant_id))
        if album is not None:
            return album
    # Gleichnamiges eigenes Album wiederverwenden (User-Entscheid 2026-11-22): exakter Name, bei
    # mehreren das älteste; nur manuelle Alben des eigenen Mandanten, nie Partner-Alben.
    existing = jobs.manual_albums_by_name(db, job.tenant_id, {value}).get(value, [])
    if existing:
        album = existing[0]
    else:
        album = PhotoAlbum(tenant_id=job.tenant_id, name=value, kind="manual")
        db.add(album)
        db.flush()
    job.album_map = {**(job.album_map or {}), value: str(album.id)}
    job.album_report = {**(job.album_report or {}), value: {"reused": bool(existing), "candidates": len(existing)}}
    return album


def _assign_albums(
    db: Session, job: ImportJob, imported: list[tuple[uuid.UUID, ImportItem]], work: _Slice, *, existing: bool = False
) -> None:
    """existing=True (Duplikate): nur hinzufügen - ein schon vorhandener Album-Eintrag bleibt unverändert."""
    from app.services import photo_album_service  # Importzyklus wie in file_service

    by_key: dict[str, list[uuid.UUID]] = {}
    for public_id, item in imported:
        for key in item.albums or []:
            by_key.setdefault(key, []).append(public_id)
    for key, file_ids in by_key.items():
        album = _album_for_key(db, job, key)
        if album is None:
            continue
        photo_album_service.add_items(db, album, file_ids, manual=not existing)
        work.touched_albums.add(album.id)


def _recompute_albums(db: Session, service: FileService, album_ids: set[uuid.UUID]) -> None:
    from app.services import photo_album_service

    try:
        photo_album_service.recompute_best_of_for_albums(db, service, album_ids)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - Bestenauswahl ist nachrangig, der Import bleibt gültig
        from app.core.error_log import record_system_error

        db.rollback()
        record_system_error(db, exc=exc)


def _remaining(db: Session, job: ImportJob, *statuses: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(ImportItem).where(
                ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status.in_(statuses)
            )
        )
        or 0
    )


def _maybe_finish(db: Session, job: ImportJob) -> None:
    """Nichts mehr bereit: fertig - ausser eine Ordner-Quelle wartet noch auf Dateien aus dem Browser."""
    waiting = _remaining(db, job, "queued", "staged", "listed")
    if waiting:
        idle_since = job.last_progress_at or job.started_at or job.updated_at
        if job.source != "folder" or idle_since is None or jobs.now() - idle_since < UPLOAD_IDLE_TIMEOUT:
            db.commit()
            return
        db.execute(
            update(ImportItem)
            .where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status.in_(("queued", "listed")))
            .values(status="failed", result_code="not_uploaded")
        )
    _finish(db, job, "done")


def _finish(db: Session, job: ImportJob, status: str) -> None:
    from app.services import upload_job_service

    upload_job_service.finish_import_job(db, job)
    job.status = status
    job.finished_at = jobs.now()
    job.archives = []
    jobs.touch(job)
    _release_remote(db, job)
    _notify_end(db, job)
    by_status, _codes, _bytes = jobs.status_counts(db, job)
    AuditService().log(
        db, action=f"file_import.{'finished' if status == 'done' else status}", actor_user_id=job.requested_by,
        tenant_id=job.tenant_id, entity_type="import_job", details={"job_id": str(job.id), "source": job.source, "counts": by_status},
        commit=False,
    )
    db.commit()
    jobs.remove_staging(job)
    _after_job_end(db, job)


def _notify_end(db: Session, job: ImportJob) -> None:
    """Mail «Import abgeschlossen/unterbrochen» an die auslösende Person (Plan §9, alle Quellen)."""
    from app.notifications import cloud_import as cloud_import_notifications

    cloud_import_notifications.on_job_end(db, job)


def _release_remote(db: Session, job: ImportJob) -> None:
    """API-Quelle beendet: Tokens sofort löschen (Plan §5.5)."""
    from app.services.cloud_import import remote

    if remote.is_remote(job):
        remote.release_connection(db, job)


def _after_job_end(db: Session, job: ImportJob) -> None:
    """Am Ende eines Auftrags mit neuen Dateien die Statistik auffrischen."""
    _imported_since_analyze.pop(job.id, None)
    if (job.started_at is not None) and _remaining(db, job, "imported"):
        analyze_upload_tables(db)


def _finish_cancel(db: Session, job: ImportJob) -> None:
    from app.services import upload_job_service

    upload_job_service.finish_import_job(db, job, cancelled=True)
    jobs.finalize_cancel(db, job)
    _release_remote(db, job)
    AuditService().log(
        db, action="file_import.cancelled", actor_user_id=job.requested_by, tenant_id=job.tenant_id,
        entity_type="import_job", details={"job_id": str(job.id), "source": job.source}, commit=False,
    )
    db.commit()
    _after_job_end(db, job)


def cleanup(db: Session) -> None:
    """Aufräumen (läuft mandantenübergreifend, gibt nichts zurück)."""
    try:
        jobs.expire_stale_drafts(db)
        db.commit()
        # API-Quellen: wer sich 7 Tage nicht neu anmeldet, dessen Auftrag gilt als unterbrochen;
        # Verbindungen nach purge_after löschen (Tokens weg)
        from app.services.cloud_import import connections, remote

        remote.expire_reauth(db)
        db.commit()
        connections.purge_expired(db)
        db.commit()
        # Fehlgeschlagene Aufträge, die 7 Tage nicht fortgesetzt wurden: Quelle verwerfen.
        stale_failed = list(
            db.scalars(
                select(ImportJob).where(
                    ImportJob.status == "failed", ImportJob.finished_at < jobs.now() - UPLOAD_IDLE_TIMEOUT,
                    ImportJob.archives != text("'[]'::jsonb"),
                )
            )
        )
        for job in stale_failed:
            job.archives = []
            db.execute(
                update(ImportItem)
                .where(ImportItem.job_id == job.id, ImportItem.status.in_(("listed", "queued", "staged")))
                .values(status="cancelled", staged_path=None)
            )
            jobs.remove_staging(job)
        db.commit()
        # Bericht (E-12): bleibt, solange mindestens eine importierte Datei existiert; ein Auftrag
        # ohne importierte Datei bleibt REPORT_MIN_AGE sichtbar, damit das Ergebnis lesbar ist.
        has_file = exists().where(ImportItem.job_id == ImportJob.id, ImportItem.stored_file_id.is_not(None))
        db.execute(
            delete(ImportJob).where(
                ImportJob.status.in_(IMPORT_JOB_TERMINAL_STATUSES),
                ImportJob.finished_at < jobs.now() - REPORT_MIN_AGE,
                ~has_file,
            )
        )
        db.commit()
        _sweep_orphan_staging(db)
    except Exception as exc:  # noqa: BLE001
        from app.core.error_log import record_system_error

        db.rollback()
        record_system_error(db, exc=exc)


def _sweep_orphan_staging(db: Session) -> None:
    root = Path(settings.upload_root) / "_staging" / "cloud-import"
    if not root.is_dir():
        return
    # «failed» zählt mit: ein unterbrochener Auftrag lässt sich 7 Tage fortsetzen (danach räumt cleanup).
    live = {
        str(job_id)
        for job_id in db.scalars(select(ImportJob.id).where(ImportJob.status.not_in(("cancelled", "done"))))
    }
    cutoff = time.time() - 24 * 60 * 60
    for directory in root.iterdir():
        if directory.name in live or not directory.is_dir():
            continue
        try:
            if directory.stat().st_mtime < cutoff:
                import shutil

                shutil.rmtree(directory, ignore_errors=True)
        except FileNotFoundError:
            continue
