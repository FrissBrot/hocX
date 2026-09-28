"""Automatische Pausenvorschlaege (Auftrag Abschnitt 8). Arbeitet auf der bereits berechneten
Marschzeittabelle (Phase 3, app/core/march_time.py) plus den erkannten Aufstiegsabschnitten
(Phase 4, app/core/waypoint_detection.py) - reine Funktion, keine DB-Abhaengigkeit.

Der Algorithmus setzt NICHT stumpf alle X Minuten eine Pause (das verbietet der Auftrag
ausdruecklich), sondern bevorzugt das Ende eines langen Aufstiegs als natuerlichen Rastplatz
und weicht nur bei Bedarf (zu lange ohne Pause unterwegs) auf den naechstgelegenen flachen
Abschnitt aus. Jeder Vorschlag bekommt einen nachvollziehbaren Grund im geforderten Format
("Nach 1h42 Marschzeit und 610 hm Aufstieg; geeigneter flacher Abschnitt.")."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.waypoint_detection import ClimbSegment, RoutePoint

# Ab dieser Marschzeit ohne Pause wird spaetestens eine gesucht (Auftrag: "Zeit seit letzter
# Pause", "bisherige Belastung").
DEFAULT_MAX_MINUTES_WITHOUT_BREAK = 105.0
# Zwei Pausen naeher als das werden nicht beide vorgeschlagen (z.B. zwei kurz aufeinander
# folgende Aufstiegsenden).
DEFAULT_MIN_MINUTES_BETWEEN_BREAKS = 45.0
# In den letzten Minuten vor dem Tourende wird keine Pause mehr vorgeschlagen - niemand
# braucht eine geplante Rast unmittelbar vor dem Ziel.
DEFAULT_SKIP_LAST_MINUTES = 15.0
# "flacher Abschnitt" (Auftrag Abschnitt 8): Steigung/Gefaelle unter dieser Schwelle (ueber ein
# 100m-Fenster) gilt als fuer eine Pause geeignet.
DEFAULT_FLAT_GRADIENT_PERCENT = 8.0
DEFAULT_FLAT_GRADIENT_WINDOW_M = 100.0
# Wie weit um den Faelligkeitspunkt nach einem flachen Abschnitt gesucht wird, bevor
# ersatzweise der Faelligkeitspunkt selbst genommen wird (Auftrag: "Vermeide Pausen mitten in
# steilen ... Abschnitten" - lieber etwas frueher/spaeter als mitten im Steilstueck).
DEFAULT_FLAT_SEARCH_WINDOW_M = 800.0
# Ein erkanntes Aufstiegsende zaehlt als "in der Naehe" der Faelligkeit, wenn es hoechstens so
# weit (in beide Richtungen) davon entfernt liegt.
DEFAULT_CLIMB_END_SEARCH_WINDOW_M = 1500.0


@dataclass(frozen=True)
class MarchTableRow:
    """Minimaler Ausschnitt aus MarchTimeEntry, den die Pausenplanung braucht - entkoppelt
    dieses Modul bewusst vom vollen march_time.MarchTimeEntry-Typ."""

    sequence: int
    cumulative_distance_m: float
    cumulative_ascent_m: float
    cumulative_duration_minutes: float


@dataclass(frozen=True)
class BreakSuggestion:
    after_sequence: int
    """Die Pause wird NACH dem Wegpunkt mit dieser sequence eingefuegt (als neuer Wegpunkt)."""
    distance_m: float
    minutes: int
    reason: str


def _format_hhmm(total_minutes: float) -> str:
    total = round(total_minutes)
    return f"{total // 60}h{total % 60:02d}"


def _local_gradient_percent(points: list[RoutePoint], distance_m: float, *, window_m: float) -> float | None:
    """Lokale Steigung/Gefaelle (Betrag, %) in einem window_m-Fenster um distance_m. None, wenn
    dafuer zu wenige Punkte mit Hoehe vorhanden sind."""
    with_elevation = [p for p in points if p.elevation_m is not None]
    before = [p for p in with_elevation if p.distance_m <= distance_m]
    after = [p for p in with_elevation if p.distance_m >= distance_m]
    if not before or not after:
        return None
    start = max((p for p in before if p.distance_m >= distance_m - window_m / 2), key=lambda p: -p.distance_m, default=before[-1])
    end = min((p for p in after if p.distance_m <= distance_m + window_m / 2), key=lambda p: p.distance_m, default=after[0])
    if end.distance_m <= start.distance_m:
        return None
    height_delta = abs(end.elevation_m - start.elevation_m)  # type: ignore[operator]
    return (height_delta / (end.distance_m - start.distance_m)) * 100


def _find_flat_distance_near(
    points: list[RoutePoint], target_distance_m: float, *, search_window_m: float, flat_gradient_percent: float, gradient_window_m: float
) -> float | None:
    with_elevation = sorted((p for p in points if p.elevation_m is not None), key=lambda p: p.distance_m)
    if not with_elevation:
        return None
    candidates = [p for p in with_elevation if abs(p.distance_m - target_distance_m) <= search_window_m] or with_elevation
    flat_candidates = [
        p for p in candidates if (_local_gradient_percent(points, p.distance_m, window_m=gradient_window_m) or 0.0) <= flat_gradient_percent
    ]
    pool = flat_candidates or candidates
    return min(pool, key=lambda p: abs(p.distance_m - target_distance_m)).distance_m


def suggest_breaks(
    *,
    rows: list[MarchTableRow],
    climb_segments: list[ClimbSegment],
    elevation_points: list[RoutePoint],
    total_duration_minutes: float,
    max_minutes_without_break: float = DEFAULT_MAX_MINUTES_WITHOUT_BREAK,
    min_minutes_between_breaks: float = DEFAULT_MIN_MINUTES_BETWEEN_BREAKS,
    skip_last_minutes: float = DEFAULT_SKIP_LAST_MINUTES,
    default_break_minutes: int = 10,
) -> list[BreakSuggestion]:
    """Ein Durchlauf ueber die Marschzeit: sobald `max_minutes_without_break` seit der letzten
    Pause (oder dem Start) erreicht ist, wird bevorzugt am naechsten Aufstiegsende gerastet;
    ohne ein nahes Aufstiegsende wird der naechstgelegene flache Abschnitt gesucht."""
    if not rows or total_duration_minutes <= 0:
        return []

    sorted_rows = sorted(rows, key=lambda r: r.cumulative_duration_minutes)
    sorted_climb_ends = sorted(seg.end_distance_m for seg in climb_segments)

    suggestions: list[BreakSuggestion] = []
    last_break_minutes = 0.0
    last_break_ascent_m = 0.0
    due_minutes = max_minutes_without_break

    while due_minutes < total_duration_minutes - skip_last_minutes:
        due_row = min(sorted_rows, key=lambda r: abs(r.cumulative_duration_minutes - due_minutes))

        nearest_climb_end = min(
            (d for d in sorted_climb_ends if abs(d - due_row.cumulative_distance_m) <= DEFAULT_CLIMB_END_SEARCH_WINDOW_M),
            key=lambda d: abs(d - due_row.cumulative_distance_m),
            default=None,
        )
        if nearest_climb_end is not None:
            target_row = min(sorted_rows, key=lambda r: abs(r.cumulative_distance_m - nearest_climb_end))
            trigger_description = "Ende eines längeren Aufstiegs"
        else:
            flat_distance = _find_flat_distance_near(
                elevation_points,
                due_row.cumulative_distance_m,
                search_window_m=DEFAULT_FLAT_SEARCH_WINDOW_M,
                flat_gradient_percent=DEFAULT_FLAT_GRADIENT_PERCENT,
                gradient_window_m=DEFAULT_FLAT_GRADIENT_WINDOW_M,
            )
            if flat_distance is not None:
                target_row = min(sorted_rows, key=lambda r: abs(r.cumulative_distance_m - flat_distance))
                trigger_description = "geeigneter flacher Abschnitt"
            else:
                target_row = due_row
                trigger_description = "Fälligkeit erreicht"

        if (
            target_row.cumulative_duration_minutes - last_break_minutes < min_minutes_between_breaks
            or target_row.cumulative_duration_minutes >= total_duration_minutes - skip_last_minutes
            or (suggestions and target_row.sequence == suggestions[-1].after_sequence)
        ):
            due_minutes += max_minutes_without_break
            continue

        elapsed_minutes = target_row.cumulative_duration_minutes - last_break_minutes
        ascent_since_break = target_row.cumulative_ascent_m - last_break_ascent_m
        reason = f"Nach {_format_hhmm(elapsed_minutes)} Marschzeit und {round(ascent_since_break)} hm Aufstieg; {trigger_description}."

        suggestions.append(
            BreakSuggestion(
                after_sequence=target_row.sequence,
                distance_m=target_row.cumulative_distance_m,
                minutes=default_break_minutes,
                reason=reason,
            )
        )
        last_break_minutes = target_row.cumulative_duration_minutes
        last_break_ascent_m = target_row.cumulative_ascent_m
        due_minutes = last_break_minutes + max_minutes_without_break

    return suggestions
