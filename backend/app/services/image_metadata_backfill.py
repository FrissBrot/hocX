"""Gezielter Metadaten-Backfill für bereits gespeicherte Bilder.

Keine pauschale Neuanalyse: Kandidaten sind ausschliesslich Bilder, die seit Einführung der
Metadatenspalten (Migration 0113) noch nie serverseitig analysiert wurden
(metadata_scanned_at IS NULL) UND denen mindestens eine rekonstruierbare Angabe fehlt
(echtes Aufnahmedatum, GPS, Kamera, Abmessungen). Für die reine Unterscheidung Aufnahme- vs.
Uploaddatum braucht es keinen Backfill - exif_taken_at und created_at existieren bereits.

Ablauf je Bild: Originaldatei suchen -> nur wenn vorhanden analysieren -> fehlende Werte
ergänzen (vorhandene bleiben) -> metadata_scanned_at/metadata_scan_status setzen. Jede Charge
wird einzeln committet; ein abgebrochener Lauf setzt beim nächsten Aufruf genau dort fort, und
ein wiederholter Lauf findet nichts mehr (keine unerwünschten Änderungen). --rescan prüft auch
bereits analysierte Bilder erneut (ebenfalls nur ergänzend).

Bewusst kein Hintergrundjob und nichts beim Serverstart - Aufruf manuell, siehe
backend/scripts/backfill_image_metadata.py und UPLOAD_DUPLICATES.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import StoredFile
from app.services import image_metadata_service, photo_event_link_service, upload_precheck_service
from app.services.image_metadata_service import FIELD_GPS, FIELD_TAKEN_AT

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    checked: int = 0
    taken_at_added: int = 0
    gps_added: int = 0
    other_added: int = 0
    # Datei lesbar, aber ohne rekonstruierbare Angaben ("keine Metadaten vorhanden").
    no_metadata: int = 0
    # Original fehlt im Speicher.
    missing_files: int = 0
    # Datei nicht dekodierbar oder Fehler bei der Analyse ("Analyse nicht möglich").
    failed: int = 0
    # Lesbar, Metadaten vorhanden, aber nichts davon fehlte bzw. alles widersprach.
    unchanged: int = 0
    conflicts: int = 0
    # HEIC-Konvertierungen: das Original existiert nicht mehr, das JPEG wurde trotzdem analysiert.
    converted_sources: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def not_reconstructable(self) -> int:
        return self.no_metadata + self.unchanged

    def as_dict(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "taken_at_added": self.taken_at_added,
            "gps_added": self.gps_added,
            "other_added": self.other_added,
            "not_reconstructable": self.not_reconstructable,
            "no_metadata": self.no_metadata,
            "missing_files": self.missing_files,
            "failed": self.failed,
            "conflicts": self.conflicts,
            "converted_sources": self.converted_sources,
        }


def _candidate_query(*, tenant_id: int | None, rescan: bool, after_id: int):
    missing_something = or_(
        StoredFile.exif_taken_at.is_(None),
        StoredFile.gps_latitude.is_(None),
        StoredFile.camera_model.is_(None),
        StoredFile.width.is_(None),
    )
    query = select(StoredFile).where(
        StoredFile.mime_type.like("image/%"),
        StoredFile.scan_status == "clean",
        StoredFile.id > after_id,
        missing_something,
    )
    if not rescan:
        query = query.where(StoredFile.metadata_scanned_at.is_(None))
    if tenant_id is not None:
        query = query.where(StoredFile.tenant_id == tenant_id)
    return query.order_by(StoredFile.id)


def run_backfill(
    db: Session,
    *,
    tenant_id: int | None = None,
    limit: int | None = None,
    batch_size: int = 200,
    rescan: bool = False,
    dry_run: bool = False,
) -> BackfillReport:
    """Arbeitet Kandidaten in Chargen nach id ab. dry_run analysiert, schreibt aber nichts."""
    report = BackfillReport()
    after_id = 0
    while limit is None or report.checked < limit:
        size = batch_size if limit is None else min(batch_size, limit - report.checked)
        batch = list(db.scalars(_candidate_query(tenant_id=tenant_id, rescan=rescan, after_id=after_id).limit(size).with_for_update(skip_locked=True)))
        if not batch:
            break
        for stored_file in batch:
            after_id = stored_file.id
            report.checked += 1
            # Dry-Run arbeitet auf einer losgelösten Kopie der Werte - es wird nichts geschrieben.
            _process(db, stored_file, report, target=_detached_copy(stored_file) if dry_run else stored_file)
        db.commit()  # beendet auch im Dry-Run nur die (unveränderte) Transaktion samt Sperren
    return report


_COPIED_ATTRIBUTES = (
    "id", "exif_taken_at", "exif_taken_offset", "exif_taken_source", "estimated_taken_on", "estimated_taken_set_at",
    "estimated_taken_set_by", "gps_latitude", "gps_longitude", "gps_altitude_m", "gps_direction_deg", "gps_accuracy_m",
    "gps_timestamp", "gps_source", "camera_make", "camera_model", "width", "height", "orientation",
    "metadata_scanned_at", "metadata_scan_status", "checksum_sha256", "source_checksum_sha256",
)


def _detached_copy(stored_file: StoredFile) -> SimpleNamespace:
    return SimpleNamespace(**{name: getattr(stored_file, name) for name in _COPIED_ATTRIBUTES})


def _process(db: Session, stored_file: StoredFile, report: BackfillReport, *, target: Any) -> None:
    """Analysiert `stored_file` und schreibt das Ergebnis in `target` (die Zeile selbst oder
    eine Dry-Run-Kopie)."""
    try:
        metadata = upload_precheck_service.analyze_stored_file(db, stored_file)
    except Exception as exc:  # Einzelfehler protokollieren, Lauf fortsetzen
        logger.warning("Backfill: Analyse von stored_file %s fehlgeschlagen: %s", stored_file.id, exc)
        report.failed += 1
        report.errors.append(f"{stored_file.id}: {exc}")
        image_metadata_service.mark_scan_status(target, "unreadable")
        return
    if metadata.status == "missing_file":
        report.missing_files += 1
        image_metadata_service.mark_scan_status(target, "missing_file")
        return
    if metadata.status == "unreadable":
        report.failed += 1
        image_metadata_service.mark_scan_status(target, "unreadable")
        return
    if target.source_checksum_sha256 and target.source_checksum_sha256 != target.checksum_sha256:
        report.converted_sources += 1
    before_dates = (target.exif_taken_at, target.estimated_taken_on)
    outcome = image_metadata_service.apply_server_analysis(target, metadata, source="backfill")
    if outcome.conflicts:
        report.conflicts += 1
    if FIELD_TAKEN_AT in outcome.applied:
        report.taken_at_added += 1
    if FIELD_GPS in outcome.applied:
        report.gps_added += 1
    if set(outcome.applied) - {FIELD_TAKEN_AT, FIELD_GPS}:
        report.other_added += 1
    if not outcome.applied:
        if metadata.status == "no_metadata":
            report.no_metadata += 1
        else:
            report.unchanged += 1
    if target is stored_file and (stored_file.exif_taken_at, stored_file.estimated_taken_on) != before_dates:
        photo_event_link_service.resync_photo_after_date_change(db, stored_file)
