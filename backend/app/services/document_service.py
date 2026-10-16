"""Logische Dokumente: Anlage beim Upload, Versionen, Verarbeitungsaufträge und Aufräumen.

Überblick: docs-site/docs/technik/dokumente.md. Die physischen Dateien bleiben in stored_file;
hier entstehen nur die Verknüpfungen (document_file) und Aufträge (document_job). Alle Funktionen
committen nicht selbst - der Aufrufer bestimmt die Transaktion, damit Dokument und Jobs zusammen
mit der hochgeladenen Datei entstehen (kein Auftrag geht zwischen Commit und Worker verloren).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.storage import MAIN, get_object_store
from app.models import StoredFile
from app.models.document_entities import (
    DOCUMENT_SOURCE_PROTOCOL_EXPORT,
    DOCUMENT_SOURCE_UPLOAD,
    FILE_ROLE_ORIGINAL,
    FILE_ROLE_PDF,
    JOB_KIND_EXTRACT,
    JOB_KIND_PDF,
    Document,
    DocumentExtraction,
    DocumentFile,
    DocumentJob,
    DocumentVersion,
)
from app.services.documents import formats

_logger = logging.getLogger(__name__)

# Key-Präfix (Namespace "main") aller von der Dokumentverarbeitung erzeugten Dateien. Daran
# erkennt der document_sync-Loop verwaiste Reste (siehe document_sync_service.py).
GENERATED_PREFIX = "documents"


def generated_key(tenant_id: int, document: Document, version: DocumentVersion, name: str) -> str:
    return f"{GENERATED_PREFIX}/tenant-{tenant_id}/{document.public_id}/{version.public_id}/{name}"


def _now() -> datetime:
    return datetime.now(UTC)


# ── Anlage ────────────────────────────────────────────────────────────────────


def document_for_original(db: Session, stored_file_id: int) -> Document | None:
    return db.scalar(
        select(Document)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(DocumentFile, DocumentFile.document_version_id == DocumentVersion.id)
        .where(DocumentFile.stored_file_id == stored_file_id, DocumentFile.role == FILE_ROLE_ORIGINAL)
    )


def register_upload(db: Session, stored_file: StoredFile) -> Document | None:
    """Legt für eine hochgeladene Datei das logische Dokument samt Version 1 und Aufträgen an.
    Nicht-Dokumente (Bilder, ZIP, Video, ...) bekommen keins und liefern None. Idempotent: hat die
    Datei schon ein Dokument, wird dieses zurückgegeben."""
    if not formats.is_document_mime(stored_file.mime_type):
        return None
    existing = document_for_original(db, stored_file.id)
    if existing is not None:
        return existing
    document = Document(
        tenant_id=stored_file.tenant_id,
        source_kind=DOCUMENT_SOURCE_UPLOAD,
        display_name=stored_file.original_name,
    )
    db.add(document)
    db.flush()
    version = _add_version(
        db, document, number=1, original=stored_file, fingerprint=stored_file.checksum_sha256, created_by=stored_file.created_by
    )
    document.current_version_id = version.id
    db.flush()
    return document


def _add_version(
    db: Session,
    document: Document,
    *,
    number: int,
    original: StoredFile,
    fingerprint: str | None,
    label: str | None = None,
    created_by: int | None = None,
) -> DocumentVersion:
    version = DocumentVersion(
        document_id=document.id, version_number=number, label=label, content_fingerprint=fingerprint, created_by=created_by
    )
    db.add(version)
    db.flush()
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=original.id, role=FILE_ROLE_ORIGINAL, is_generated=False))
    if original.mime_type == formats.PDF:
        # Bereits ein PDF: dieselbe Datei ist zugleich Darstellung, keine Neukonvertierung. Der
        # PDF-Auftrag erzeugt hier nur das Vorschaubild der ersten Seite.
        db.add(DocumentFile(document_version_id=version.id, stored_file_id=original.id, role=FILE_ROLE_PDF, is_generated=False))
        enqueue_job(db, version, JOB_KIND_PDF, tenant_id=document.tenant_id)
    elif formats.needs_conversion(original.mime_type):
        enqueue_job(db, version, JOB_KIND_PDF, tenant_id=document.tenant_id)
    if formats.extraction_parser(original.mime_type) is not None:
        enqueue_job(db, version, JOB_KIND_EXTRACT, tenant_id=document.tenant_id)
    else:
        db.add(DocumentExtraction(document_version_id=version.id, status="unsupported", warnings=[]))
    db.flush()
    return version


def enqueue_job(db: Session, version: DocumentVersion, kind: str, *, tenant_id: int, reset: bool = False) -> None:
    """Legt den Auftrag an (höchstens einer je Version und Art). reset=True stellt einen
    abgeschlossenen/fehlgeschlagenen Auftrag erneut in die Warteschlange (erneute Verarbeitung);
    ein gerade laufender bleibt unberührt."""
    statement = pg_insert(DocumentJob).values(
        tenant_id=tenant_id, document_version_id=version.id, kind=kind, status="queued", attempts=0,
        max_attempts=_max_attempts(),
    )
    if reset:
        statement = statement.on_conflict_do_update(
            constraint="uq_document_job_version_kind",
            set_={
                "status": "queued", "attempts": 0, "result": None, "last_error": None, "run_after": func.now(),
                "lease_owner": None, "lease_expires_at": None, "started_at": None, "finished_at": None,
                "updated_at": func.now(),
            },
            where=DocumentJob.status != "running",
        )
    else:
        statement = statement.on_conflict_do_nothing(constraint="uq_document_job_version_kind")
    db.execute(statement)


def _max_attempts() -> int:
    from app.core.config import settings

    return settings.document_job_max_attempts


def requeue_failed(db: Session, document: Document) -> int:
    """Erneute Verarbeitung der aktuellen Version: fehlgeschlagene/gesperrte Aufträge und
    Extraktionen mit Fehlerstatus werden zurückgesetzt. Gibt die Anzahl neu eingereihter Jobs zurück."""
    if document.current_version_id is None:
        return 0
    jobs = list(
        db.scalars(
            select(DocumentJob).where(
                DocumentJob.document_version_id == document.current_version_id,
                DocumentJob.status.in_(("failed", "blocked")),
            )
        )
    )
    version = db.get(DocumentVersion, document.current_version_id)
    for job in jobs:
        enqueue_job(db, version, job.kind, tenant_id=document.tenant_id, reset=True)
    return len(jobs)


# ── Protokollexporte ──────────────────────────────────────────────────────────


@dataclass
class ExportVersionResult:
    document: Document
    version: DocumentVersion
    created: bool


def record_protocol_export(
    db: Session,
    *,
    tenant_id: int,
    protocol_id: int,
    export_kind: str,
    display_name: str,
    stored_file: StoredFile,
    fingerprint: str,
    label: str | None,
    created_by: int | None = None,
) -> ExportVersionResult:
    """Ordnet eine neu erzeugte Exportdatei dem logischen Dokument (protocol_id, export_kind) zu.

    Inhaltlich neu (anderer Fingerprint als die aktuelle Version) -> neue Version, die zur
    aktuellen wird. Gleicher Inhalt -> die Darstellung der aktuellen Version wird durch die neue
    Datei ersetzt (z. B. geänderte Vorlage), es entsteht keine Version."""
    document = lock_export_document(
        db, tenant_id=tenant_id, protocol_id=protocol_id, export_kind=export_kind, display_name=display_name
    )
    document.display_name = display_name
    document.updated_at = _now()
    current = db.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if current is not None and current.content_fingerprint == fingerprint:
        _replace_export_rendition(db, current, stored_file)
        if label:
            current.label = label
        db.flush()
        return ExportVersionResult(document=document, version=current, created=False)
    number = (db.scalar(select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)) or 0) + 1
    version = _add_version(db, document, number=number, original=stored_file, fingerprint=fingerprint, label=label, created_by=created_by)
    document.current_version_id = version.id
    db.flush()
    return ExportVersionResult(document=document, version=version, created=True)


def lock_export_document(db: Session, *, tenant_id: int, protocol_id: int, export_kind: str, display_name: str) -> Document:
    """Legt das Export-Dokument bei Bedarf an und sperrt seine Zeile bis zum Ende der Transaktion.
    Serialisiert gleichzeitige Exporte (Versionsnummern, Übernahme der Exporthistorie)."""
    db.execute(
        pg_insert(Document)
        .values(
            tenant_id=tenant_id, source_kind=DOCUMENT_SOURCE_PROTOCOL_EXPORT, display_name=display_name,
            protocol_id=protocol_id, export_kind=export_kind,
        )
        .on_conflict_do_nothing(index_elements=["protocol_id", "export_kind"], index_where=text("protocol_id IS NOT NULL"))
    )
    return db.scalar(
        select(Document)
        .where(Document.protocol_id == protocol_id, Document.export_kind == export_kind)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def document_tenant_id(db: Session, version: DocumentVersion) -> int:
    return db.scalar(select(Document.tenant_id).where(Document.id == version.document_id))


def _replace_export_rendition(db: Session, version: DocumentVersion, stored_file: StoredFile) -> None:
    """Neue Datei mit gleichem Inhalt: Original und PDF der Version zeigen auf die neue Datei. Die
    alte Exportdatei gehört weiter ihrem document_export und fällt unter dessen Aufbewahrung."""
    db.execute(
        delete(DocumentFile).where(DocumentFile.document_version_id == version.id, DocumentFile.is_generated.is_(False))
    )
    db.flush()
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=stored_file.id, role=FILE_ROLE_ORIGINAL, is_generated=False))
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=stored_file.id, role=FILE_ROLE_PDF, is_generated=False))
    version.updated_at = _now()
    # Neue Darstellung -> Vorschaubild neu erzeugen.
    enqueue_job(db, version, JOB_KIND_PDF, tenant_id=document_tenant_id(db, version), reset=True)


# ── Löschen und Aufräumen ─────────────────────────────────────────────────────


def _delete_generated_files(db: Session, stored_file_ids: list[int]) -> None:
    if not stored_file_ids:
        return
    files = list(db.scalars(select(StoredFile).where(StoredFile.id.in_(stored_file_ids))))
    keys = [stored_file.storage_path for stored_file in files]
    for stored_file in files:
        db.delete(stored_file)
    db.flush()
    store = get_object_store()
    for key in keys:
        # Wie FileService.delete_stored_file: erst DB, dann Objekt (über das Journal).
        store.delete(db, MAIN, key)


def _generated_file_ids(db: Session, version_ids: list[int]) -> list[int]:
    if not version_ids:
        return []
    return list(
        db.scalars(
            select(DocumentFile.stored_file_id).where(
                DocumentFile.document_version_id.in_(version_ids), DocumentFile.is_generated.is_(True)
            )
        )
    )


def delete_document(db: Session, document: Document) -> None:
    """Entfernt das logische Dokument samt der von der Verarbeitung erzeugten Dateien. Originale
    und Exportdateien bleiben unangetastet - sie gehören ihrer Herkunft."""
    version_ids = list(db.scalars(select(DocumentVersion.id).where(DocumentVersion.document_id == document.id)))
    generated = _generated_file_ids(db, version_ids)
    db.execute(update(Document).where(Document.id == document.id).values(current_version_id=None))
    db.execute(delete(Document).where(Document.id == document.id))
    db.flush()
    _delete_generated_files(db, generated)


def _delete_version(db: Session, document: Document, version: DocumentVersion) -> None:
    generated = _generated_file_ids(db, [version.id])
    if document.current_version_id == version.id:
        document.current_version_id = None
    db.flush()
    db.execute(delete(DocumentVersion).where(DocumentVersion.id == version.id))
    db.flush()
    _delete_generated_files(db, generated)
    remaining = db.scalar(
        select(DocumentVersion.id)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    if remaining is None:
        delete_document(db, document)
    elif document.current_version_id is None:
        document.current_version_id = remaining
        db.flush()


def release_original(db: Session, stored_file_id: int) -> None:
    """Muss vor dem Löschen einer stored_file aufgerufen werden, die Original eines Dokuments sein
    kann: ein Upload-Dokument verschwindet ganz, bei einem Export nur die betroffene Version."""
    rows = db.execute(
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(DocumentFile, DocumentFile.document_version_id == DocumentVersion.id)
        .where(DocumentFile.stored_file_id == stored_file_id, DocumentFile.role == FILE_ROLE_ORIGINAL)
    ).all()
    for document, version in rows:
        if document.source_kind == DOCUMENT_SOURCE_UPLOAD:
            delete_document(db, document)
        else:
            _delete_version(db, document, version)


def remove_versions_without_original(db: Session, *, limit: int) -> int:
    """Sicherheitsnetz für Löschpfade, die release_original nicht aufrufen (document_file hängt
    per ON DELETE CASCADE an stored_file): Versionen ohne Originaldatei werden entfernt."""
    orphaned = db.execute(
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            ~select(DocumentFile.id)
            .where(DocumentFile.document_version_id == DocumentVersion.id, DocumentFile.role == FILE_ROLE_ORIGINAL)
            .exists()
        )
        .limit(limit)
    ).all()
    for document, version in orphaned:
        # Ein früherer Durchlauf dieser Schleife kann das Dokument bereits entfernt haben.
        if db.scalar(select(DocumentVersion.id).where(DocumentVersion.id == version.id)) is None:
            continue
        if document.source_kind == DOCUMENT_SOURCE_UPLOAD:
            delete_document(db, document)
        else:
            _delete_version(db, document, version)
    return len(orphaned)


def remove_orphaned_generated_files(db: Session, *, limit: int, min_age_minutes: int = 60) -> int:
    """Erzeugte Dateien (Präfix documents/), auf die kein document_file mehr zeigt - z. B. nach
    einem Absturz zwischen Objekt-Upload und Commit oder einer Mandanten-Bereinigung."""
    orphans = list(
        db.scalars(
            select(StoredFile.id)
            .where(
                StoredFile.storage_path.like(f"{GENERATED_PREFIX}/%"),
                StoredFile.created_at < func.now() - text(f"interval '{int(min_age_minutes)} minutes'"),
                ~select(DocumentFile.id).where(DocumentFile.stored_file_id == StoredFile.id).exists(),
            )
            .limit(limit)
        )
    )
    _delete_generated_files(db, orphans)
    return len(orphans)
