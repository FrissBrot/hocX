"""Altbestand des Upload-Verlaufs rekonstruieren (User-Entscheid E-7, Plan Abschnitt 10).

Läuft als einmaliger, idempotenter Wartungsbefehl (app/workers/upload_history_backfill.py), nicht in
der Migration - Deploy und Rollback bleiben schnell. Erfasst werden nur Dateien ohne Vorgang
(stored_file.upload_job_id IS NULL); ein zweiter Lauf findet nichts mehr. Alle so entstandenen
Vorgänge tragen ``reconstructed = true`` (Anzeige «rekonstruiert»), ``options.reconstruction`` sagt,
ob die Quelle eindeutig (``exact``) oder geschätzt (``heuristic``) ist.

1. Exakt:
   - Abgabebox-Einreichungen (submission_upload, dauerhaft) - je Einreichung ein Vorgang.
   - Datei-Importe (import_job/import_item) - je Import ein Vorgang mit Verweis auf den Bericht.
   - Word-Import-Dokumente - je Dokument ein Vorgang.
   - Galerie-Ingest-Aufträge der letzten 30 Tage (gallery_upload_job) - Pakete derselben Person mit
     weniger als 2 Minuten Abstand ergeben einen Vorgang (ein Dialog sendet mehrere Pakete).
2. Heuristisch: übrige Galerie-/Ablage-Dateien (gallery_image) gruppiert nach Mandant, Person, Bezug
   und Dateiart mit höchstens 10 Minuten Lücke. Duplikate und Ablehnungen sind dafür nicht bekannt.
3. Protokollbilder bleiben «Upload-Vorgang unbekannt» (wenig Nutzen).

Das Audit-Log taugt nicht als Quelle (keine Upload-Einträge vor 1.6).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.entities import (
    GalleryImage,
    GalleryUploadJob,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    WordImportDocument,
)
from app.models.import_entities import ImportItem, ImportJob
from app.models.upload_history_entities import UploadJob
from app.services import upload_job_service

logger = logging.getLogger(__name__)

PACKET_GAP = timedelta(minutes=2)
HEURISTIC_GAP = timedelta(minutes=10)


@dataclass
class BackfillReport:
    jobs: dict[str, int] = field(default_factory=dict)
    files: int = 0

    def add(self, kind: str, files: int) -> None:
        self.jobs[kind] = self.jobs.get(kind, 0) + 1
        self.files += files


def _create(
    db: Session, *, tenant_id: int, channel: str, kind: str, files: list[StoredFile], created_by: int | None = None,
    actor_kind: str = "user", report: BackfillReport, extra_items: list | None = None, **target,
) -> UploadJob | None:
    files = [stored for stored in files if stored.upload_job_id is None and stored.tenant_id == tenant_id]
    if not files:
        return None
    created = min(stored.created_at for stored in files)
    finished = max(stored.created_at for stored in files)
    job = UploadJob(
        tenant_id=tenant_id, channel=channel, created_by=created_by, actor_kind=actor_kind, status="done", reconstructed=True,
        options={"reconstruction": kind}, created_at=created, client_closed_at=finished, finished_at=finished,
        **{key: value for key, value in target.items() if value is not None},
    )
    db.add(job)
    db.flush()
    items = [
        upload_job_service.ItemIn(
            status="uploaded", name=stored.original_name, stored_file_id=stored.id, size_bytes=stored.file_size_bytes,
            mime_type=stored.mime_type,
        )
        for stored in sorted(files, key=lambda row: (row.created_at, row.id))
    ]
    upload_job_service.record_items(db, job, items + list(extra_items or []))
    db.execute(
        update(StoredFile).where(StoredFile.id.in_([stored.id for stored in files]), StoredFile.tenant_id == tenant_id)
        .values(upload_job_id=job.id).execution_options(synchronize_session=False)
    )
    for stored in files:
        stored.upload_job_id = job.id
    report.add(f"{channel}:{kind}", len(files))
    return job


def _files(db: Session, tenant_id: int, ids) -> list[StoredFile]:
    ids = [file_id for file_id in ids if file_id is not None]
    if not ids:
        return []
    return list(
        db.scalars(
            select(StoredFile)
            .where(StoredFile.tenant_id == tenant_id, StoredFile.id.in_(ids), StoredFile.upload_job_id.is_(None))
            .execution_options(include_trashed=True)
        )
    )


def _abgabebox(db: Session, tenant_id: int, report: BackfillReport) -> None:
    rows = db.execute(
        select(SubmissionUploadFile.upload_id, SubmissionUploadFile.stored_file_id, SubmissionUpload.assignment_id, SubmissionUpload.event_id)
        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
        .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
        .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
        # Wie der Trigger 0252: Mandant der Abgabe = Mandant der Datei (Security-Review H-3)
        .where(StoredFile.tenant_id == tenant_id, SubmissionAssignment.tenant_id == tenant_id, StoredFile.upload_job_id.is_(None))
        .execution_options(include_trashed=True)
    ).all()
    by_upload: dict[int, list] = {}
    for row in rows:
        by_upload.setdefault(row.upload_id, []).append(row)
    for upload_id, group in by_upload.items():
        if db.scalar(select(UploadJob.id).where(UploadJob.submission_upload_id == upload_id)) is not None:
            continue  # vom Trigger angelegt (neue Einreichung mit älteren Dateien)
        _create(
            db, tenant_id=tenant_id, channel="abgabebox", kind="exact", actor_kind="anonymous_link",
            files=_files(db, tenant_id, [row.stored_file_id for row in group]), report=report,
            submission_upload_id=upload_id, submission_assignment_id=group[0].assignment_id, event_id=group[0].event_id,
        )


def _imports(db: Session, tenant_id: int, report: BackfillReport) -> None:
    for job in db.scalars(select(ImportJob).where(ImportJob.tenant_id == tenant_id)):
        if db.scalar(select(UploadJob.id).where(UploadJob.import_job_id == job.id)) is not None:
            continue
        ids = db.scalars(select(ImportItem.stored_file_id).where(ImportItem.job_id == job.id, ImportItem.stored_file_id.is_not(None)))
        _create(
            db, tenant_id=tenant_id, channel="cloud_import", kind="exact", created_by=job.requested_by,
            files=_files(db, tenant_id, list(ids)), report=report, import_job_id=job.id,
        )


def _word_imports(db: Session, tenant_id: int, report: BackfillReport) -> None:
    for document in db.scalars(select(WordImportDocument).where(WordImportDocument.tenant_id == tenant_id)):
        _create(
            db, tenant_id=tenant_id, channel="word_import", kind="exact", created_by=document.created_by,
            files=_files(db, tenant_id, [document.stored_file_id]), report=report,
        )


def _gallery_jobs(db: Session, tenant_id: int, report: BackfillReport) -> None:
    packets = list(
        db.scalars(
            select(GalleryUploadJob)
            .where(GalleryUploadJob.tenant_id == tenant_id, GalleryUploadJob.upload_job_id.is_(None), GalleryUploadJob.status == "done")
            .order_by(GalleryUploadJob.requested_by, GalleryUploadJob.created_at)
        )
    )
    groups: list[list[GalleryUploadJob]] = []
    for packet in packets:
        last = groups[-1][-1] if groups else None
        if last is not None and last.requested_by == packet.requested_by and packet.created_at - last.created_at < PACKET_GAP:
            groups[-1].append(packet)
        else:
            groups.append([packet])
    for group in groups:
        public_ids = []
        for packet in group:
            for raw in packet.imported_file_ids or []:
                try:
                    public_ids.append(uuid.UUID(str(raw)))
                except ValueError:
                    continue
        files = list(
            db.scalars(
                select(StoredFile)
                .where(StoredFile.tenant_id == tenant_id, StoredFile.public_id.in_(public_ids), StoredFile.upload_job_id.is_(None))
                .execution_options(include_trashed=True)
            )
        ) if public_ids else []
        failures = [
            upload_job_service.ItemIn(status=status, name=result.get("name"), reason_code=reason)
            for packet in group
            for result in (packet.file_results or [])
            if result.get("status") == "failed"
            for status, reason in [upload_job_service.item_status_for(result)]
        ]
        first = group[0]
        job = _create(
            db, tenant_id=tenant_id, channel="gallery", kind="exact", created_by=first.requested_by, files=files, report=report,
            extra_items=failures, event_id=first.upload_event_id, submission_assignment_id=first.upload_assignment_id,
            submission_element_ref=first.upload_element_ref, submission_element_label=first.upload_element_label,
            cycle_config_id=first.upload_cycle_config_id,
        )
        if job is not None:
            for packet in group:
                packet.upload_job_id = job.id


def _heuristic(db: Session, tenant_id: int, report: BackfillReport) -> None:
    rows = db.execute(
        select(StoredFile, GalleryImage)
        .join(GalleryImage, GalleryImage.stored_file_id == StoredFile.id)
        .where(StoredFile.tenant_id == tenant_id, StoredFile.upload_job_id.is_(None))
        .order_by(GalleryImage.created_by, StoredFile.created_at, StoredFile.id)
        .execution_options(include_trashed=True)
    ).all()
    groups: list[tuple[tuple, list[StoredFile], datetime]] = []
    for stored, image in rows:
        is_image = bool(stored.mime_type and stored.mime_type.startswith("image/"))
        key = (
            image.created_by, image.event_id if not image.event_auto_linked else None, image.submission_assignment_id,
            image.submission_element_ref, image.cycle_config_id, is_image,
        )
        if groups and groups[-1][0] == key and stored.created_at - groups[-1][2] <= HEURISTIC_GAP:
            groups[-1][1].append(stored)
            groups[-1] = (key, groups[-1][1], stored.created_at)
        else:
            groups.append((key, [stored], stored.created_at))
    for key, files, _last in groups:
        created_by, event_id, assignment_id, element_ref, cycle_id, is_image = key
        _create(
            db, tenant_id=tenant_id, channel="gallery" if is_image else "document", kind="heuristic", created_by=created_by,
            files=files, report=report, event_id=event_id, submission_assignment_id=assignment_id,
            submission_element_ref=element_ref if assignment_id else None, cycle_config_id=cycle_id,
        )


def backfill_tenant(db: Session, tenant_id: int) -> BackfillReport:
    report = BackfillReport()
    for step in (_abgabebox, _imports, _word_imports, _gallery_jobs, _heuristic):
        step(db, tenant_id, report)
        db.commit()
    return report
