"""Entscheidungspunkte (Auftrag Abschnitt 9): "sinnvoller Umkehrpunkt", "letzter guter
Umkehrpunkt", Zugang zu Alternativroute/Notausstieg. Reine Funktionen - Platzierung
(WO ein Entscheidungspunkt sinnvoll ist) und Kennzahlen (WAS dort angezeigt wird) sind bewusst
getrennt: Kennzahlen (Zeit vom Start/bis Ziel/zurueck, naechster Ausstieg) sind fuer jeden
Entscheidungspunkt gleich berechenbar, unabhaengig davon, warum er dort liegt.

Die Software liefert Entscheidungshilfe, keine Sicherheitsgarantie (Auftrag: "Markiere nicht
leichtfertig einen mathematischen Punkt als absoluten 'Point of no Return'") - deshalb im
Reason-Text immer vorsichtig formuliert ("etwa", "ungefähr"), nie als Tatsachenbehauptung."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.march_time import leistungskilometer
from app.core.waypoint_detection import ClimbSegment, RoutePoint

# Wenn kein Aufstiegsabschnitt einen natuerlichen Entscheidungspunkt liefert, wird ersatzweise
# hier (Anteil der Gesamtmarschzeit) ein allgemeiner "ungefaehre Tourhaelfte"-Punkt erzeugt.
DEFAULT_FALLBACK_TIME_FRACTION = 0.5


@dataclass(frozen=True)
class DecisionCandidate:
    distance_m: float
    lat: float
    lon: float
    label: str
    reason: str


def _interpolate_position(points: list[RoutePoint], distance_m: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if distance_m <= points[0].distance_m:
        return points[0].lat, points[0].lon
    if distance_m >= points[-1].distance_m:
        return points[-1].lat, points[-1].lon
    for previous, current in zip(points, points[1:]):
        if previous.distance_m <= distance_m <= current.distance_m:
            span = current.distance_m - previous.distance_m
            if span <= 0:
                return previous.lat, previous.lon
            ratio = (distance_m - previous.distance_m) / span
            return previous.lat + ratio * (current.lat - previous.lat), previous.lon + ratio * (current.lon - previous.lon)
    return points[-1].lat, points[-1].lon


@dataclass(frozen=True)
class DecisionRow:
    """Minimaler Ausschnitt der Marschzeittabelle, den decision_points braucht."""

    sequence: int
    cumulative_distance_m: float
    cumulative_ascent_m: float
    cumulative_descent_m: float
    cumulative_duration_minutes: float


@dataclass(frozen=True)
class ExitCandidate:
    waypoint_label: str
    distance_from_route_m: float
    time_to_exit_minutes: float


@dataclass(frozen=True)
class DecisionMetrics:
    time_from_start_minutes: float
    time_to_end_minutes: float
    time_back_minutes: float
    nearest_exit_label: str | None
    time_to_exit_minutes: float | None
    distance_to_exit_m: float | None


def find_decision_candidates(
    *,
    climb_segments: list[ClimbSegment],
    elevation_points: list[RoutePoint],
    fallback_time_fraction: float = DEFAULT_FALLBACK_TIME_FRACTION,
) -> list[DecisionCandidate]:
    """Ein Entscheidungspunkt vor jedem laengeren Aufstieg (Auftrag: "letzter guter
    Umkehrpunkt" ist meist genau dort, wo man sich auf einen laengeren Aufstieg festlegt).
    Ohne einen einzigen erkannten Aufstieg (z.B. eine reine Grat-/Ebene-Tour) ersatzweise ein
    allgemeiner Punkt bei ungefaehr der halben Strecke."""
    if not climb_segments:
        if not elevation_points:
            return []
        total_distance_m = elevation_points[-1].distance_m
        if total_distance_m <= 0:
            return []
        target_distance = total_distance_m * fallback_time_fraction
        lat, lon = _interpolate_position(elevation_points, target_distance)
        return [
            DecisionCandidate(
                distance_m=target_distance,
                lat=lat,
                lon=lon,
                label="Entscheidungspunkt",
                reason="Etwa auf halber Strecke - ab hier dauert der Rückweg ungefähr gleich lange wie der Weg zum Ziel.",
            )
        ]

    candidates = []
    for segment in sorted(climb_segments, key=lambda s: s.start_distance_m):
        candidates.append(
            DecisionCandidate(
                distance_m=segment.start_distance_m,
                lat=segment.start_lat,
                lon=segment.start_lon,
                label="Entscheidungspunkt",
                reason=(
                    f"Vor einem längeren Aufstieg (ca. {round(segment.ascent_m)} Hm) - "
                    "letzter guter Punkt, um die Weiterfahrt abzuwägen."
                ),
            )
        )
    return candidates


def compute_decision_metrics(
    *,
    row: DecisionRow,
    total_duration_minutes: float,
    speed_factor_kmh: float,
    nearest_exit: ExitCandidate | None,
) -> DecisionMetrics:
    """Zeit zurueck wird NICHT einfach gleich Zeit vom Start gesetzt - der Rueckweg kehrt
    Auf-/Abstieg um (bergab wird zu bergauf und umgekehrt), siehe leistungskilometer()."""
    time_from_start = row.cumulative_duration_minutes
    time_to_end = max(0.0, total_duration_minutes - time_from_start)
    reverse_lkm = leistungskilometer(row.cumulative_distance_m, row.cumulative_descent_m, row.cumulative_ascent_m)
    time_back = (reverse_lkm / speed_factor_kmh) * 60 if speed_factor_kmh > 0 else time_from_start

    return DecisionMetrics(
        time_from_start_minutes=time_from_start,
        time_to_end_minutes=time_to_end,
        time_back_minutes=time_back,
        nearest_exit_label=nearest_exit.waypoint_label if nearest_exit else None,
        time_to_exit_minutes=nearest_exit.time_to_exit_minutes if nearest_exit else None,
        distance_to_exit_m=nearest_exit.distance_from_route_m if nearest_exit else None,
    )
