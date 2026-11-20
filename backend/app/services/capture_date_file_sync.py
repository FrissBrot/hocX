"""Job capture_date_file_sync: korrigiertes Aufnahmedatum in die Bilddatei schreiben bzw. das
Original zurückschreiben (Migration 0203).

Ablauf: Korrigieren, Verschieben und «Original wiederherstellen» ändern wie bisher sofort die
DB (image_metadata_service.set_capture_correction - Anzeige, Sortierung, Filter und
Termin-Zuordnung gelten damit sofort) und setzen ``capture_file_state = 'pending'``. Dieser Job
holt offene Zeilen mandantenübergreifend, je Datei eine Zeilensperre (``FOR UPDATE SKIP LOCKED``,
ein Commit pro Datei), und berechnet das Ziel aus dem DANN aktuellen Stand - idempotent und
unempfindlich gegen Korrektur → Wiederherstellen vor dem Lauf:

- korrigiert                         → Korrektur in die Datei schreiben (``written``), beim ersten
                                        Mal das Original der Datumsfelder in
                                        ``capture_exif_original`` sichern
- nicht korrigiert, Original gesichert → Original zurückschreiben, Sicherung löschen (NULL)
- sonst                               → nichts zu tun (NULL)

Die Datei wird nie überschrieben, sondern als neues Objekt neben die alte gelegt; ``storage_path``,
``checksum_sha256`` und ``file_size_bytes`` werden in derselben Transaktion nachgeführt, das alte
Objekt per Tombstone gelöscht (physisch erst nach dem Commit durch storage_purge, mit
Copy-on-Write für einen laufenden Backup-Hold). Ein Rollback lässt so die alte Datei samt DB-Stand
unverändert; das neue, nie registrierte Objekt räumt upload_pipeline nach dem Rollback weg.

Folgen der neuen Prüfsumme (siehe CHANGELOG 1.4.1):
- Duplikaterkennung (Galerie, Vorab-Abgleich, Abgabebox) prüft auch ``source_checksum_sha256``;
  ist der leer, bekommt er hier den ursprünglichen Hash - die Originaldatei wird weiterhin als
  Duplikat erkannt.
- Vorschaubilder, Abmessungen, Wahrnehmungs-Hash und Qualitätswerte bleiben (Pixel unverändert);
  der Ähnlichkeits-Cache rechnet einmal neu (Schlüssel enthält die Prüfsumme).
- ETag des Objekts ändert sich; die Inline-Ansicht darf ihren Browser-Cache behalten (gleiche
  Pixel), Downloads kommen ohnehin frisch bzw. über die Exportkopie.

Übersprungen: Papierkorb (trash_scope), Dateien mit Virenbefund oder ungeprüfte (``scan_status``
nicht ``clean`` - sie bleiben ``pending`` bis zum Befund), Nicht-Bilder (Live-Photo-Clips). Formate,
die kein Datum aufnehmen können, werden ``unsupported`` (Datei unverändert, die DB-Korrektur gilt
weiter). Fehler: ``failed`` + Fehlerprotokoll; eine neue Korrektur versucht es erneut.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import (
    ObjectNotFound,
    StorageUnavailable,
    StorageWriteFenced,
    get_object_store,
    new_object_key,
)
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import StoredFile
from app.services import exif_date_write, image_metadata_service
from app.services.capture_date import corrected_exif_stamp
from app.services.stored_file_location import namespace_for_stored_file
from app.services.upload_pipeline import _track_uncommitted_object

_logger = logging.getLogger(__name__)

STATE_PENDING = "pending"
STATE_WRITTEN = "written"
STATE_UNSUPPORTED = "unsupported"
STATE_FAILED = "failed"

# Höchstens so viele Dateien je Lauf und so lange - der Rest folgt im nächsten Tick (Takt 1 min;
# 500 Bilder einer Mehrfachauswahl sind damit nach wenigen Minuten in den Dateien).
BATCH = 100
TIME_BUDGET_SECONDS = 50.0
# Grössere Dateien werden nicht in den Speicher geladen (Galerie-Bilder sind viel kleiner).
# Bilder kommen höchstens als Galerie-Upload (deutlich unter 50 MB); ganze Datei im Speicher, mehrere
# Kopien gleichzeitig - die Grenze hält die Spitze im job-worker klein (Security-Review F6).
MAX_FILE_BYTES = 50 * 1024 * 1024


def _claim_next(db: Session) -> StoredFile | None:
    return db.scalars(
        select(StoredFile)
        .where(
            StoredFile.capture_file_state == STATE_PENDING,
            StoredFile.deleted_at.is_(None),
            StoredFile.scan_status == "clean",
            StoredFile.mime_type.like("image/%"),
        )
        .order_by(StoredFile.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def _replace_object(db: Session, stored_file: StoredFile, namespace: str, content: bytes) -> None:
    store = get_object_store()
    old_key = stored_file.storage_path
    parent = PurePosixPath(old_key).parent.as_posix()
    new_key = new_object_key(*([] if parent in ("", ".") else parent.split("/")), filename=old_key)
    store.put_bytes(db, namespace, new_key, content, content_type=stored_file.mime_type)
    _track_uncommitted_object(db, namespace, new_key)
    store.delete(db, namespace, old_key)
    if not stored_file.source_checksum_sha256:
        # Die hochgeladene Datei soll weiterhin als Duplikat erkannt werden.
        stored_file.source_checksum_sha256 = stored_file.checksum_sha256
    stored_file.storage_path = new_key
    stored_file.checksum_sha256 = hashlib.sha256(content).hexdigest()
    stored_file.file_size_bytes = len(content)


def _sync_one(db: Session, stored_file: StoredFile) -> str:
    """Verarbeitet eine gesperrte Zeile; der Aufrufer committet. Gibt das Ergebnis zurück."""
    wants_correction = stored_file.capture_corrected_at is not None
    original = stored_file.capture_exif_original
    if not wants_correction and original is None:
        stored_file.capture_file_state = None
        return "nothing"
    namespace = namespace_for_stored_file(db, stored_file)
    store = get_object_store()
    info = store.head(namespace, stored_file.storage_path)
    if info is None:
        raise ObjectNotFound(stored_file.storage_path)
    if info.size > MAX_FILE_BYTES:
        stored_file.capture_file_state = STATE_UNSUPPORTED
        return STATE_UNSUPPORTED
    data = store.get_bytes(namespace, stored_file.storage_path, max_bytes=MAX_FILE_BYTES)

    if wants_correction:
        if stored_file.metadata_scanned_at is None:
            # Noch nie analysiert: das Original JETZT einlesen, bevor die Datei das korrigierte
            # Datum trägt - sonst hielte ein späterer Backfill es für das EXIF-Original.
            image_metadata_service.apply_server_analysis(
                stored_file, image_metadata_service.extract_image_metadata(data), source="backfill"
            )
        stamp = corrected_exif_stamp(stored_file)
        try:
            content, record = exif_date_write.write_capture_date(data, stamp or "", record_original=original is None)
        except exif_date_write.ExifDateUnsupported:
            stored_file.capture_file_state = STATE_UNSUPPORTED
            return STATE_UNSUPPORTED
        if record is not None:
            stored_file.capture_exif_original = record
        stored_file.capture_file_state = STATE_WRITTEN
        result = STATE_WRITTEN
    else:
        content = exif_date_write.restore_capture_date(data, original)
        stored_file.capture_exif_original = None
        stored_file.capture_file_state = None
        result = "restored"
    if content != data:
        _replace_object(db, stored_file, namespace, content)
    return result


def _mark_failed(db: Session, stored_file_id: int, exc: Exception, tenant_id: int | None) -> None:
    from app.core.error_log import record_system_error

    db.rollback()
    bind_tenant_scope(db, None)
    try:
        stored_file = db.get(StoredFile, stored_file_id)
        if stored_file is not None and stored_file.capture_file_state == STATE_PENDING:
            stored_file.capture_file_state = STATE_FAILED
            db.commit()
    except Exception:  # noqa: BLE001 - Status nicht setzbar; der Fehler selbst wird unten protokolliert
        db.rollback()
        _logger.exception("Aufnahmedatum in Datei: Status für %s nicht setzbar", stored_file_id)
    record_system_error(db, exc=exc, tenant_id=tenant_id)


def process_pending(db: Session, *, limit: int = BATCH, time_budget_seconds: float = TIME_BUDGET_SECONDS) -> dict[str, int]:
    """Ein Tick des Jobs (siehe Moduldocstring). Gibt Zähler je Ergebnis zurück."""
    counts = {"written": 0, "restored": 0, "unsupported": 0, "nothing": 0, "failed": 0}
    started = time.monotonic()
    for _ in range(limit):
        if time.monotonic() - started > time_budget_seconds:
            break
        stored_file = _claim_next(db)
        if stored_file is None:
            db.commit()
            break
        stored_file_id, tenant_id = stored_file.id, stored_file.tenant_id
        # Zweites Netz (RLS): solange diese Datei bearbeitet wird, sieht die Session nur ihren Mandanten.
        bind_tenant_scope(db, tenant_id)
        try:
            result = _sync_one(db, stored_file)
            db.commit()
        except (StorageWriteFenced, StorageUnavailable):
            # Speicher gesperrt (Migration/Wartung) oder nicht erreichbar: Datei bleibt pending,
            # nächster Tick versucht es erneut.
            db.rollback()
            bind_tenant_scope(db, None)
            _logger.info("Aufnahmedatum in Datei: Speicher nicht verfügbar, nächster Lauf")
            break
        except Exception as exc:  # noqa: BLE001 - eine Datei hält den Rest nicht auf; Fehlerprotokoll
            _logger.warning("Aufnahmedatum in Datei: stored_file %s fehlgeschlagen", stored_file_id, exc_info=True)
            _mark_failed(db, stored_file_id, exc, tenant_id)
            counts["failed"] += 1
            continue
        finally:
            bind_tenant_scope(db, None)
        counts[result] += 1
    return counts
