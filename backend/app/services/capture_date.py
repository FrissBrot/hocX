"""Zentrale Datumspriorität für Bilder - einzige Stelle, die festlegt, welches Datum ein Bild hat.

Verbindliche Reihenfolge (Galerie-Sortierung, -Gruppierung, -Überschriften, Bilddetails,
chronologische Ansichten, Datumsfilter, Termin-Zuordnung, Freigabe-Seite, Exporte):

0. korrigiertes Aufnahmedatum    StoredFile.capture_corrected_at -> date_source "corrected"
1. tatsächliches Aufnahmedatum   StoredFile.exif_taken_at        -> date_source "exif"
2. geschätztes Aufnahmedatum     StoredFile.estimated_taken_on   -> date_source "estimated"
3. Uploaddatum                   StoredFile.created_at           -> date_source "upload"

Die Korrektur (Migration 0200) setzt ein Benutzer mit photos.manage bewusst und nach einer
Bestätigung, wenn das EXIF-Datum falsch ist (z. B. falsch gestellte Kamera). Das EXIF-Datum
bleibt dabei gespeichert und wird als «ursprünglich» angezeigt; die Datei selbst wird nie
umgeschrieben. Wird die Korrektur entfernt, gilt wieder EXIF bzw. die Schätzung.

Das geschätzte Datum bleibt gespeichert, auch wenn später ein echtes Datum hinzukommt - es
verliert dann nur den Vorrang.

Automatische Termin-Zuordnung (photo_event_link_service) ist bewusst vorsichtiger: ein nur
geschätztes Datum ist zu unsicher, um ein Foto ohne Zutun einem Termin zuzuordnen. Liegt eine
Schätzung vor, wird deshalb weder nach ihr noch nach dem (dann erwiesenermassen falschen)
Uploaddatum automatisch verknüpft - siehe auto_link_date/auto_link_date_sql. Ein korrigiertes
Datum ist dagegen ausdrücklich bestätigt und zählt wie ein echtes Aufnahmedatum.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import Date, case, cast, func, literal, null

DateSource = Literal["corrected", "exif", "estimated", "upload"]


def _corrected(stored_file: Any) -> datetime | None:
    # getattr: leichte Traeger (_CaptureView, Testdoubles) muessen das Feld nicht kennen.
    return getattr(stored_file, "capture_corrected_at", None)


def effective_capture(stored_file: Any) -> tuple[date, DateSource]:
    corrected = _corrected(stored_file)
    if corrected is not None:
        return corrected.date(), "corrected"
    if stored_file.exif_taken_at is not None:
        return stored_file.exif_taken_at.date(), "exif"
    if stored_file.estimated_taken_on is not None:
        return stored_file.estimated_taken_on, "estimated"
    return stored_file.created_at.date(), "upload"


def effective_capture_date(stored_file: Any) -> date:
    return effective_capture(stored_file)[0]


def effective_capture_moment(stored_file: Any) -> datetime | None:
    """Aufnahmezeitpunkt (floating, wie exif_taken_at) - korrigiert vor EXIF; None ohne beides."""
    return _corrected(stored_file) or stored_file.exif_taken_at


def effective_capture_date_sql(model: Any):
    """SQL-Gegenstück zu effective_capture_date für eine StoredFile-Entität oder einen Alias."""
    return func.coalesce(
        cast(model.capture_corrected_at, Date),
        cast(model.exif_taken_at, Date),
        model.estimated_taken_on,
        cast(model.created_at, Date),
    )


def date_source_sql(model: Any):
    return case(
        (model.capture_corrected_at.is_not(None), literal("corrected")),
        (model.exif_taken_at.is_not(None), literal("exif")),
        (model.estimated_taken_on.is_not(None), literal("estimated")),
        else_=literal("upload"),
    )


def auto_link_date(stored_file: Any) -> date | None:
    """Datum für die automatische Termin-Zuordnung oder None (= nicht automatisch zuordnen)."""
    corrected = _corrected(stored_file)
    if corrected is not None:
        return corrected.date()
    if stored_file.exif_taken_at is not None:
        return stored_file.exif_taken_at.date()
    if stored_file.estimated_taken_on is not None:
        return None
    return stored_file.created_at.date()


def auto_link_date_sql(model: Any):
    return case(
        (model.capture_corrected_at.is_not(None), cast(model.capture_corrected_at, Date)),
        (model.exif_taken_at.is_not(None), cast(model.exif_taken_at, Date)),
        (model.estimated_taken_on.is_not(None), cast(null(), Date)),
        else_=cast(model.created_at, Date),
    )
