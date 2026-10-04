"""Gefahreneinschätzung einer Route: kombiniert die amtliche Wanderweg-Kategorie (swisstopo/
SchweizMobil, siehe routing_cost.py::WANDERWEG_STATUSES) mit einer Geländeanalyse aus den
Höhendaten. Reine Funktionen, keine DB-/Netzwerk-Abhängigkeit (siehe terrain_danger_service.py
für den Höhendaten-Abruf) - Stil wie break_planning.py/waypoint_detection.py.

Regel (Auftrag): "wanderweg"/"bergwanderweg" sind normale Wanderwege; sehr steile oder
ausgesetzte Stellen darauf werden "steep_exposed" (orange auf der Karte). Ein Abschnitt mit
amtlichem Status "alpinwanderweg" ist immer "alpine" (blau), unabhängig vom Geländewert - der
amtliche Status hat Vorrang vor der Geländeanalyse, siehe merge_with_official_status().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.waypoint_detection import RoutePoint

DangerLevel = Literal["normal", "steep_exposed", "alpine"]

# Ab dieser Steigung/Gefälle entlang des Weges (über ein GRADIENT_WINDOW_M-Fenster) gilt eine
# Stelle als "sehr steil". Bewusst ein eigener, höherer Schwellwert als
# routing_cost.STEEP_GRADIENT_THRESHOLD_PERCENT (25%) - jener markiert für die Routenpräferenz
# bereits moderates Gelände, hier geht es um eine tatsächliche Gefahrenmarkierung auf der Karte.
STEEP_GRADIENT_DANGER_PERCENT = 40.0
GRADIENT_WINDOW_M = 40.0

# Ab diesem Quergefälle (Höhenunterschied über CROSS_SECTION_OFFSET_M neben dem Weg) gilt eine
# Stelle als "ausgesetzt" (z. B. Gratweg mit Abbruch auf einer Seite).
EXPOSED_CROSS_SLOPE_PERCENT = 70.0
CROSS_SECTION_OFFSET_M = 15.0


@dataclass(frozen=True)
class DangerSegment:
    from_m: float
    to_m: float
    danger: DangerLevel

    def as_dict(self) -> dict:
        return {"from_m": self.from_m, "to_m": self.to_m, "danger": self.danger}


def _elevation_at(profile: list[dict], distance_m: float) -> float | None:
    """Lineare Interpolation wie elevation_service.elevation_at_distance - hier dupliziert statt
    importiert, damit app/core frei von einer Abhängigkeit auf die swisstopo-Dienstschicht
    (app/services) bleibt (gleiche Konvention wie gradient_percent()/leistungskilometer(),
    bewusst dupliziert zwischen routing_cost.py und march_time.py, siehe dort)."""
    if not profile:
        return None
    if distance_m <= profile[0]["distance_m"]:
        return profile[0]["elevation_m"]
    if distance_m >= profile[-1]["distance_m"]:
        return profile[-1]["elevation_m"]
    for previous, current in zip(profile, profile[1:]):
        if previous["distance_m"] <= distance_m <= current["distance_m"]:
            span = current["distance_m"] - previous["distance_m"]
            if span <= 0:
                return previous["elevation_m"]
            ratio = (distance_m - previous["distance_m"]) / span
            return previous["elevation_m"] + ratio * (current["elevation_m"] - previous["elevation_m"])
    return profile[-1]["elevation_m"]


def _local_gradient_percent(points: list[RoutePoint], distance_m: float, *, window_m: float) -> float | None:
    """Lokale Steigung/Gefälle (Betrag, %) in einem window_m-Fenster um distance_m - identisches
    Verfahren wie break_planning._local_gradient_percent, hier dupliziert (andere Domäne:
    Pausenplanung vs. Gefahreneinschätzung, siehe Modul-Docstring)."""
    before = [p for p in points if p.distance_m <= distance_m]
    after = [p for p in points if p.distance_m >= distance_m]
    if not before or not after:
        return None
    start = max((p for p in before if p.distance_m >= distance_m - window_m / 2), key=lambda p: -p.distance_m, default=before[-1])
    end = min((p for p in after if p.distance_m <= distance_m + window_m / 2), key=lambda p: p.distance_m, default=after[0])
    if end.distance_m <= start.distance_m:
        return None
    return abs(end.elevation_m - start.elevation_m) / (end.distance_m - start.distance_m) * 100  # type: ignore[operator]


def _cross_slope_percent(point: RoutePoint, left_profile: list[dict], right_profile: list[dict]) -> float:
    """Grösstes Quergefälle (links oder rechts) an diesem Punkt - 0.0, wenn für beide Seiten
    keine Daten vorliegen (z. B. weil das Offsetting für beide Seiten fehlgeschlagen ist, siehe
    terrain_danger_service.py: Steigung entlang des Weges bleibt dann die einzige Quelle)."""
    slopes = [
        abs(elevation - point.elevation_m) / CROSS_SECTION_OFFSET_M * 100  # type: ignore[operator]
        for profile in (left_profile, right_profile)
        for elevation in [_elevation_at(profile, point.distance_m)]
        if elevation is not None and point.elevation_m is not None
    ]
    return max(slopes, default=0.0)


def classify_terrain(points: list[RoutePoint], *, left_profile: list[dict], right_profile: list[dict]) -> list[DangerSegment]:
    """Lauflängenkodierte Geländeklassifikation ("normal"/"steep_exposed") entlang der Route.
    "alpine" kommt erst beim Mergen mit der amtlichen Kategorie dazu, siehe
    merge_with_official_status() - diese Funktion kennt den amtlichen Status nicht.

    Klassifiziert wird pro Intervall zwischen zwei aufeinanderfolgenden Punkten, anhand des
    Ankunftspunkts (nicht pro Punkt einzeln) - so partitionieren die Segmente lückenlos und
    überlappungsfrei genau [erster, letzter Punkt], ohne ein künstliches Nullsegment am
    Anfang."""
    with_elevation = [p for p in points if p.elevation_m is not None]
    if len(with_elevation) < 2:
        return []
    segments: list[DangerSegment] = []
    for previous, current in zip(with_elevation, with_elevation[1:]):
        gradient = _local_gradient_percent(with_elevation, current.distance_m, window_m=GRADIENT_WINDOW_M) or 0.0
        cross_slope = _cross_slope_percent(current, left_profile, right_profile)
        danger: DangerLevel = (
            "steep_exposed" if gradient > STEEP_GRADIENT_DANGER_PERCENT or cross_slope > EXPOSED_CROSS_SLOPE_PERCENT else "normal"
        )
        if segments and segments[-1].danger == danger:
            segments[-1] = DangerSegment(segments[-1].from_m, current.distance_m, danger)
        else:
            segments.append(DangerSegment(previous.distance_m, current.distance_m, danger))
    return segments


def merge_with_official_status(terrain_segments: list[DangerSegment], wanderweg_segments: list[dict]) -> list[DangerSegment]:
    """Amtlicher Status "alpinwanderweg" überschreibt die Geländeklassifikation an der
    jeweiligen Distanz immer mit "alpine" (Auftrag: "alle Alpinwanderwege blau markieren,
    unabhängig vom Geländewert"). wanderweg_segments: [{"from_m","to_m","status"}, ...] mit
    bereits tourweiter (nicht leg-relativer) Distanz, siehe terrain_danger_service.py."""
    boundaries = sorted(
        {bound for segment in terrain_segments for bound in (segment.from_m, segment.to_m)}
        | {bound for segment in wanderweg_segments for bound in (segment["from_m"], segment["to_m"])}
    )
    merged: list[DangerSegment] = []
    for from_m, to_m in zip(boundaries, boundaries[1:]):
        midpoint = (from_m + to_m) / 2
        official = next((segment["status"] for segment in wanderweg_segments if segment["from_m"] <= midpoint <= segment["to_m"]), None)
        terrain = next((segment.danger for segment in terrain_segments if segment.from_m <= midpoint <= segment.to_m), "normal")
        danger: DangerLevel = "alpine" if official == "alpinwanderweg" else terrain
        if merged and merged[-1].danger == danger:
            merged[-1] = DangerSegment(merged[-1].from_m, to_m, danger)
        else:
            merged.append(DangerSegment(from_m, to_m, danger))
    return merged
