"""Löschen von Protokollen, Abgaben und Einreichungen mit ihren Dateien (Datenschutz-Audit
PRIV-003/PRIV-004, Umsetzungsplan Paket 2).

Vorher blieben beim Löschen eines Protokolls die Protokollbilder und beim Löschen einer Abgabe
alle eingereichten Dateien liegen: unsichtbar, aber im Speicher, in Backups und im Kontingent.
Jetzt zeigt die Oberfläche vorher, welche Dateien betroffen sind (``*_preview``), und der
Benutzer wählt je Datei (Standard: löschen). Nicht gewählte Dateien wandern mit Herkunfts-Tag in
die Galerie. Dateien, die noch anderswo verwendet werden (ein Bild, das auch in einem anderen
Protokoll steckt), bleiben unverändert und sind in der Vorschau nicht wählbar.

Die Aufrufer prüfen Rechte und Mandant; hier wird nur gelöscht. Committet wird hier.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.storage import ABGABEBOX, MAIN
from app.models.entities import (
    DocumentExport,
    GalleryImage,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
)
from app.services.file_eraser import FileEraser, is_referenced


@dataclass
class DeletionFile:
    stored_file: StoredFile
    # Wird die Datei ausserhalb des gelöschten Zusammenhangs noch verwendet, bleibt sie.
    used_elsewhere: bool = False
    # Gruppe in der Vorschau: "protocol_image", "submission", "gallery"
    group: str = "protocol_image"
    namespace: str = MAIN
    upload_file_public_id: uuid.UUID | None = None
    upload_public_id: uuid.UUID | None = None
    label: str | None = None


@dataclass
class DeletionResult:
    deleted_files: int = 0
    kept_files: int = 0
    untouched_files: int = 0
    errors: list[str] = field(default_factory=list)


def _choose(delete_file_ids: set[uuid.UUID] | None, stored_file: StoredFile) -> bool:
    """None = alles löschen (Standard der Oberfläche, auch für alte Clients ohne Auswahl)."""
    return delete_file_ids is None or stored_file.public_id in delete_file_ids


# ── Protokoll ─────────────────────────────────────────────────────────────────────────────────


def _protocol_image_rows(db: Session, protocol_id: int) -> list[ProtocolImage]:
    return list(
        db.scalars(
            select(ProtocolImage)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolImage.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(ProtocolElement.protocol_id == protocol_id)
            .order_by(ProtocolImage.sort_index, ProtocolImage.id)
        )
    )


def protocol_preview(db: Session, protocol: Protocol) -> list[DeletionFile]:
    images = _protocol_image_rows(db, protocol.id)
    own_rows = {image.stored_file_id: 0 for image in images}
    for image in images:
        own_rows[image.stored_file_id] += 1
    files: list[DeletionFile] = []
    for stored_file_id, own_count in own_rows.items():
        stored_file = db.get(StoredFile, stored_file_id)
        if stored_file is None:
            continue
        protocol_image_total = db.scalar(select(func.count()).select_from(ProtocolImage).where(ProtocolImage.stored_file_id == stored_file_id)) or 0
        elsewhere = protocol_image_total > own_count or _referenced_besides_protocol_images(db, stored_file_id)
        title = next((image.title for image in images if image.stored_file_id == stored_file_id and image.title), None)
        files.append(DeletionFile(stored_file=stored_file, used_elsewhere=elsewhere, label=title))
    return files


def _referenced_besides_protocol_images(db: Session, stored_file_id: int) -> bool:
    from app.services.file_eraser import _REFERENCES

    for column in _REFERENCES:
        if column.class_ is ProtocolImage:
            continue
        if db.scalar(select(column).where(column == stored_file_id).limit(1)) is not None:
            return True
    return False


def delete_protocol(db: Session, protocol: Protocol, *, delete_file_ids: set[uuid.UUID] | None, actor_user_id: int | None, file_service=None) -> DeletionResult:
    result = DeletionResult()
    preview = protocol_preview(db, protocol)
    export_file_ids = list(
        db.scalars(select(DocumentExport.stored_file_id).where(DocumentExport.protocol_id == protocol.id, DocumentExport.stored_file_id.is_not(None)))
    )
    tag = f"Protokoll {protocol.protocol_number or protocol.title or ''}".strip()
    eraser = FileEraser(file_service)
    for item in preview:
        if item.used_elsewhere:
            result.untouched_files += 1
        elif not _choose(delete_file_ids, item.stored_file):
            eraser.keep_in_gallery(db, item.stored_file, tag=tag, created_by=actor_user_id)
            result.kept_files += 1
    image_ids = [item.stored_file.id for item in preview if not item.used_elsewhere and _choose(delete_file_ids, item.stored_file)]
    db.delete(protocol)
    db.flush()
    # Nach dem Protokoll sind protocol_image und document_export weg; gelöscht wird nur, was nun
    # niemand mehr braucht (übernommene Bilder hängen jetzt an der Galerie).
    result.deleted_files += eraser.erase_if_unreferenced(db, image_ids)
    result.deleted_files += eraser.erase_if_unreferenced(db, export_file_ids)
    db.commit()
    eraser.after_commit(db)
    return result


# ── Abgabe und Einreichungen ──────────────────────────────────────────────────────────────────


def _submission_rows(db: Session, *, assignment_id: int | None = None, upload_id: int | None = None):
    statement = (
        select(SubmissionUploadFile, StoredFile, SubmissionUpload)
        .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
        .order_by(SubmissionUpload.submitted_at, SubmissionUploadFile.sort_index, SubmissionUploadFile.id)
    )
    if assignment_id is not None:
        statement = statement.where(SubmissionUpload.assignment_id == assignment_id)
    if upload_id is not None:
        statement = statement.where(SubmissionUpload.id == upload_id)
    return db.execute(statement).all()


def assignment_preview(db: Session, assignment: SubmissionAssignment) -> list[DeletionFile]:
    files: list[DeletionFile] = []
    for upload_file, stored_file, upload in _submission_rows(db, assignment_id=assignment.id):
        other_upload_rows = db.scalar(
            select(func.count()).select_from(SubmissionUploadFile).where(
                SubmissionUploadFile.stored_file_id == stored_file.id, SubmissionUploadFile.id != upload_file.id
            )
        ) or 0
        other_assignment = other_upload_rows and db.scalar(
            select(SubmissionUpload.assignment_id)
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .where(SubmissionUploadFile.stored_file_id == stored_file.id, SubmissionUpload.assignment_id != assignment.id)
            .limit(1)
        )
        files.append(
            DeletionFile(
                stored_file=stored_file,
                group="submission",
                namespace=ABGABEBOX,
                upload_file_public_id=upload_file.public_id,
                upload_public_id=upload.public_id,
                used_elsewhere=bool(other_assignment) or _referenced_besides_submissions(db, stored_file.id),
            )
        )
    for stored_file in db.scalars(
        select(StoredFile)
        .join(GalleryImage, GalleryImage.stored_file_id == StoredFile.id)
        .where(GalleryImage.submission_assignment_id == assignment.id)
        .order_by(StoredFile.created_at, StoredFile.id)
    ):
        files.append(DeletionFile(stored_file=stored_file, group="gallery"))
    return files


def _referenced_besides_submissions(db: Session, stored_file_id: int) -> bool:
    from app.services.file_eraser import _REFERENCES

    for column in _REFERENCES:
        if column.class_ is SubmissionUploadFile:
            continue
        if db.scalar(select(column).where(column == stored_file_id).limit(1)) is not None:
            return True
    return False


def _erase_gallery_photo(db: Session, eraser: FileEraser, stored_file: StoredFile) -> None:
    live_video_id = db.scalar(select(GalleryImage.live_video_stored_file_id).where(GalleryImage.stored_file_id == stored_file.id))
    db.execute(delete(GalleryImage).where(GalleryImage.stored_file_id == stored_file.id))
    db.flush()
    if not is_referenced(db, stored_file.id):
        eraser.erase(db, stored_file, namespace=MAIN)
    if live_video_id is not None:
        eraser.erase_if_unreferenced(db, [live_video_id])


def delete_assignment(db: Session, assignment: SubmissionAssignment, *, delete_file_ids: set[uuid.UUID] | None, actor_user_id: int | None, file_service=None) -> DeletionResult:
    result = DeletionResult()
    eraser = FileEraser(file_service)
    tag = f"Abgabe {assignment.title}".strip()
    to_erase: list[DeletionFile] = []
    for item in assignment_preview(db, assignment):
        if item.used_elsewhere:
            result.untouched_files += 1
        elif _choose(delete_file_ids, item.stored_file):
            to_erase.append(item)
        elif item.group == "submission":
            eraser.keep_in_gallery(
                db, item.stored_file, tag=tag, namespace=ABGABEBOX,
                extra_public_ids=[item.upload_file_public_id] if item.upload_file_public_id else [], created_by=actor_user_id,
            )
            result.kept_files += 1
        else:
            result.kept_files += 1  # Galeriefoto bleibt, verliert nur den Bezug zur Abgabe
    for item in to_erase:
        if item.group == "gallery":
            _erase_gallery_photo(db, eraser, item.stored_file)
        result.deleted_files += 1
    submission_items = [item for item in to_erase if item.group == "submission"]
    db.delete(assignment)
    db.flush()
    for item in submission_items:
        eraser.erase(db, item.stored_file, namespace=ABGABEBOX, extra_public_ids=[item.upload_file_public_id] if item.upload_file_public_id else [])
    db.commit()
    eraser.after_commit(db)
    return result


def delete_submission_files(db: Session, rows: list[tuple[SubmissionUploadFile, StoredFile]], *, file_service=None) -> int:
    """Einzelne eingereichte Dateien löschen; leere Einreichungen verschwinden mit."""
    eraser = FileEraser(file_service)
    upload_ids = {upload_file.upload_id for upload_file, _ in rows}
    erased = 0
    for upload_file, stored_file in rows:
        public_id = upload_file.public_id
        db.delete(upload_file)
        db.flush()
        if not is_referenced(db, stored_file.id):
            eraser.erase(db, stored_file, namespace=ABGABEBOX, extra_public_ids=[public_id])
            erased += 1
    for upload_id in upload_ids:
        if db.scalar(select(SubmissionUploadFile.id).where(SubmissionUploadFile.upload_id == upload_id).limit(1)) is None:
            db.execute(delete(SubmissionUpload).where(SubmissionUpload.id == upload_id))
    db.commit()
    eraser.after_commit(db)
    return erased


def preview_read(files: list[DeletionFile]):
    """DeletionFile -> Schema der Vorschau (Vorschaubild je nach Herkunft der Datei)."""
    from app.schemas.deletion import DeletionPreview, DeletionPreviewFile

    items = []
    for item in files:
        stored_file = item.stored_file
        is_image = (stored_file.mime_type or "").startswith("image/")
        if not is_image:
            thumbnail_url = None
        elif item.group == "submission" and item.upload_public_id is not None:
            thumbnail_url = f"/api/submission-uploads/{item.upload_public_id}/files/{stored_file.public_id}/thumbnail"
        else:
            thumbnail_url = f"/api/stored-files/{stored_file.public_id}/thumbnail"
        items.append(
            DeletionPreviewFile(
                id=stored_file.public_id,
                name=stored_file.original_name,
                mime_type=stored_file.mime_type,
                is_image=is_image,
                thumbnail_url=thumbnail_url,
                created_at=stored_file.created_at,
                group=item.group,
                used_elsewhere=item.used_elsewhere,
                label=item.label,
            )
        )
    return DeletionPreview(files=items)

