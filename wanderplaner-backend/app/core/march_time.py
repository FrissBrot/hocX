"""Marschzeitberechnung (Auftrag Abschnitt 12/13). Formel und Presets verifiziert gegen die
vom Nutzer bereitgestellte Referenzdatei "Marschtabelle_Zeitberechnung.xlsx" (Jubla-
Originalvorlage) - siehe Wiki-Seite "Wanderplaner" fuer die volle Herleitung inkl. Abgleich
gegen deren "Beispiel"-Blatt. `leistungskilometer()`/`gradient_percent()` sind identisch zu
app/core/routing_cost.py (dort fuer die Routing-Kostenfunktion dupliziert statt importiert,
siehe dessen Docstring - dieses Modul hier ist die "kanonische" Fassung fuer die tatsaechliche
Marschzeitanzeige).

Reine Funktionen/Dataclasses, keine DB-Abhaengigkeit - march_time_service.py uebersetzt
ORM-Objekte (HikingTour/-Waypoint/-RouteLeg) in die hier erwarteten einfachen Eingaben und
zurueck in Pydantic-Schemas. Macht build_march_table() ohne Datenbank testbar (Auftrag
Abschnitt 23: "Abschnittszeiten", "Pausen", "Gesamtzeit" brauchen Unit-Tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

STEEP_DESCENT_THRESHOLD_PERCENT = 20.0

# (group_type, luggage_type) -> Lkm/h, aus der Jubla-Referenzvorlage (Wiki "Wanderplaner").
# Freitext-Codes statt DB-Enum (siehe hiking_tour.group_type-Kommentar in entities.py) -
# unbekannte Kombinationen fallen auf DEFAULT_SPEED_FACTOR_KMH zurueck statt einen Fehler zu
# werfen, damit eine Tour ohne (oder mit noch nicht abgebildetem) Gruppentyp trotzdem eine
# Marschzeit bekommt.
SPEED_FACTOR_PRESETS_KMH: dict[tuple[str, str], float] = {
    ("untrainiert", "mit_gepaeck"): 4.0,
    ("untrainiert", "ohne_gepaeck"): 5.0,
    ("trainiert", "mit_gepaeck"): 5.0,
    ("trainiert", "ohne_gepaeck"): 6.0,
}
DEFAULT_SPEED_FACTOR_KMH = 4.0  # konservativste Vorlagen-Stufe als sicherer Fallback


def gradient_percent(length_m: float, height_delta_m: float) -> float:
    if length_m <= 0:
        return 0.0
    return (height_delta_m / length_m) * 100


def leistungskilometer(length_m: float, ascent_m: float, descent_m: float) -> float:
    """1 Lkm = 1 km horizontal, ODER 100 Hm Aufstieg, ODER bei Gefaelle steiler als 20%
    zusaetzlich 150 Hm Abstieg (siehe Wiki "Wanderplaner")."""
    horizontal_km = length_m / 1000
    lkm = horizontal_km + (ascent_m / 100)
    if gradient_percent(length_m, descent_m) > STEEP_DESCENT_THRESHOLD_PERCENT:
        lkm += descent_m / 150
    return lkm


def resolve_speed_factor_kmh(
    *, group_type: str | None, luggage_type: str | None, override_kmh: float | None
) -> float:
    """override_kmh (Tour.speed_factor_kmh, manuell gesetzt) hat immer Vorrang vor den
    Presets - Auftrag Abschnitt 12: "Biete sinnvolle Presets an, aber erlaube manuelle
    Anpassung des Geschwindigkeitsfaktors"."""
    if override_kmh is not None and override_kmh > 0:
        return override_kmh
    if group_type and luggage_type:
        return SPEED_FACTOR_PRESETS_KMH.get((group_type, luggage_type), DEFAULT_SPEED_FACTOR_KMH)
    return DEFAULT_SPEED_FACTOR_KMH


@dataclass
class MarchTimeWaypointInput:
    sequence: int
    label: str | None
    kind: str
    elevation_m: float | None = None
    break_minutes: int = 0
    break_reason: str | None = None
    remarks: str | None = None


@dataclass
class MarchTimeLegInput:
    distance_m: float
    ascent_m: float
    descent_m: float


@dataclass
class MarchTimeEntry:
    sequence: int
    label: str | None
    kind: str
    elevation_m: float | None
    segment_distance_m: float
    cumulative_distance_m: float
    segment_ascent_m: float
    segment_descent_m: float
    segment_lkm: float
    cumulative_lkm: float
    segment_duration_minutes: float
    cumulative_duration_minutes: float
    planned_arrival: time | None
    break_minutes: int
    planned_departure: time | None
    remarks: str | None = None


@dataclass
class MarchTimeSummary:
    total_distance_m: float
    total_ascent_m: float
    total_descent_m: float
    total_lkm: float
    walking_duration_minutes: float
    break_duration_minutes: float
    total_duration_minutes: float


@dataclass
class MarchTimeTable:
    speed_factor_kmh: float
    entries: list[MarchTimeEntry] = field(default_factory=list)
    summary: MarchTimeSummary | None = None


def _add_minutes(base: time, minutes: float) -> time:
    # Auf ganze Minuten runden (hh:mm, Auftrag Abschnitt 13) - ohne round() haetten
    # Uhrzeiten Sekunden-/Mikrosekundenreste aus der Lkm/h-Division.
    combined = datetime.combine(date(2000, 1, 1), base) + timedelta(minutes=round(minutes))
    return combined.time()


def build_march_table(
    *,
    waypoints: list[MarchTimeWaypointInput],
    legs: list[MarchTimeLegInput],
    speed_factor_kmh: float,
    planned_start_time: time | None,
) -> MarchTimeTable:
    """waypoints/legs muessen bereits in Reihenfolge sein, legs[i] verbindet
    waypoints[i] -> waypoints[i+1] (wie hiking_tour_route_leg.sequence == Startwegpunkt)."""
    if len(waypoints) < 1:
        raise ValueError("Marschzeittabelle braucht mindestens einen Wegpunkt")
    if len(legs) != len(waypoints) - 1:
        raise ValueError("Anzahl Routenabschnitte muss Anzahl Wegpunkte minus 1 entsprechen - Route neu berechnen")
    if speed_factor_kmh <= 0:
        raise ValueError("Geschwindigkeitsfaktor muss positiv sein")

    entries: list[MarchTimeEntry] = []
    cumulative_distance = cumulative_lkm = cumulative_minutes = 0.0
    total_break_minutes = 0
    total_ascent = total_descent = 0.0

    for index, waypoint in enumerate(waypoints):
        if index == 0:
            segment_distance = segment_ascent = segment_descent = segment_lkm = segment_duration = 0.0
        else:
            leg = legs[index - 1]
            segment_distance = leg.distance_m
            segment_ascent = leg.ascent_m
            segment_descent = leg.descent_m
            segment_lkm = leistungskilometer(segment_distance, segment_ascent, segment_descent)
            segment_duration = (segment_lkm / speed_factor_kmh) * 60
            total_ascent += segment_ascent
            total_descent += segment_descent

        cumulative_distance += segment_distance
        cumulative_lkm += segment_lkm
        cumulative_minutes += segment_duration

        planned_arrival = _add_minutes(planned_start_time, cumulative_minutes) if planned_start_time else None
        break_minutes = max(0, waypoint.break_minutes)
        total_break_minutes += break_minutes
        cumulative_minutes += break_minutes
        planned_departure = (
            _add_minutes(planned_start_time, cumulative_minutes) if planned_start_time and break_minutes else None
        )

        entries.append(
            MarchTimeEntry(
                sequence=waypoint.sequence,
                label=waypoint.label,
                kind=waypoint.kind,
                elevation_m=waypoint.elevation_m,
                segment_distance_m=segment_distance,
                cumulative_distance_m=cumulative_distance,
                segment_ascent_m=segment_ascent,
                segment_descent_m=segment_descent,
                segment_lkm=segment_lkm,
                cumulative_lkm=cumulative_lkm,
                segment_duration_minutes=segment_duration,
                cumulative_duration_minutes=cumulative_minutes,
                planned_arrival=planned_arrival,
                break_minutes=break_minutes,
                planned_departure=planned_departure,
                remarks=waypoint.break_reason or waypoint.remarks,
            )
        )

    summary = MarchTimeSummary(
        total_distance_m=cumulative_distance,
        total_ascent_m=total_ascent,
        total_descent_m=total_descent,
        total_lkm=cumulative_lkm,
        walking_duration_minutes=cumulative_minutes - total_break_minutes,
        break_duration_minutes=total_break_minutes,
        total_duration_minutes=cumulative_minutes,
    )
    return MarchTimeTable(speed_factor_kmh=speed_factor_kmh, entries=entries, summary=summary)
