"""Kamera-Kürzel für bestehende Fotos nachtragen (Upload-Verlauf 1.6, User-Entscheid E-13, Migration 0253).

Neue Fotos bekommen das Kürzel der Seriennummer schon beim Upload (image_metadata_service
.merge_missing_metadata). Für Fotos von vor 1.6 liest dieser Hintergrundjob die Seriennummer aus
der EXIF der Originaldatei und speichert nur das Kürzel (HMAC je Mandant, services/camera_serial.py)
in ``stored_file.camera_serial_key``. Die Seriennummer selbst wird nie gespeichert, geloggt oder
zurückgegeben.

- **Mandantengetrennt:** je Mandant ein Fortschritt in ``camera_serial_backfill``; die Session ist
  während der Arbeit an einem Mandanten an dessen RLS-Bereich gebunden (bind_tenant_scope), alle
  Abfragen filtern zusätzlich auf ``tenant_id``. Das Kürzel wird mit dem Schlüssel des Mandanten
  der Datei gerechnet.
- **In Chargen, wiederaufnehmbar:** je Mandant höchstens ``BATCH_SIZE`` Dateien nach aufsteigender ID,
  danach Commit mit ``last_file_id``. Ein abgebrochener Lauf setzt genau dort fort; die Mandanten
  kommen reihum dran (ältester Stand zuerst), damit ein grosser Verein die anderen nicht aufhält.
- **Begrenzt:** nur bis zur grössten Bild-ID beim Start (``upper_file_id``), nur saubere Bilder ohne
  Kürzel und mit Kamera-Angabe bzw. ohne Metadaten-Analyse. JPEGs werden nur bis 512 KB gelesen
  (EXIF steht am Anfang), andere Formate höchstens 64 MB.
- Prozesse ohne ``ADMIN_AUTH_SECRET`` (document-worker) rechnen kein Kürzel und lassen den Stand
  unverändert. Ein nicht erreichbarer Objektspeicher bricht den Tick ab, ohne den Stand zu verschieben.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import InvalidObjectKey, ObjectNotFound, ObjectTooLarge, StorageUnavailable, get_object_store
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import StoredFile
from app.models.upload_history_entities import CameraSerialBackfill
from app.services import image_metadata_service
from app.services.camera_serial import serial_key
from app.services.stored_file_location import namespace_for_stored_file

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
JPEG_PREFIX_BYTES = 512 * 1024
MAX_FULL_BYTES = 64 * 1024 * 1024
# Zeitbudget eines Ticks (Sekunden): danach endet er nach der laufenden Charge
TICK_SECONDS = 90

_ENROLL = text(
    """
    INSERT INTO camera_serial_backfill (tenant_id, upper_file_id)
    SELECT t.id, COALESCE(
        (SELECT max(s.id) FROM stored_file s WHERE s.tenant_id = t.id AND s.mime_type LIKE :image_pattern), 0
    )
      FROM tenant t
     WHERE NOT EXISTS (SELECT 1 FROM camera_serial_backfill b WHERE b.tenant_id = t.id)
    ON CONFLICT (tenant_id) DO NOTHING
    """
)


@dataclass
class TickReport:
    tenants: int = 0
    checked: int = 0
    keyed: int = 0


def _read_metadata(db: Session, stored: StoredFile) -> image_metadata_service.ImageMetadata:
    """EXIF der Originaldatei; status "missing_file", wenn sie nicht mehr im Speicher liegt."""
    store = get_object_store()
    namespace = namespace_for_stored_file(db, stored)
    try:
        if (stored.mime_type or "").lower() in ("image/jpeg", "image/jpg"):
            prefix = bytearray()
            chunks = store.iter_bytes(namespace, stored.storage_path)
            try:
                for chunk in chunks:
                    prefix.extend(chunk)
                    if len(prefix) >= JPEG_PREFIX_BYTES:
                        break
            finally:
                close = getattr(chunks, "close", None)
                if close is not None:
                    close()
            metadata = image_metadata_service.extract_image_metadata(bytes(prefix))
            complete = len(prefix) < JPEG_PREFIX_BYTES
            if complete or metadata.camera_serial or metadata.camera_make or metadata.camera_model:
                return metadata
        content = store.get_bytes(namespace, stored.storage_path, max_bytes=MAX_FULL_BYTES)
    except (ObjectNotFound, InvalidObjectKey):
        return image_metadata_service.ImageMetadata(status="missing_file")
    except ObjectTooLarge:
        return image_metadata_service.ImageMetadata(status="unreadable")
    return image_metadata_service.extract_image_metadata(content)


def _candidates(db: Session, state: CameraSerialBackfill) -> list[StoredFile]:
    return list(
        db.scalars(
            select(StoredFile)
            .where(
                StoredFile.tenant_id == state.tenant_id,
                StoredFile.id > state.last_file_id,
                StoredFile.id <= state.upper_file_id,
                StoredFile.mime_type.like("image/%"),
                StoredFile.scan_status == "clean",
                StoredFile.camera_serial_key.is_(None),
                or_(StoredFile.camera_make.is_not(None), StoredFile.camera_model.is_not(None), StoredFile.metadata_scanned_at.is_(None)),
            )
            .order_by(StoredFile.id)
            .limit(BATCH_SIZE)
            # Auch Dateien im Papierkorb: nach dem Wiederherstellen gehören sie wieder in ihre Kameragruppe
            .execution_options(include_trashed=True)
        )
    )


def process_batch(db: Session, state: CameraSerialBackfill) -> int:
    """Eine Charge eines Mandanten; committet den Stand. Gibt die Zahl gelesener Dateien zurück."""
    bind_tenant_scope(db, state.tenant_id)
    try:
        files = _candidates(db, state)
        now = datetime.now(UTC)
        if not files:
            state.finished_at = now
            state.updated_at = now
            db.commit()
            return 0
        errors: list[Exception] = []
        for stored in files:
            try:
                metadata = _read_metadata(db, stored)
            except StorageUnavailable:
                raise  # Speicher weg: Tick abbrechen, Stand nicht verschieben
            except Exception as exc:  # noqa: BLE001 - eine Datei darf den Job nicht anhalten (Security-Review N-3)
                state.checked += 1
                state.failed += 1
                errors.append(exc)
                continue
            state.checked += 1
            if metadata.status == "missing_file":
                state.missing += 1
                continue
            if metadata.status == "unreadable":
                state.failed += 1
                continue
            key = serial_key(
                stored.tenant_id, stored.camera_make or metadata.camera_make, stored.camera_model or metadata.camera_model,
                metadata.camera_serial,
            )
            if key is None:
                state.no_serial += 1
                continue
            written = db.execute(
                update(StoredFile)
                .where(StoredFile.id == stored.id, StoredFile.tenant_id == state.tenant_id, StoredFile.camera_serial_key.is_(None))
                .values(camera_serial_key=key)
                .execution_options(synchronize_session=False)
            ).rowcount
            state.keyed += int(written or 0)
        state.last_file_id = files[-1].id
        state.updated_at = now
        db.commit()
        if errors:
            # Nach dem Commit (record_system_error committet selbst); nur der erste Fehler der
            # Charge, ohne Metadaten - die Seriennummer steht nie in der Ausnahme.
            from app.core.error_log import record_system_error

            record_system_error(db, exc=errors[0], tenant_id=state.tenant_id)
        return len(files)
    except BaseException:
        db.rollback()
        raise
    finally:
        bind_tenant_scope(db, None)


def run_tick(db: Session, *, max_files: int | None = None, deadline_seconds: float = TICK_SECONDS) -> TickReport:
    """Ein Tick des Jobs: neue Mandanten aufnehmen, dann reihum Chargen bis zum Budget."""
    report = TickReport()
    if settings.is_secretless_process or not settings.admin_auth_secret:
        return report
    budget = max_files if max_files is not None else settings.camera_serial_backfill_files_per_tick
    started = time.monotonic()
    db.execute(_ENROLL, {"image_pattern": "image/%"})
    db.commit()
    seen: set[int] = set()
    while report.checked < budget and time.monotonic() - started < deadline_seconds:
        state = db.scalar(
            select(CameraSerialBackfill)
            .where(CameraSerialBackfill.finished_at.is_(None), CameraSerialBackfill.tenant_id.not_in(seen or {0}))
            .order_by(CameraSerialBackfill.updated_at.asc().nulls_first(), CameraSerialBackfill.tenant_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if state is None:
            if not seen:
                break
            seen.clear()  # alle offenen Mandanten waren dran - nächste Runde
            continue
        seen.add(state.tenant_id)
        report.tenants += 1
        before = state.keyed
        report.checked += process_batch(db, state)
        report.keyed += state.keyed - before
    if report.checked:
        logger.info("camera_serial_backfill: %s Dateien gelesen, %s Kürzel gesetzt", report.checked, report.keyed)
    return report
