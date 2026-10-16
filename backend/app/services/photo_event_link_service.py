"""Bidirectional date-based linking between gallery photos and Termine (Event), so a photo
taken on (or during) a Termin shows up under it in the Fotos gallery without anyone having
to pick that Termin by hand.

Two directions, both funnelling through GalleryImage.event_id/event_auto_linked:
 - photo -> Termin: FileService.save_gallery_uploads calls find_matching_event() per
   upload when the uploader didn't target a Termin themselves.
 - Termin -> photo: events.py's create_event/patch_event call sync_photos_for_event()
   after a Termin is created or its dates change, to link/unlink already-uploaded photos.

event_auto_linked tells the two directions apart so sync_photos_for_event never overrides
an uploader's explicit choice."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.entities import Event, GalleryImage, StoredFile
from app.services.capture_date import auto_link_date, auto_link_date_sql

# Datum fuer die automatische Zuordnung, zentral definiert in capture_date.py: echtes
# Aufnahmedatum, sonst Uploaddatum - aber NULL (keine automatische Zuordnung), sobald nur ein
# geschaetztes Datum vorliegt. Eine Schaetzung ist zu unsicher, um ein Foto ohne Zutun einem
# Termin zuzuordnen, und das Uploaddatum ist in diesem Fall erwiesenermassen falsch.
_capture_date_expr = auto_link_date_sql(StoredFile)


def capture_date(stored_file: StoredFile) -> date | None:
    """Python-side equivalent of _capture_date_expr, for the single-file upload path where
    the StoredFile row already exists in memory and a round-trip through SQL would be
    wasteful. None means "do not auto-link" (only an estimated date is known)."""
    return auto_link_date(stored_file)


def find_matching_event(db: Session, tenant_id: int, on_date: date | None) -> Event | None:
    """The Termin (if any) covering `on_date`, for auto-linking a just-uploaded photo.
    Multi-day Termine match every day in their [event_date, event_end_date] range.
    Cancelled Termine never match - a cancelled Termin's days almost certainly didn't
    happen, so a photo taken that day is unrelated to it. Ties (two Termine covering the
    same day) favour the one that started most recently, then the lower id, purely for a
    deterministic result - genuinely overlapping Termine are rare enough not to warrant
    linking a photo to more than one."""
    if on_date is None:
        return None
    return db.scalars(
        select(Event)
        .where(
            Event.tenant_id == tenant_id,
            Event.is_cancelled.is_(False),
            Event.event_date <= on_date,
            func.coalesce(Event.event_end_date, Event.event_date) >= on_date,
        )
        .order_by(Event.event_date.desc(), Event.id.asc())
        .limit(1)
    ).first()


def sync_photos_for_event(db: Session, event: Event) -> None:
    """Called after a Termin is created or updated: links previously-unlinked gallery
    photos whose capture date now falls in this Termin's range, and unlinks photos that an
    earlier date-match had linked to it but no longer covers (e.g. the Termin's end date
    was shortened). Never touches a manually-picked link (event_auto_linked False) - the
    uploader's own choice always wins over date matching. Commits its own changes, like
    submission_service.sync_todos_for_event which the same route handlers call alongside
    this."""
    end_date = event.event_end_date or event.event_date

    to_link = db.execute(
        select(GalleryImage)
        .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
        .where(
            GalleryImage.tenant_id == event.tenant_id,
            GalleryImage.event_id.is_(None),
            _capture_date_expr >= event.event_date,
            _capture_date_expr <= end_date,
        )
    ).scalars().all()
    for gallery_image in to_link:
        gallery_image.event_id = event.id
        gallery_image.event_auto_linked = True

    to_unlink = db.execute(
        select(GalleryImage)
        .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
        .where(
            GalleryImage.event_id == event.id,
            GalleryImage.event_auto_linked.is_(True),
            or_(_capture_date_expr.is_(None), _capture_date_expr < event.event_date, _capture_date_expr > end_date),
        )
    ).scalars().all()
    for gallery_image in to_unlink:
        gallery_image.event_id = None
        gallery_image.event_auto_linked = False

    if to_link or to_unlink:
        db.commit()


def resync_photo_after_date_change(db: Session, stored_file: StoredFile) -> None:
    """Nach einer Aenderung von exif_taken_at/estimated_taken_on (Hash-Abgleich, Backfill,
    Bearbeitung): automatische Termin-Verknuepfungen dieses Fotos neu bewerten. Eine manuell
    gewaehlte Verknuepfung (event_auto_linked False mit event_id) bleibt immer unberuehrt.
    Committet nicht - der Aufrufer schliesst seine Transaktion selbst ab."""
    on_date = auto_link_date(stored_file)
    for gallery_image in db.scalars(select(GalleryImage).where(GalleryImage.stored_file_id == stored_file.id)):
        if gallery_image.event_id is not None and not gallery_image.event_auto_linked:
            continue
        match = find_matching_event(db, gallery_image.tenant_id, on_date)
        if match is None:
            gallery_image.event_id = None
            gallery_image.event_auto_linked = False
        elif gallery_image.event_id != match.id:
            gallery_image.event_id = match.id
            gallery_image.event_auto_linked = True
