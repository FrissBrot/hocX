"""Automatische Wegpunkt-Erkennung aus der Routen-Geometrie (Auftrag Abschnitt 7):
"deutliche Richtungsänderungen" und "Beginn/Ende langer Aufstiege". Reine Funktionen auf
einer einfachen Punktreihe (wie sie das Hoehenprofil, Phase 3, ohnehin schon liefert) - keine
DB-Abhaengigkeit, siehe hiking_tour_analysis_service.py fuer die Uebersetzung in
HikingTourWaypoint-Zeilen.

Pass-/Gipfel-/Huetten-/Wasserstellen-Erkennung (ebenfalls Teil Abschnitt 7) braucht einen
POI-Datensatz (swisstopo-Objektklassen fuer Huetten/Wasserstellen/Gipfelkreuze o.ae.), dessen
genaue Layer-IDs laut Wiki-Seite "Wanderplaner" ("Offene Punkte", seit Phase 2) noch nicht
verifiziert sind - ein echter Import ist ein separater, noch nicht ausgefuehrter
Betriebsschritt (wie der swissTLM3D-Wegenetz-Import). Dieses Modul deckt deshalb nur die rein
geometrisch/aus dem Hoehenprofil ableitbaren Faelle ab; POI-basierte Kinds (SUMMIT/PASS/HUT/
WATER) bleiben bis zu diesem Import unbesetzt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Ab dieser Kursaenderung (Grad) gilt ein Punkt als "deutliche Richtungsaenderung" - kleinere
# Abweichungen sind bei dicht abgetasteten GPS-/Routing-Linien normales Rauschen, kein
# Wegpunkt-wuerdiges Ereignis (Auftrag: "Nicht jeder kleine Richtungswechsel darf einen
# Wegpunkt erzeugen").
DEFAULT_MIN_BEARING_CHANGE_DEG = 50.0
# Mindestabstand (Meter) vor/nach einem Kandidatenpunkt, ueber den die Peilung gemittelt wird -
# glaettet einzelne verrauschte Stuetzpunkte, ohne echte Kehren zu verschlucken.
DEFAULT_BEARING_WINDOW_M = 150.0
# Zwei Richtungsaenderungen naeher als das werden zu einer zusammengefasst (die mit der
# staerkeren Aenderung gewinnt) - vermeidet Wegpunkt-Cluster an einer einzigen Kehrenserie.
DEFAULT_MERGE_DISTANCE_M = 300.0

# Ein Aufstiegsabschnitt zaehlt erst ab dieser Gesamthoehe als "lang" (Auftrag: "Beginn/Ende
# langer Aufstiege" - explizit nicht jede kleine Kuppe).
DEFAULT_MIN_CLIMB_ASCENT_M = 150.0
# Ein kurzer Gegenanstieg/Zwischenabstieg bis zu dieser Hoehe unterbricht einen sonst
# zusammenhaengenden Aufstieg nicht (verhindert, dass eine leicht wellige Passage in viele
# winzige Einzel-"Aufstiege" zerfaellt).
DEFAULT_CLIMB_TOLERANCE_M = 20.0


@dataclass(frozen=True)
class RoutePoint:
    distance_m: float
    lat: float
    lon: float
    elevation_m: float | None = None


@dataclass(frozen=True)
class DirectionChange:
    distance_m: float
    lat: float
    lon: float
    bearing_change_deg: float


@dataclass(frozen=True)
class ClimbSegment:
    start_distance_m: float
    start_lat: float
    start_lon: float
    end_distance_m: float
    end_lat: float
    end_lon: float
    ascent_m: float


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initialer Kurs (Grad, 0-360) von Punkt 1 nach Punkt 2 (Grosskreis-Naeherung - auf
    hocX-Tourdistanzen unter dem Fehler einer ebenen Naeherung irrelevant)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return math.degrees(math.atan2(y, x)) % 360


def _bearing_diff_deg(a: float, b: float) -> float:
    """Kleinster Winkel zwischen zwei Peilungen, 0-180 Grad."""
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff


def _point_at_or_before(points: list[RoutePoint], target_distance_m: float) -> RoutePoint:
    candidate = points[0]
    for point in points:
        if point.distance_m > target_distance_m:
            break
        candidate = point
    return candidate


def _point_at_or_after(points: list[RoutePoint], target_distance_m: float) -> RoutePoint:
    for point in points:
        if point.distance_m >= target_distance_m:
            return point
    return points[-1]


def detect_direction_changes(
    points: list[RoutePoint],
    *,
    min_bearing_change_deg: float = DEFAULT_MIN_BEARING_CHANGE_DEG,
    window_m: float = DEFAULT_BEARING_WINDOW_M,
    merge_distance_m: float = DEFAULT_MERGE_DISTANCE_M,
) -> list[DirectionChange]:
    """Punkte, an denen sich die Wanderrichtung deutlich aendert (Auftrag Abschnitt 7). Peilung
    wird ueber `window_m` vor/nach jedem Kandidaten gemittelt (nicht Punkt-zu-Punkt), damit
    dicht abgetastete Linien nicht durch einzelne verrauschte Stuetzpunkte falsch ausloesen."""
    if len(points) < 3:
        return []

    candidates: list[DirectionChange] = []
    for point in points[1:-1]:
        before = _point_at_or_before(points, point.distance_m - window_m)
        after = _point_at_or_after(points, point.distance_m + window_m)
        if before.distance_m >= point.distance_m or after.distance_m <= point.distance_m:
            continue
        bearing_before = _bearing_deg(before.lat, before.lon, point.lat, point.lon)
        bearing_after = _bearing_deg(point.lat, point.lon, after.lat, after.lon)
        change = _bearing_diff_deg(bearing_before, bearing_after)
        if change >= min_bearing_change_deg:
            candidates.append(DirectionChange(point.distance_m, point.lat, point.lon, change))

    if not candidates:
        return []

    # Cluster benachbarter Kandidaten (< merge_distance_m auseinander) zusammenfassen, jeweils
    # der mit der staerksten Richtungsaenderung gewinnt.
    merged: list[DirectionChange] = []
    cluster = [candidates[0]]
    for change in candidates[1:]:
        if change.distance_m - cluster[-1].distance_m <= merge_distance_m:
            cluster.append(change)
        else:
            merged.append(max(cluster, key=lambda c: c.bearing_change_deg))
            cluster = [change]
    merged.append(max(cluster, key=lambda c: c.bearing_change_deg))
    return merged


def detect_climb_segments(
    points: list[RoutePoint],
    *,
    min_ascent_m: float = DEFAULT_MIN_CLIMB_ASCENT_M,
    tolerance_m: float = DEFAULT_CLIMB_TOLERANCE_M,
) -> list[ClimbSegment]:
    """Zusammenhaengende Aufstiegsabschnitte ab `min_ascent_m` Gesamthoehe (Auftrag Abschnitt
    7: "Beginn langer Aufstiege"/"Ende langer Aufstiege"). Kurze Gegenanstiege/Einsenkungen bis
    `tolerance_m` unterbrechen einen Abschnitt nicht - ohne diese Tolerenz wuerde jede leicht
    wellige Passage in viele einzelne Mini-Aufstiege zerfallen."""
    points_with_elevation = [p for p in points if p.elevation_m is not None]
    if len(points_with_elevation) < 2:
        return []

    segments: list[ClimbSegment] = []
    segment_start: RoutePoint | None = None
    low_point: RoutePoint = points_with_elevation[0]
    high_point: RoutePoint = points_with_elevation[0]

    def close_segment(end_point: RoutePoint) -> None:
        nonlocal segment_start
        if segment_start is not None:
            ascent = high_point.elevation_m - segment_start.elevation_m  # type: ignore[operator]
            if ascent >= min_ascent_m:
                segments.append(
                    ClimbSegment(
                        start_distance_m=segment_start.distance_m,
                        start_lat=segment_start.lat,
                        start_lon=segment_start.lon,
                        end_distance_m=high_point.distance_m,
                        end_lat=high_point.lat,
                        end_lon=high_point.lon,
                        ascent_m=ascent,
                    )
                )
        segment_start = None

    for point in points_with_elevation[1:]:
        elevation = point.elevation_m
        assert elevation is not None
        if segment_start is None:
            if elevation > low_point.elevation_m:  # type: ignore[operator]
                segment_start = low_point
                high_point = point
            else:
                low_point = point
            continue

        if elevation >= high_point.elevation_m:  # type: ignore[operator]
            high_point = point
        elif high_point.elevation_m - elevation > tolerance_m:  # type: ignore[operator]
            # Abstieg ueberschreitet die Toleranz - Aufstiegsabschnitt endet am bisherigen Hoch.
            close_segment(point)
            low_point = point
            high_point = point

    close_segment(points_with_elevation[-1])
    return segments
