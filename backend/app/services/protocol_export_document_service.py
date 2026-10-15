"""Protokollexporte als versionierte logische Dokumente.

Fachliche Identität ist (protocol_id, Exportart) - nie der Dateiname. Exportarten:

    protocol_export_cache.export_format -> document.export_kind
    'pdf'             -> 'protocol'      (das Protokoll selbst)
    'pdf-todos'       -> 'todos'         (Todo-Liste, alle)
    'pdf-todos-open'  -> 'todos_open'    (Todo-Liste, nur offene)
    'pdf-events'      -> 'events'        (Terminübersicht)

'latex' (der LaTeX-Quelltext für Fachleute) ist kein Dokument im Dateien-Tab.

Bestehende Exporte (vor Einführung der Dokumentebene) werden je (Protokoll, Exportart) einmal
komplett in zeitlicher Reihenfolge übernommen - entweder vom document_sync-Loop oder spätestens
beim nächsten Export dieser Art, bevor die neue Version angehängt wird. So bleibt die Reihenfolge
der Versionen immer korrekt. Exporte, deren Datei nicht mehr im Speicher liegt (Aufbewahrung
EXPORT_RETENTION_DAYS abgelaufen), werden übersprungen; ab Einführung schont die Aufbewahrung
Dateien, die zu einer Dokumentversion gehören (ExportService.cleanup_old_generated_exports).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import MAIN, get_object_store
from app.models import Protocol, ProtocolExportCache, StoredFile
from app.models.document_entities import Document
from app.services import document_service

_logger = logging.getLogger(__name__)

EXPORT_KINDS: dict[str, str] = {
    "pdf": "protocol",
    "pdf-todos": "todos",
    "pdf-todos-open": "todos_open",
    "pdf-events": "events",
}
# Obergrenze der beim Backfill übernommenen Altexporte je Protokoll und Exportart.
MAX_HISTORY = 100


def fingerprint(body: str | None) -> str:
    """Inhaltlicher Fingerabdruck: derselbe Body, an dem ExportService.export_pdf bereits
    entscheidet, ob sich das Protokoll geändert hat (und die Protokollversion hochzählt)."""
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def _retention_cutoff() -> datetime:
    """Ältere Exportdateien hat cleanup_old_generated_exports bereits gelöscht (vor Einführung
    der Dokumentebene ohne Ausnahme) - sie gar nicht erst prüfen."""
    return datetime.now(UTC) - timedelta(days=max(settings.export_retention_days - 1, 0))


def _document(db: Session, protocol_id: int, export_kind: str) -> Document | None:
    return db.scalar(select(Document).where(Document.protocol_id == protocol_id, Document.export_kind == export_kind))


def _backfill_group(db: Session, protocol: Protocol, export_format: str, *, exclude_stored_file_id: int | None = None) -> int:
    """Übernimmt alle bisherigen Exporte einer Art chronologisch als Versionen."""
    export_kind = EXPORT_KINDS[export_format]
    rows = db.execute(
        select(ProtocolExportCache, StoredFile)
        .join(StoredFile, StoredFile.id == ProtocolExportCache.generated_file_id)
        .where(
            ProtocolExportCache.protocol_id == protocol.id,
            ProtocolExportCache.export_format == export_format,
            ProtocolExportCache.created_at >= _retention_cutoff(),
        )
        .order_by(ProtocolExportCache.created_at.asc(), ProtocolExportCache.id.asc())
        .limit(MAX_HISTORY)
    ).all()
    store = get_object_store()
    count = 0
    for cache, stored_file in rows:
        if stored_file.id == exclude_stored_file_id or stored_file.tenant_id != protocol.tenant_id:
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
            fingerprint=fingerprint(cache.latex_source),
            label=None,
        )
        count += 1
    return count


def record_export(
    db: Session,
    *,
    protocol: Protocol,
    export_format: str,
    stored_file: StoredFile,
    body: str | None,
    label: str | None,
    created_by: int | None,
) -> document_service.ExportVersionResult | None:
    """Vom ExportService nach jedem neuen Export aufgerufen (gleiche Transaktion)."""
    export_kind = EXPORT_KINDS.get(export_format)
    if export_kind is None:
        return None
    if _document(db, protocol.id, export_kind) is None:
        _backfill_group(db, protocol, export_format, exclude_stored_file_id=stored_file.id)
    return document_service.record_protocol_export(
        db,
        tenant_id=protocol.tenant_id,
        protocol_id=protocol.id,
        export_kind=export_kind,
        display_name=stored_file.original_name,
        stored_file=stored_file,
        fingerprint=fingerprint(body),
        label=label,
        created_by=created_by,
    )


def backfill(db: Session, *, limit: int) -> int:
    """document_sync: (Protokoll, Exportart)-Gruppen mit Exporten, aber noch ohne Dokument."""
    candidates = db.execute(
        select(ProtocolExportCache.protocol_id, ProtocolExportCache.export_format)
        .where(
            ProtocolExportCache.export_format.in_(list(EXPORT_KINDS)),
            ProtocolExportCache.generated_file_id.is_not(None),
            ProtocolExportCache.created_at >= _retention_cutoff(),
        )
        .group_by(ProtocolExportCache.protocol_id, ProtocolExportCache.export_format)
        .order_by(ProtocolExportCache.protocol_id)
    ).all()
    groups = 0
    for protocol_id, export_format in candidates:
        if groups >= limit:
            break
        if _document(db, protocol_id, EXPORT_KINDS[export_format]) is not None:
            continue
        protocol = db.get(Protocol, protocol_id)
        if protocol is None:
            continue
        with db.begin_nested():
            created = _backfill_group(db, protocol, export_format)
        if created:
            groups += 1
    return groups
