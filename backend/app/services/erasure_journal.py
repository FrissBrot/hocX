"""Löschjournal: Löschungen nach einem Restore erneut anwenden (Datenschutz-Audit PRIV-010).

``record`` schreibt bei jeder endgültigen Löschung Art und public_id in die Tabelle erasure_journal
(Migration 0144), in der Transaktion der Löschung - wird sie zurückgerollt, verschwindet auch der
Eintrag. ``apply`` führt Einträge auf einer (wiederhergestellten) Datenbank erneut aus. Der
Backup-Worker liest dafür vor dem Umschalten die Einträge der laufenden Datenbank, die neuer sind
als der Sicherungspunkt (app/backup/run_restore.py).

Bewusst nur Arten mit einem eigenen, vollständigen Löschpfad; was davon abhängt (Dateien eines
Protokolls, Konten eines Mandanten) erledigt dieser Pfad selbst.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

_logger = logging.getLogger(__name__)

KINDS = ("tenant", "app_user", "protocol", "event", "submission_assignment", "submission_upload", "stored_file")


@dataclass(frozen=True)
class ErasureEntry:
    kind: str
    subject_public_id: uuid.UUID
    tenant_public_id: uuid.UUID | None
    created_at: datetime


def record(db: Session, kind: str, subject_public_id: uuid.UUID, *, tenant_id: int | None = None, tenant_public_id: uuid.UUID | None = None) -> None:
    """In der Transaktion des Aufrufers; committet nicht."""
    if kind not in KINDS:
        raise ValueError(f"Unbekannte Art im Löschjournal: {kind}")
    if tenant_public_id is None and tenant_id is not None:
        from app.models import Tenant

        tenant_public_id = db.scalar(select(Tenant.public_id).where(Tenant.id == tenant_id))
    db.execute(
        text("INSERT INTO erasure_journal (kind, subject_public_id, tenant_public_id) VALUES (:kind, :subject, :tenant)"),
        {"kind": kind, "subject": subject_public_id, "tenant": tenant_public_id},
    )


def entries_since(db: Session, since: datetime) -> list[ErasureEntry]:
    rows = db.execute(
        text("SELECT kind, subject_public_id, tenant_public_id, created_at FROM erasure_journal WHERE created_at > :since ORDER BY id"),
        {"since": since},
    ).all()
    return [ErasureEntry(row.kind, row.subject_public_id, row.tenant_public_id, row.created_at) for row in rows]


def copy_entries(db: Session, entries: list[ErasureEntry]) -> None:
    """Einträge in eine andere (wiederhergestellte) Datenbank übernehmen, damit ein späterer Restore
    sie ebenfalls kennt. Committet nicht."""
    for entry in entries:
        db.execute(
            text(
                "INSERT INTO erasure_journal (kind, subject_public_id, tenant_public_id, created_at) "
                "VALUES (:kind, :subject, :tenant, :created_at)"
            ),
            {"kind": entry.kind, "subject": entry.subject_public_id, "tenant": entry.tenant_public_id, "created_at": entry.created_at},
        )


def purge(db: Session, *, retention_days: int) -> int:
    deleted = db.scalar(text("SELECT erasure_journal_purge(:days)"), {"days": retention_days})
    db.commit()
    return int(deleted or 0)


def apply(db: Session, entries: list[ErasureEntry], *, tenant_id: int | None = None, skip_kinds: tuple[str, ...] = ()) -> dict[str, int]:
    """Führt die Löschungen erneut aus. ``tenant_id``: nur innerhalb dieses Mandanten (Mandanten-Kopie).
    Nicht mehr vorhandene Objekte zählen als erledigt; ein Fehler bei einem Eintrag bricht nicht ab,
    sondern wird gezählt (der Restore meldet ihn)."""
    from app.core.error_log import record_system_error
    from app.models import AppUser, Event, Protocol, StoredFile, SubmissionAssignment, SubmissionUpload, Tenant

    result = {"applied": 0, "missing": 0, "failed": 0, "skipped": 0}
    models = {
        "tenant": Tenant, "app_user": AppUser, "protocol": Protocol, "event": Event,
        "submission_assignment": SubmissionAssignment, "submission_upload": SubmissionUpload, "stored_file": StoredFile,
    }
    for entry in entries:
        if entry.kind in skip_kinds:
            result["skipped"] += 1
            continue
        model = models[entry.kind]
        target = db.scalar(select(model).where(model.public_id == entry.subject_public_id))
        if target is None or (tenant_id is not None and _tenant_of(db, entry.kind, target) != tenant_id):
            result["missing"] += 1
            continue
        try:
            _erase(db, entry.kind, target)
            result["applied"] += 1
        except Exception as exc:  # noqa: BLE001 - einzelner Eintrag, Restore läuft weiter und meldet die Zahl
            db.rollback()
            _logger.exception("Löschjournal: %s %s konnte nicht erneut gelöscht werden", entry.kind, entry.subject_public_id)
            record_system_error(db, exc=exc)
            result["failed"] += 1
    return result


def _tenant_of(db: Session, kind: str, target) -> int | None:
    from app.models import SubmissionAssignment

    if kind == "tenant":
        return target.id
    if kind == "submission_upload":
        return db.scalar(select(SubmissionAssignment.tenant_id).where(SubmissionAssignment.id == target.assignment_id))
    return target.tenant_id


def _erase(db: Session, kind: str, target) -> None:
    from app.services import deletion_service
    from app.services.file_service import FileService

    if kind == "tenant":
        from app.services.admin_tenant_service import AdminTenantService

        AdminTenantService().delete_tenant(db, target.id)
    elif kind == "app_user":
        from app.services.participant_service import ParticipantService

        ParticipantService().delete_participant(db, target.id, tenant_id=target.tenant_id)
    elif kind == "protocol":
        deletion_service.delete_protocol(db, target, delete_file_ids=None, actor_user_id=None, file_service=FileService())
    elif kind == "event":
        from app.services.event_service import EventService

        EventService().delete_event(db, target.id)
    elif kind == "submission_assignment":
        deletion_service.delete_assignment(db, target, delete_file_ids=None, actor_user_id=None, file_service=FileService())
    elif kind == "submission_upload":
        from app.models import StoredFile, SubmissionUploadFile

        rows = db.execute(
            select(SubmissionUploadFile, StoredFile)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUploadFile.upload_id == target.id)
        ).all()
        if rows:
            deletion_service.delete_submission_files(db, [(row[0], row[1]) for row in rows], file_service=FileService())
        else:
            db.delete(target)
            db.commit()
    elif kind == "stored_file":
        from app.services.file_eraser import FileEraser, is_referenced

        if is_referenced(db, target.id):
            # Wieder verknüpft (z. B. Galerie nach Restore): nur löschen, wenn nichts mehr darauf zeigt.
            from app.models import GalleryImage, ProtocolImage

            db.query(GalleryImage).filter(GalleryImage.stored_file_id == target.id).delete(synchronize_session=False)
            db.query(ProtocolImage).filter(ProtocolImage.stored_file_id == target.id).delete(synchronize_session=False)
            db.flush()
            if is_referenced(db, target.id):
                raise RuntimeError("Datei wird noch verwendet")
        eraser = FileEraser(FileService())
        eraser.erase(db, target)
        db.commit()
        eraser.after_commit(db)
