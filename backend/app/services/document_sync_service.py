"""Backend-Loop document_sync: legt Dokumente für Dateien an, die nicht über einen Backend-
Uploadweg kamen, und räumt auf.

1. Abgabebox-Uploads: abgabebox-backend schreibt mit einer eingeschränkten Rolle nur in seine
   eigenen Tabellen (Isolationsgrenze) und kann deshalb kein Dokument anlegen. Das übernimmt
   dieser Loop, sobald die Zeilen sichtbar sind.
2. Bestand (Backfill): dieselbe Abfrage findet auch alle vor der Einführung hochgeladenen
   Dokumente. Wiederholbar und ohne Duplikate (Unique-Index auf dem Original), in Batches.
   Zugeordnet wird ausschliesslich über die bestehenden Herkunftstabellen, nie über Dateinamen.
3. Protokollexporte der Dokument-Engine aus document_export (protocol_export_document_service.backfill).
4. Aufräumen: Versionen ohne Original (Löschpfade über ON DELETE CASCADE) und verwaiste,
   von der Verarbeitung erzeugte Dateien.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GalleryImage, StoredFile, SubmissionUploadFile, WordImportDocument
from app.models.document_entities import FILE_ROLE_ORIGINAL, DocumentFile
from app.services import document_service
from app.services.documents import formats

_logger = logging.getLogger(__name__)


def _missing_upload_documents(db: Session, *, limit: int) -> list[StoredFile]:
    has_origin = or_(
        select(GalleryImage.id).where(GalleryImage.stored_file_id == StoredFile.id).exists(),
        select(WordImportDocument.id).where(WordImportDocument.stored_file_id == StoredFile.id).exists(),
        select(SubmissionUploadFile.id)
        .where(SubmissionUploadFile.stored_file_id == StoredFile.id, SubmissionUploadFile.delete_comment.is_(None))
        .exists(),
    )
    return list(
        db.scalars(
            select(StoredFile)
            .where(
                StoredFile.mime_type.in_(sorted(formats.DOCUMENT_MIMES)),
                StoredFile.scan_status != "infected",
                has_origin,
                ~select(DocumentFile.id)
                .where(DocumentFile.stored_file_id == StoredFile.id, DocumentFile.role == FILE_ROLE_ORIGINAL)
                .exists(),
            )
            .order_by(StoredFile.id)
            .limit(limit)
        )
    )


def register_missing_documents(db: Session, *, limit: int) -> int:
    created = 0
    for stored_file in _missing_upload_documents(db, limit=limit):
        try:
            with db.begin_nested():
                if document_service.register_upload(db, stored_file) is not None:
                    created += 1
        except IntegrityError:
            # Gleichzeitig von einem Upload-Request angelegt - dann gibt es das Dokument schon.
            continue
    return created


def run_tick(db: Session) -> dict[str, int]:
    from app.services import protocol_export_document_service

    batch = settings.document_sync_batch_size
    stats = {"registered": 0, "exports": 0, "removed_versions": 0, "removed_files": 0}
    if settings.document_backfill_enabled:
        stats["registered"] = register_missing_documents(db, limit=batch)
        stats["exports"] = protocol_export_document_service.backfill(db, limit=batch)
    stats["removed_versions"] = document_service.remove_versions_without_original(db, limit=batch)
    stats["removed_files"] = document_service.remove_orphaned_generated_files(db, limit=batch)
    db.commit()
    if any(stats.values()):
        _logger.info("document_sync: %s", stats)
    return stats
