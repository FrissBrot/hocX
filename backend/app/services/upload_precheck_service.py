"""SHA-256-Vorab-Abgleich vor dem Upload und Ergänzen von Metadaten vorhandener Bilder.

POST /files/upload-precheck: Der Browser schickt je Datei Hash, Dateiinfos und lokal
extrahierte Metadaten, bevor er Bytes überträgt. Der Server meldet je Datei:

- upload_required:   unbekannt im Mandanten, normal hochladen.
- already_exists:    byte-identisch vorhanden, nichts zu tun.
- metadata_updated:  vorhanden, fehlende Metadaten wurden ergänzt (kein Upload nötig).
- fallback_required: kein sicherer Abgleich möglich, normal hochladen (der Server prüft dann
                     beim Upload selbst noch einmal, siehe FileService._filter_exact_duplicates).

Der Abgleich nutzt exakt dieselbe Regel wie die serverseitige Duplikaterkennung nach dem
Upload (gleicher Mandant, nicht infiziert, checksum_sha256 ODER source_checksum_sha256), damit
Vorab-Ergebnis und spätere Serverentscheidung nie auseinanderlaufen. Ein Hash wird
ausschliesslich gegen den aktuellen Mandanten des Benutzers geprüft; über andere Mandanten
gibt der Endpunkt nichts preis (gleiche Antwort wie für einen unbekannten Hash).

Die Abgabebox hat bewusst KEINEN solchen Endpunkt: dort lädt anonym hoch, wer den Link kennt,
und die Antwort verrät absichtlich nicht einmal, ob eine Datei ein Duplikat war.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.storage import InvalidObjectKey, ObjectNotFound, get_object_store
from app.models.entities import StoredFile
from app.schemas.files import UploadPrecheckRequest, UploadPrecheckResult
from app.services import image_metadata_service as metadata_service
from app.services import photo_event_link_service
from app.services.stored_file_location import namespace_for_stored_file
from app.services.image_metadata_service import ImageMetadata, MergeOutcome

logger = logging.getLogger(__name__)


@dataclass
class EnrichResult:
    file_id: uuid.UUID
    outcome: MergeOutcome


def find_existing(db: Session, tenant_id: int, checksums: list[str], *, lock: bool = False) -> dict[str, list[StoredFile]]:
    """Vorhandene, nicht infizierte Dateien des Mandanten je Hash (Original- oder Quell-Hash).
    lock=True sperrt die Zeilen bis zum Ende der Transaktion (SELECT ... FOR UPDATE), damit
    zwei gleichzeitige Abgleiche dieselben fehlenden Felder nicht doppelt bzw. widersprüchlich
    befüllen - der zweite sieht danach den bereits ergänzten Wert."""
    wanted = sorted({checksum.lower() for checksum in checksums})
    if not wanted:
        return {}
    query = (
        select(StoredFile)
        .where(
            StoredFile.tenant_id == tenant_id,
            StoredFile.scan_status != "infected",
            or_(StoredFile.checksum_sha256.in_(wanted), StoredFile.source_checksum_sha256.in_(wanted)),
        )
        .order_by(StoredFile.id)
    )
    if lock:
        query = query.with_for_update()
    matches: dict[str, list[StoredFile]] = {}
    for stored_file in db.scalars(query):
        for checksum in {stored_file.checksum_sha256, stored_file.source_checksum_sha256}:
            if checksum in wanted:
                matches.setdefault(checksum, []).append(stored_file)
    return matches


def analyze_stored_file(db: Session, stored_file: StoredFile) -> ImageMetadata:
    """Serverseitige Analyse der gespeicherten Datei aus dem Objektspeicher (Namespace wie
    stored_file_location). status "missing_file", wenn sie nicht (mehr) im Speicher liegt."""
    try:
        content = get_object_store().get_bytes(namespace_for_stored_file(db, stored_file), stored_file.storage_path)
    except (ObjectNotFound, InvalidObjectKey):
        return ImageMetadata(status="missing_file")
    return metadata_service.extract_image_metadata(content)


def _is_image(stored_file: StoredFile) -> bool:
    return bool(stored_file.mime_type and stored_file.mime_type.startswith("image/"))


def enrich_existing(
    db: Session,
    stored_files: list[StoredFile],
    checksum: str,
    *,
    incoming: ImageMetadata | None,
    estimated: date | None,
    user_id: int | None,
) -> MergeOutcome:
    """Ergänzt fehlende Metadaten aller Dateien mit diesem Hash (byte-identische Kopien
    derselben Aufnahme - z. B. ältere Duplikate aus der Zeit vor der Duplikaterkennung).

    - Byte-identisches Original vorhanden (checksum_sha256 passt): der Server analysiert die
      eigene Datei (nur einmal, solange metadata_scanned_at leer ist); Client-Angaben werden
      dabei nie übernommen.
    - Nur Quell-Hash passt (HEIC wurde nach JPEG konvertiert, Original existiert nicht mehr):
      validierte Client-Angaben werden mit Herkunft "client" übernommen, Abmessungen und
      Ausrichtung des Originals aber nicht (gelten nicht für das gedrehte JPEG).
    - Das geschätzte Datum (Benutzereingabe) wird nur gesetzt, wo weder echtes noch
      geschätztes Datum existiert."""
    outcome = MergeOutcome()
    incoming = incoming or ImageMetadata()
    for stored_file in stored_files:
        if not _is_image(stored_file):
            continue
        before = (stored_file.exif_taken_at, stored_file.estimated_taken_on)
        file_outcome = MergeOutcome()
        byte_identical = stored_file.checksum_sha256 == checksum
        # Die eigene Datei wird höchstens einmal analysiert (metadata_scanned_at): eine erneute
        # Analyse derselben Bytes liefert nichts Neues. Client-Angaben lösen sie nicht aus - sonst
        # liesse sich mit erfundenen Werten jede grosse Datei unter Zeilensperre wiederholt einlesen.
        needs_analysis = stored_file.metadata_scanned_at is None
        if byte_identical and needs_analysis:
            server_metadata = analyze_stored_file(db, stored_file)
            if server_metadata.status == "missing_file":
                metadata_service.mark_scan_status(stored_file, "missing_file")
            else:
                file_outcome.extend(metadata_service.apply_server_analysis(stored_file, server_metadata, source="server"))
        elif not byte_identical:
            file_outcome.extend(
                metadata_service.merge_missing_metadata(stored_file, incoming, source="client", include_geometry=False)
            )
        file_outcome.extend(metadata_service.apply_estimated_date(stored_file, estimated, user_id=user_id))
        if (stored_file.exif_taken_at, stored_file.estimated_taken_on) != before:
            photo_event_link_service.resync_photo_after_date_change(db, stored_file)
        outcome.extend(file_outcome)
    return outcome


def precheck(
    db: Session, *, tenant_id: int, request: UploadPrecheckRequest, user_id: int | None
) -> list[UploadPrecheckResult]:
    """Siehe Moduldocstring. Committet die ergänzten Metadaten selbst (eine Transaktion für
    den ganzen Batch, Zeilen gesperrt) - der Aufrufer muss nichts mehr tun.

    Schlägt das Ergänzen unerwartet fehl, wird der ganze Batch zurückgerollt und jede
    vorhandene Datei als fallback_required gemeldet: der Client lädt sie dann normal hoch, die
    serverseitige Duplikaterkennung überspringt sie dort und ergänzt die Metadaten erneut. So
    meldet die Antwort nie eine Änderung, die nicht tatsächlich gespeichert wurde."""
    from app.core.error_log import record_system_error  # deferred: vermeidet Import beim Modulstart

    with_metadata = request.context == "gallery"
    estimated = metadata_service.valid_estimated_date(request.estimated_taken_on) if with_metadata else None
    existing = find_existing(db, tenant_id, [entry.sha256 for entry in request.files], lock=True)
    results: list[UploadPrecheckResult] = []
    # Dieselbe Aufnahme mehrfach in einem Batch: nur die erste Kopie wird als Upload gemeldet,
    # weitere als fallback_required (der Server überspringt sie beim Upload als Duplikat).
    first_seen: set[str] = set()
    try:
        for entry in request.files:
            checksum = entry.sha256.lower()
            matches = existing.get(checksum, [])
            if not matches:
                status = "upload_required" if checksum not in first_seen else "fallback_required"
                first_seen.add(checksum)
                results.append(UploadPrecheckResult(client_id=entry.client_id, status=status))
                continue
            outcome = MergeOutcome()
            if with_metadata:
                incoming = metadata_service.metadata_from_client(entry.metadata.model_dump() if entry.metadata else None)
                outcome = enrich_existing(db, matches, checksum, incoming=incoming, estimated=estimated, user_id=user_id)
            results.append(
                UploadPrecheckResult(
                    client_id=entry.client_id,
                    status="metadata_updated" if outcome.applied else "already_exists",
                    file_id=matches[0].public_id,
                    applied=outcome.applied,
                    conflicts=outcome.conflicts,
                )
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Vorab-Abgleich fehlgeschlagen - Fallback auf normalen Upload")
        record_system_error(db, exc=exc, tenant_id=tenant_id)
        return [
            UploadPrecheckResult(
                client_id=entry.client_id,
                status="fallback_required" if entry.sha256.lower() in existing else "upload_required",
            )
            for entry in request.files
        ]
    return results
