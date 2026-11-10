"""Protokollexporte der Dokument-Engine als versionierte logische Dokumente.

Fachliche Identität ist (protocol_id, Exportart) - nie der Dateiname oder die Vorlage. Exportart
ist der Dokumenttyp der Engine (``document_export.document_type``): «protocol» (das Protokoll
selbst), «invitation», «agenda», «attendance» sowie Listen mit Protokollbezug (z. B. «todos»,
«events»). Jeder PDF-Export mit Protokollbezug wird so zur Version eines Dokuments im
Dateien-Tab; Exporte ohne Protokollbezug (Mandantenlisten, Statistik) gehören nicht dazu.

Fingerabdruck einer Version ist der Inhalts-Hash der Engine (``document_export.content_hash``,
app/documents/hashing.py). Für Protokolle ist er unabhängig von Vorlage, Brand-Profil und Sprache:
eine reine Designänderung ersetzt nur die Darstellung der aktuellen Version, neuer Inhalt ergibt
eine neue Version - dieselbe Regel, nach der die Engine die Protokollversion hochzählt.

Bestehende Exporte (vor Einführung der Dokumentebene) werden je (Protokoll, Exportart) einmal in
zeitlicher Reihenfolge übernommen - vom document_sync-Loop oder spätestens beim nächsten Export
dieser Art, bevor die neue Version angehängt wird. Exporte, deren Datei schon freigegeben ist
(Aufbewahrung EXPORT_RETENTION_DAYS, nur neuester Protokoll-Export), werden übersprungen; ab
Einführung schont die Aufbewahrung Dateien, die zu einer Dokumentversion gehören
(app/documents/service.py, _release_files).

Bis Release 1.2.0 hing dieser Dienst am TeX-Export (protocol_export_cache); die Exportarten von
damals (protocol/todos/todos_open/events) entsprechen den Dokumenttypen der Engine.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import MAIN, get_object_store
from app.models import DocumentExport, Protocol, StoredFile
from app.models.document_entities import Document
from app.services import document_service

_logger = logging.getLogger(__name__)

# Obergrenze der beim Backfill übernommenen Altexporte je Protokoll und Exportart.
MAX_HISTORY = 100


def fingerprint(export: DocumentExport, stored_file: StoredFile) -> str:
    """Inhaltlicher Fingerabdruck einer Version: der Inhalts-Hash der Engine; ältere Exporte ohne
    Hash (aus dem TeX-Export übernommen) über die ausgelieferten Bytes."""
    if export.content_hash:
        return export.content_hash
    return stored_file.checksum_sha256 or hashlib.sha256(f"stored_file:{stored_file.id}".encode()).hexdigest()


def _retention_cutoff() -> datetime:
    """Ältere Exportdateien hat cleanup_old_generated_exports bereits freigegeben - sie gar nicht
    erst prüfen."""
    return datetime.now(UTC) - timedelta(days=max(settings.export_retention_days - 1, 0))


def _document(db: Session, protocol_id: int, export_kind: str) -> Document | None:
    return db.scalar(select(Document).where(Document.protocol_id == protocol_id, Document.export_kind == export_kind))


def _backfill_group(db: Session, protocol: Protocol, export_kind: str, *, exclude_export_id: int | None = None) -> int:
    """Übernimmt alle bisherigen Exporte einer Art chronologisch als Versionen."""
    rows = db.execute(
        select(DocumentExport, StoredFile)
        .join(StoredFile, StoredFile.id == DocumentExport.stored_file_id)
        .where(
            DocumentExport.protocol_id == protocol.id,
            DocumentExport.document_type == export_kind,
            DocumentExport.created_at >= _retention_cutoff(),
        )
        .order_by(DocumentExport.created_at.asc(), DocumentExport.id.asc())
        .limit(MAX_HISTORY)
    ).all()
    store = get_object_store()
    count = 0
    for export, stored_file in rows:
        if export.id == exclude_export_id or stored_file.tenant_id != protocol.tenant_id:
            continue
        if document_service.document_for_original(db, stored_file.id) is not None:
            continue
        if not store.exists(MAIN, stored_file.storage_path):
            continue
        document_service.record_protocol_export(
            db,
            tenant_id=protocol.tenant_id,
            protocol_id=protocol.id,
            export_kind=export_kind,
            display_name=stored_file.original_name,
            stored_file=stored_file,
            fingerprint=fingerprint(export, stored_file),
            label=export.version_label,
            created_by=export.created_by,
        )
        count += 1
    return count


def record_export(
    db: Session,
    *,
    protocol: Protocol,
    export: DocumentExport,
    stored_file: StoredFile,
) -> document_service.ExportVersionResult | None:
    """Von documents.service.render nach jedem PDF-Export mit Protokollbezug aufgerufen (gleiche
    Transaktion, vor dem Freigeben älterer Dateien)."""
    export_kind = export.document_type
    # Zeile sperren (bzw. anlegen) - ein gleichzeitiger Export derselben Art wartet, bis diese
    # Transaktion die Historie übernommen und ihre Version angehängt hat.
    document = document_service.lock_export_document(
        db, tenant_id=protocol.tenant_id, protocol_id=protocol.id, export_kind=export_kind, display_name=stored_file.original_name,
    )
    if document.current_version_id is None:
        _backfill_group(db, protocol, export_kind, exclude_export_id=export.id)
    return document_service.record_protocol_export(
        db,
        tenant_id=protocol.tenant_id,
        protocol_id=protocol.id,
        export_kind=export_kind,
        display_name=stored_file.original_name,
        stored_file=stored_file,
        fingerprint=fingerprint(export, stored_file),
        label=export.version_label,
        created_by=export.created_by,
    )


def backfill(db: Session, *, limit: int) -> int:
    """document_sync: (Protokoll, Exportart)-Gruppen mit Exporten, aber noch ohne Dokument."""
    candidates = db.execute(
        select(DocumentExport.protocol_id, DocumentExport.document_type)
        .where(
            DocumentExport.protocol_id.is_not(None),
            DocumentExport.stored_file_id.is_not(None),
            DocumentExport.created_at >= _retention_cutoff(),
        )
        .group_by(DocumentExport.protocol_id, DocumentExport.document_type)
        .order_by(DocumentExport.protocol_id)
    ).all()
    groups = 0
    for protocol_id, export_kind in candidates:
        if groups >= limit:
            break
        if _document(db, protocol_id, export_kind) is not None:
            continue
        protocol = db.get(Protocol, protocol_id)
        if protocol is None:
            continue
        try:
            with db.begin_nested():
                created = _backfill_group(db, protocol, export_kind)
        except IntegrityError:
            # Gleichzeitig von einem Export übernommen - beim nächsten Durchlauf erledigt.
            continue
        if created:
            groups += 1
    return groups
