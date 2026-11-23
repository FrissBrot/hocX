"""Datumskorrekturen mit Rückgängig und Vorschau (Plan «Upload-Verlauf» 7.4/7.5, Migration 0251).

- ``record``: je tatsächlich geändertem Foto Wert davor/danach in einer Korrektur
  (capture_change_batch). Gestückelte Aufrufe des Browsers hängen an derselben Korrektur, wenn sie
  deren ID mitsenden - nur eigene, nicht rückgängig gemachte, höchstens 2 h alte Korrekturen, sonst 404.
- ``undo``: setzt je Foto den Wert davor zurück, aber nur, wenn der aktuelle Wert noch dem neuen
  entspricht («inzwischen geändert» sonst). Ein vorheriger Wert NULL entfernt die Korrektur; der
  Job capture_date_file_sync schreibt dann das Original in die Datei zurück. Danach Termin-Zuordnung
  nur für die betroffenen Fotos neu bewerten und datumsabhängige Auto-Alben nachziehen.
- ``impacts``: Auswirkungen einer Vorschau (Tageswechsel, Terminwechsel automatisch verknüpfter
  Fotos), Termine einmal geladen.

Die Korrektur gilt, solange es ihre Fotos gibt (E-9): Items verschwinden mit der Datei, eine leere
Korrektur entfernt der Lösch-Trigger.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.entities import Event, GalleryImage, StoredFile
from app.models.upload_history_entities import CaptureChangeBatch, CaptureChangeItem
from app.services import image_metadata_service, photo_event_link_service
from app.services.capture_date import auto_link_date

BATCH_REUSE_WINDOW = timedelta(hours=2)
UNDO_CHUNK = 500


def _now() -> datetime:
    return datetime.now(UTC)


def open_batch(
    db: Session, user, *, batch_id: uuid.UUID | None, mode: str, params: dict, upload_job_id: uuid.UUID | None
) -> CaptureChangeBatch:
    """Neue Korrektur oder - bei gestückelten Aufrufen - die eigene des ersten Stücks (sonst 404)."""
    if batch_id is not None:
        batch = db.scalar(
            select(CaptureChangeBatch)
            .where(
                CaptureChangeBatch.id == batch_id,
                CaptureChangeBatch.tenant_id == user.current_tenant_id,
                CaptureChangeBatch.created_by == user.user_id,
                CaptureChangeBatch.undone_at.is_(None),
                CaptureChangeBatch.mode == mode,
                CaptureChangeBatch.created_at >= _now() - BATCH_REUSE_WINDOW,
            )
            .with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="Korrektur nicht gefunden")
        return batch
    batch = CaptureChangeBatch(
        tenant_id=user.current_tenant_id, created_by=user.user_id, mode=mode, params=params, upload_job_id=upload_job_id
    )
    db.add(batch)
    db.flush()
    return batch


def record(db: Session, batch: CaptureChangeBatch, changes) -> None:
    if not changes:
        return
    rows = [
        {
            "batch_id": batch.id, "tenant_id": batch.tenant_id, "stored_file_id": change.stored_file.id,
            "prev_corrected_at": change.prev_corrected_at, "prev_has_time": change.prev_has_time,
            "new_corrected_at": change.new_corrected_at, "new_has_time": change.new_has_time,
        }
        for change in changes
        if change.stored_file.tenant_id == batch.tenant_id
    ]
    inserted = db.execute(pg_insert(CaptureChangeItem).values(rows).on_conflict_do_nothing().returning(CaptureChangeItem.id)).scalars().all()
    db.execute(
        update(CaptureChangeBatch)
        .where(CaptureChangeBatch.id == batch.id, CaptureChangeBatch.tenant_id == batch.tenant_id)
        .values(updated_count=CaptureChangeBatch.updated_count + len(inserted))
        .execution_options(synchronize_session=False)
    )


@dataclass
class UndoOutcome:
    restored_ids: list[uuid.UUID] = field(default_factory=list)
    conflict_ids: list[uuid.UUID] = field(default_factory=list)
    not_found_ids: list[uuid.UUID] = field(default_factory=list)
    touched_album_ids: set[uuid.UUID] = field(default_factory=set)


def _same(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.astimezone(UTC).replace(tzinfo=None) == b.astimezone(UTC).replace(tzinfo=None)


def undo(db: Session, batch: CaptureChangeBatch, *, user_id: int | None, writable) -> UndoOutcome:
    """Rückgängig (Committet nicht). ``writable(stored_file) -> bool``: Schreibprüfung des Aufrufers
    je Foto (Reichweite, Leserecht) - nicht beschreibbare zählen wie gelöschte als not_found."""
    from app.services import photo_album_service

    outcome = UndoOutcome()
    items = list(
        db.scalars(
            select(CaptureChangeItem)
            .where(CaptureChangeItem.batch_id == batch.id, CaptureChangeItem.tenant_id == batch.tenant_id)
            .order_by(CaptureChangeItem.id)
        )
    )
    changed: list[StoredFile] = []
    relink: list[StoredFile] = []
    for start in range(0, len(items), UNDO_CHUNK):
        chunk = items[start : start + UNDO_CHUNK]
        files = {
            stored.id: stored
            for stored in db.scalars(
                select(StoredFile)
                .where(StoredFile.tenant_id == batch.tenant_id, StoredFile.id.in_([item.stored_file_id for item in chunk]))
                .with_for_update()
            )
        }
        for item in chunk:
            stored = files.get(item.stored_file_id)
            if stored is None or not writable(stored):
                if stored is not None:
                    outcome.not_found_ids.append(stored.public_id)
                continue
            current_has_time = bool(stored.capture_corrected_has_time) if stored.capture_corrected_at is not None else False
            if not _same(stored.capture_corrected_at, item.new_corrected_at) or current_has_time != item.new_has_time:
                outcome.conflict_ids.append(stored.public_id)
                continue
            old_day = auto_link_date(stored)
            prev = item.prev_corrected_at
            try:
                image_metadata_service.set_capture_correction(
                    stored, prev.astimezone(UTC).replace(tzinfo=None) if prev is not None else None,
                    has_time=item.prev_has_time, user_id=user_id,
                )
            except ValueError:
                outcome.conflict_ids.append(stored.public_id)
                continue
            outcome.restored_ids.append(stored.public_id)
            changed.append(stored)
            if auto_link_date(stored) != old_day:
                relink.append(stored)
    photo_event_link_service.resync_photos_after_date_change(db, batch.tenant_id, relink)
    db.flush()
    outcome.touched_album_ids = photo_album_service.follow_capture_date_change(db, tenant_id=batch.tenant_id, stored_files=changed)
    batch.undone_at = _now()
    batch.undone_by = user_id
    return outcome


# --- Vorschau ---------------------------------------------------------------------------------


def _view_after(change) -> SimpleNamespace:
    stored = change.stored_file
    return SimpleNamespace(
        capture_corrected_at=change.new_corrected_at, exif_taken_at=stored.exif_taken_at,
        estimated_taken_on=stored.estimated_taken_on, created_at=stored.created_at,
    )


def impacts(db: Session, tenant_id: int, changes) -> dict:
    """Tageswechsel und Terminwechsel (nur automatisch verknüpfte bzw. unverknüpfte Fotos; manuelle
    bleiben unberührt) für die Vorschau. Termine nur des eigenen Mandanten."""
    day_changes = 0
    new_days: dict[int, date | None] = {}
    for change in changes:
        new_day = auto_link_date(_view_after(change))
        new_days[change.stored_file.id] = new_day
        if new_day != change.old_link_day:
            day_changes += 1
    candidates = {file_id for file_id, day in new_days.items()}
    links = {
        row.stored_file_id: row
        for row in db.execute(
            select(GalleryImage.stored_file_id, GalleryImage.event_id, GalleryImage.event_auto_linked).where(
                GalleryImage.tenant_id == tenant_id, GalleryImage.stored_file_id.in_(candidates)
            )
        )
    } if candidates else {}
    events = photo_event_link_service._events_for_days(db, tenant_id, [day for day in new_days.values() if day is not None])
    transitions: dict[tuple[int | None, int | None], int] = {}
    for file_id, new_day in new_days.items():
        link = links.get(file_id)
        if link is None or (link.event_id is not None and not link.event_auto_linked):
            continue
        match = photo_event_link_service.match_in_memory(events, new_day)
        target = match.id if match is not None else None
        if target != link.event_id:
            transitions[(link.event_id, target)] = transitions.get((link.event_id, target), 0) + 1
    event_ids = {event_id for pair in transitions for event_id in pair if event_id is not None}
    titles = {
        row.id: (row.title, row.event_date)
        for row in db.execute(select(Event.id, Event.title, Event.event_date).where(Event.tenant_id == tenant_id, Event.id.in_(event_ids)))
    } if event_ids else {}

    def describe(event_id):
        if event_id is None or event_id not in titles:
            return None
        title, on_date = titles[event_id]
        return {"title": title, "date": on_date.isoformat()}

    return {
        "day_changes": day_changes,
        "event_changes": sum(transitions.values()),
        "event_transitions": [
            {"from_event": describe(old), "to_event": describe(new), "count": count}
            for (old, new), count in sorted(transitions.items(), key=lambda item: -item[1])[:10]
        ],
    }


def samples(service, changes, limit: int = 20) -> list[dict]:
    result = []
    for change in changes[:limit]:
        stored = change.stored_file
        before = change.prev_corrected_at or stored.exif_taken_at
        result.append(
            {
                "id": stored.public_id,
                "name": stored.original_name,
                "thumbnail_url": service.build_thumbnail_url(stored.public_id),
                "before": before,
                "before_has_time": change.prev_has_time if change.prev_corrected_at is not None else stored.exif_taken_at is not None,
                "before_source": "corrected" if change.prev_corrected_at is not None else ("exif" if stored.exif_taken_at else "estimated"),
                "after": change.new_corrected_at,
                "after_has_time": change.new_has_time,
            }
        )
    return result


def list_for_job(db: Session, tenant_id: int, upload_job_id: uuid.UUID) -> list[CaptureChangeBatch]:
    return list(
        db.scalars(
            select(CaptureChangeBatch)
            .where(CaptureChangeBatch.tenant_id == tenant_id, CaptureChangeBatch.upload_job_id == upload_job_id)
            .order_by(CaptureChangeBatch.created_at.desc())
            .limit(100)
        )
    )


def remaining_items(db: Session, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not batch_ids:
        return {}
    return dict(
        db.execute(
            select(CaptureChangeItem.batch_id, func.count()).where(CaptureChangeItem.batch_id.in_(batch_ids)).group_by(CaptureChangeItem.batch_id)
        ).all()
    )
