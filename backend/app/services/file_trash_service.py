"""Papierkorb für Dateien und Fotos (Migration 0199_stored_file_soft_delete).

Löschen auf der Dateien-/Fotos-Seite (Einzelaktion, Foto-Ansicht, Mehrfachauswahl, «Nur beste
behalten») legt eine Datei hier ab, statt sie sofort zu entfernen:

- **In den Papierkorb** setzt ``deleted_at``/``deleted_by`` auf der Datei und auf allem, was ohne
  eigene Zeile in der Übersicht an ihr hängt (Clip eines Live Photos, von der Dokument-
  verarbeitung erzeugte PDF-/Vorschaudateien). Alle Verknüpfungen bleiben stehen: Galerie-Eintrag
  mit Termin-/Abgabe-/Zyklus-Bezug, Album-Einträge (inkl. «beste»), Tags, Freigabelinks,
  Pendenz-Verknüpfungen. Sichtbar ist davon nichts mehr, weil ``app/core/trash_scope.py`` die
  Datei aus jeder ORM-Abfrage ausblendet.
- **Wiederherstellen** setzt die Spalten zurück - damit ist alles wieder da.
- **Endgültig löschen** (von Hand, «Papierkorb leeren» oder nach ``TRASH_RETENTION`` durch den
  Job ``file_trash_purge``) nimmt den bisherigen Löschweg: Galerie-Eintrag, ``FileEraser.erase``
  (Dokument, Album-/Linkeinträge, Löschjournal, Speicherobjekt), Vorschaubild nach dem Commit.

In den Papierkorb kommen nur Direkt-Uploads der Galerie/Ablage (``gallery_image``), wie bisher
beim Löschen. Protokollbilder, Word-Import-Quellen, Abgabebox-Einreichungen und Exporte haben
eigene Löschwege und bleiben dort (siehe deletion_service). DSGVO-/Offboarding-/Aufbewahrungs-
und Virenfund-Wege löschen weiterhin sofort und schliessen den Papierkorb ein.

Rechte: wer eine Datei löschen darf, sieht sie im Papierkorb und darf sie wiederherstellen oder
endgültig löschen - Fotos/Videos mit ``photos.manage``, andere Dateien mit ``files.manage``.

Kontingent: Papierkorb-Dateien zählen bis zum endgültigen Löschen
(StoredFileRepository.total_bytes_for_tenant, Speicherkategorie «Papierkorb»).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.core.security import CurrentUser
from app.core.storage import MAIN
from app.core.trash_scope import TRASH_RETENTION, include_trashed
from app.models.document_entities import Document, DocumentFile, DocumentVersion
from app.models.entities import (
    AppUser,
    DocumentExport,
    GalleryImage,
    ProtocolImage,
    StoredFile,
    SubmissionUploadFile,
    WordImportDocument,
)
from app.services.audit_service import AuditService

_logger = logging.getLogger(__name__)

# Höchstens so viele Dateien je Aktion (wie die bisherige Mehrfachauswahl).
MAX_BATCH = 200
# Purge-Job: höchstens so viele Dateien je Lauf, der Rest folgt im nächsten Tick.
PURGE_BATCH = 200

_audit = AuditService()


def is_media(mime_type: str | None) -> bool:
    mime = mime_type or ""
    return mime.startswith("image/") or mime.startswith("video/")


def permission_for(mime_type: str | None) -> str:
    """Löschen/Papierkorb einer Datei: Fotos und Videos mit photos.manage, alles andere mit files.manage."""
    return P.PHOTOS_MANAGE if is_media(mime_type) else P.FILES_MANAGE


def may_manage(user: CurrentUser, mime_type: str | None) -> bool:
    return user.can(permission_for(mime_type))


def _other_owner(db: Session, stored_file_id: int) -> bool:
    """Die Datei gehört (auch) einem Zusammenhang mit eigenem Löschweg."""
    for column in (
        ProtocolImage.stored_file_id,
        WordImportDocument.stored_file_id,
        SubmissionUploadFile.stored_file_id,
        DocumentExport.stored_file_id,
    ):
        if db.scalar(select(column).where(column == stored_file_id).limit(1)) is not None:
            return True
    return False


def _group_ids(db: Session, stored_file_id: int) -> list[int]:
    """Die Datei samt den Dateien, die mit ihr in den Papierkorb gehen und mit ihr zurückkommen:
    Clip des Live Photos und erzeugte Dateien ihres Upload-Dokuments."""
    ids = [stored_file_id]
    live = db.scalar(
        select(GalleryImage.live_video_stored_file_id).where(
            GalleryImage.stored_file_id == stored_file_id, GalleryImage.live_video_stored_file_id.is_not(None)
        )
    )
    if live is not None:
        ids.append(live)
    version_ids = select(DocumentFile.document_version_id).where(
        DocumentFile.stored_file_id == stored_file_id, DocumentFile.role == "original"
    )
    generated = db.scalars(
        select(DocumentFile.stored_file_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentFile.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentFile.is_generated.is_(True),
            Document.source_kind == "upload",
            DocumentVersion.document_id.in_(select(DocumentVersion.document_id).where(DocumentVersion.id.in_(version_ids))),
        )
    )
    ids += [file_id for file_id in generated if file_id not in ids]
    return ids


def _is_gallery_main(db: Session, stored_file_id: int) -> bool:
    return db.scalar(select(GalleryImage.id).where(GalleryImage.stored_file_id == stored_file_id).limit(1)) is not None


# ── In den Papierkorb ────────────────────────────────────────────────────────────────────────


def trash_files(db: Session, user: CurrentUser, file_ids: list[uuid.UUID]) -> tuple[list[uuid.UUID], list[str]]:
    """Legt Dateien des eigenen Mandanten in den Papierkorb. Teil-Erfolg wie bisher beim Löschen:
    (verschobene IDs, Fehlertexte je abgelehnter Datei). Committet."""
    tenant_id = user.current_tenant_id
    if tenant_id is None:
        raise ValueError("No active tenant")
    trashed: list[uuid.UUID] = []
    errors: list[str] = []
    now = datetime.now(UTC)
    rows = {
        row.public_id: row
        for row in db.scalars(select(StoredFile).where(StoredFile.tenant_id == tenant_id, StoredFile.public_id.in_(file_ids)))
    }
    for file_id in file_ids:
        stored_file = rows.get(file_id)
        if stored_file is None:
            errors.append("Datei nicht gefunden")
            continue
        if not may_manage(user, stored_file.mime_type):
            # Kein Existenz-Orakel nötig: die Datei liegt im eigenen Mandanten, nur das Recht fehlt.
            errors.append(f"{stored_file.original_name}: keine Berechtigung zum Löschen")
            continue
        if not _is_gallery_main(db, stored_file.id) or _other_owner(db, stored_file.id):
            errors.append(f"{stored_file.original_name}: kann von hier aus nicht gelöscht werden")
            continue
        group = _group_ids(db, stored_file.id)
        db.execute(
            update(StoredFile)
            .where(StoredFile.id.in_(group), StoredFile.tenant_id == tenant_id, StoredFile.deleted_at.is_(None))
            .values(deleted_at=now, deleted_by=user.user_id)
            .execution_options(synchronize_session=False)
        )
        _audit.log(
            db, action="file.trashed", actor=user, entity_type="stored_file", entity_id=stored_file.id,
            details={"name": stored_file.original_name, "files": len(group)}, commit=False,
        )
        trashed.append(file_id)
    db.commit()
    return trashed, errors


# ── Papierkorb-Ansicht ───────────────────────────────────────────────────────────────────────


@dataclass
class TrashEntry:
    stored_file: StoredFile
    deleted_by_name: str | None
    purge_at: datetime


def _trash_query(db: Session, user: CurrentUser):
    """Papierkorb des eigenen Mandanten. Reichweite «nur zugewiesene» (Phase 4/5) gilt auch hier:
    Abgabe-Dateien nicht lesbarer Aufträge erscheinen nicht (wie in Liste und Mehrfachaktionen)."""
    from app.services import context_visibility_service

    query = (
        select(StoredFile, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == StoredFile.deleted_by)
        .where(
            StoredFile.tenant_id == user.current_tenant_id,
            StoredFile.deleted_at.is_not(None),
            # Nur die Einträge, die man gelöscht hat - Live-Clip und erzeugte Dateien hängen daran.
            select(GalleryImage.id).where(GalleryImage.stored_file_id == StoredFile.id).exists(),
        )
        .execution_options(include_trashed=True)
    )
    readable = context_visibility_service.readable_assignment_ids(db, user)
    if readable is not None:
        query = query.where(context_visibility_service.abgabe_scope_clause(StoredFile.id, readable))
    return query


def _visible_to(user: CurrentUser, stored_file: StoredFile) -> bool:
    return may_manage(user, stored_file.mime_type)


def list_trash(db: Session, user: CurrentUser) -> list[TrashEntry]:
    """Papierkorb des Mandanten, neueste Löschung zuerst; nur Dateien, die das Konto löschen darf."""
    tenant_id = user.current_tenant_id
    if tenant_id is None:
        return []
    entries: list[TrashEntry] = []
    for stored_file, deleted_by_name in db.execute(_trash_query(db, user).order_by(StoredFile.deleted_at.desc(), StoredFile.id.desc())):
        if not _visible_to(user, stored_file):
            continue
        entries.append(TrashEntry(stored_file=stored_file, deleted_by_name=deleted_by_name, purge_at=stored_file.deleted_at + TRASH_RETENTION))
    return entries


def get_trashed(db: Session, user: CurrentUser, file_id: uuid.UUID) -> StoredFile | None:
    """Eine Papierkorb-Datei des eigenen Mandanten, die das Konto verwalten darf (sonst None = 404)."""
    if user.current_tenant_id is None:
        return None
    row = db.execute(_trash_query(db, user).where(StoredFile.public_id == file_id)).first()
    if row is None or not _visible_to(user, row[0]):
        return None
    return row[0]


def _resolve(db: Session, user: CurrentUser, file_ids: list[uuid.UUID]) -> tuple[list[StoredFile], list[str]]:
    found: list[StoredFile] = []
    errors: list[str] = []
    for file_id in file_ids:
        stored_file = get_trashed(db, user, file_id)
        if stored_file is None:
            errors.append("Datei nicht im Papierkorb")
        else:
            found.append(stored_file)
    return found, errors


# ── Wiederherstellen ─────────────────────────────────────────────────────────────────────────


def restore(db: Session, user: CurrentUser, file_ids: list[uuid.UUID]) -> tuple[list[uuid.UUID], list[str]]:
    """Holt Dateien samt Live-Clip und erzeugten Dateien zurück; alle Verknüpfungen sind noch da."""
    with include_trashed(db):
        found, errors = _resolve(db, user, file_ids)
        restored: list[uuid.UUID] = []
        for stored_file in found:
            group = _group_ids(db, stored_file.id)
            db.execute(
                update(StoredFile)
                .where(StoredFile.id.in_(group), StoredFile.tenant_id == stored_file.tenant_id)
                .values(deleted_at=None, deleted_by=None)
                .execution_options(synchronize_session=False)
            )
            _audit.log(
                db, action="file.restored", actor=user, entity_type="stored_file", entity_id=stored_file.id,
                details={"name": stored_file.original_name}, commit=False,
            )
            restored.append(stored_file.public_id)
        db.commit()
    return restored, errors


# ── Endgültig löschen ────────────────────────────────────────────────────────────────────────


def _purge_one(db: Session, stored_file: StoredFile, eraser) -> None:
    """Der bisherige endgültige Löschweg (FileService.delete_gallery_images). Muss mit
    sichtbarem Papierkorb laufen, damit Dokument, Live-Clip und erzeugte Dateien gefunden werden."""
    live_video_id = db.scalar(select(GalleryImage.live_video_stored_file_id).where(GalleryImage.stored_file_id == stored_file.id))
    db.execute(delete(GalleryImage).where(GalleryImage.stored_file_id == stored_file.id))
    db.flush()
    eraser.erase(db, stored_file, namespace=MAIN)
    if live_video_id is not None:
        eraser.erase_if_unreferenced(db, [live_video_id])


def _eraser():
    from app.services.file_eraser import FileEraser
    from app.services.file_service import FileService

    return FileEraser(FileService())


def purge(db: Session, user: CurrentUser, file_ids: list[uuid.UUID]) -> tuple[list[uuid.UUID], list[str]]:
    """«Endgültig löschen» im Papierkorb."""
    eraser = _eraser()
    with include_trashed(db):
        found, errors = _resolve(db, user, file_ids)
        purged: list[uuid.UUID] = []
        for stored_file in found:
            public_id, name, internal_id = stored_file.public_id, stored_file.original_name, stored_file.id
            _purge_one(db, stored_file, eraser)
            _audit.log(
                db, action="file.purged", actor=user, entity_type="stored_file", entity_id=internal_id,
                details={"name": name}, commit=False,
            )
            purged.append(public_id)
        db.commit()
        eraser.after_commit(db)
    return purged, errors


def empty(db: Session, user: CurrentUser) -> int:
    """«Papierkorb leeren»: alles, was das Konto im Papierkorb sieht."""
    entries = list_trash(db, user)
    ids = [entry.stored_file.public_id for entry in entries]
    purged: list[uuid.UUID] = []
    for start in range(0, len(ids), MAX_BATCH):
        done, _errors = purge(db, user, ids[start:start + MAX_BATCH])
        purged += done
    _audit.log(db, action="file.trash_emptied", actor=user, entity_type="tenant", entity_id=user.current_tenant_id, details={"files": len(purged)})
    return len(purged)


def summary(db: Session, user: CurrentUser) -> tuple[int, int]:
    """(Anzahl, Bytes) der Papierkorb-Dateien, die das Konto sieht - für den Kontingent-Hinweis."""
    entries = list_trash(db, user)
    total = 0
    with include_trashed(db):
        for entry in entries:
            ids = _group_ids(db, entry.stored_file.id)
            total += int(db.scalar(select(func.coalesce(func.sum(StoredFile.file_size_bytes), 0)).where(StoredFile.id.in_(ids))) or 0)
    return len(entries), total


def purge_expired(db: Session, *, now: datetime | None = None, limit: int = PURGE_BATCH) -> dict[str, int]:
    """Job file_trash_purge: löscht Papierkorb-Dateien endgültig, deren Frist abgelaufen ist.
    Jede Datei einzeln committet; ein Fehler landet im Fehlerprotokoll und hält den Rest nicht auf."""
    from app.core.error_log import record_system_error

    cutoff = (now or datetime.now(UTC)) - TRASH_RETENTION
    result = {"purged": 0, "failed": 0}
    with include_trashed(db):
        candidates = list(
            db.execute(
                select(StoredFile.id, StoredFile.tenant_id)
                .where(
                    StoredFile.deleted_at.is_not(None),
                    StoredFile.deleted_at <= cutoff,
                    select(GalleryImage.id).where(GalleryImage.stored_file_id == StoredFile.id).exists(),
                )
                .order_by(StoredFile.deleted_at, StoredFile.id)
                .limit(limit)
            ).all()
        )
        db.commit()
        for stored_file_id, tenant_id in candidates:
            eraser = _eraser()
            try:
                stored_file = db.get(StoredFile, stored_file_id)
                if stored_file is None or stored_file.deleted_at is None:
                    continue
                name = stored_file.original_name
                _purge_one(db, stored_file, eraser)
                _audit.log(
                    db, action="file.purged", tenant_id=tenant_id, entity_type="stored_file", entity_id=stored_file_id,
                    details={"name": name, "automatic": True}, commit=False,
                )
                db.commit()
                eraser.after_commit(db)
                result["purged"] += 1
            except Exception as exc:  # noqa: BLE001 - einzelne Datei; Fehlerprotokoll, Rest läuft weiter
                db.rollback()
                _logger.exception("Papierkorb: Datei %s konnte nicht endgültig gelöscht werden", stored_file_id)
                record_system_error(db, exc=exc, tenant_id=tenant_id)
                result["failed"] += 1
        # Mitgelöschte Dateien (Live-Clip, erzeugte Dokumentdateien), deren Hauptdatei auf einem
        # anderen Weg endgültig verschwand: sonst blieben sie unsichtbar und unbegrenzt liegen.
        result["orphans"] = _purge_expired_orphans(db, cutoff, limit=limit)
    return result


def _purge_expired_orphans(db: Session, cutoff: datetime, *, limit: int) -> int:
    from app.core.error_log import record_system_error
    from app.services.file_eraser import is_referenced

    orphan_ids = list(
        db.scalars(
            select(StoredFile.id)
            .where(
                StoredFile.deleted_at.is_not(None),
                StoredFile.deleted_at <= cutoff,
                ~select(GalleryImage.id).where(GalleryImage.stored_file_id == StoredFile.id).exists(),
                ~select(DocumentFile.id).where(DocumentFile.stored_file_id == StoredFile.id).exists(),
            )
            .order_by(StoredFile.id)
            .limit(limit)
        )
    )
    db.commit()
    purged = 0
    for stored_file_id in orphan_ids:
        eraser = _eraser()
        try:
            stored_file = db.get(StoredFile, stored_file_id)
            if stored_file is None or is_referenced(db, stored_file_id):
                continue
            eraser.erase(db, stored_file)
            db.commit()
            eraser.after_commit(db)
            purged += 1
        except Exception as exc:  # noqa: BLE001 - einzelne Datei; Fehlerprotokoll, Rest läuft weiter
            db.rollback()
            _logger.exception("Papierkorb: verwaiste Datei %s konnte nicht gelöscht werden", stored_file_id)
            record_system_error(db, exc=exc)
    return purged
