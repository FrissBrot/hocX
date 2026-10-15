"""Gefahreneinschätzung einer Route: kombiniert die amtliche Wanderweg-Kategorie (swisstopo/
SchweizMobil, siehe routing_cost.py::WANDERWEG_STATUSES) mit einer Geländeanalyse aus den
Höhendaten. Reine Funktionen, keine DB-/Netzwerk-Abhängigkeit (siehe terrain_danger_service.py
für den Höhendaten-Abruf) - Stil wie break_planning.py/waypoint_detection.py.

Regel (Auftrag): "wanderweg"/"bergwanderweg" sind normale Wanderwege; sehr steile oder
ausgesetzte Stellen darauf werden "steep_exposed" (orange auf der Karte). Ein Abschnitt mit
amtlichem Status "alpinwanderweg" ist immer "alpine" (blau), unabhängig vom Geländewert - der
amtliche Status hat Vorrang vor der Geländeanalyse, siehe merge_with_official_status().

Erkannt wird:
- Steigung/Gefälle entlang des Weges > STEEP_GRADIENT_DANGER_PERCENT (über ein
  GRADIENT_WINDOW_M-Fenster, mindestens aber über den Abstand zweier Profilpunkte).
- Ausgesetztheit: Gelände fällt CROSS_SECTION_OFFSET_M neben dem Weg (links oder rechts) um
  mehr als EXPOSED_CROSS_SLOPE_PERCENT ab. Nur abfallendes Gelände zählt - eine steile
  Bergflanke oberhalb des Weges ist keine Absturzgefahr.

Die Höhendaten müssen dafür dicht genug sein (terrain_danger_service.py fragt etwa alle
SAMPLE_SPACING_M Meter ab) - das angezeigte Höhenprofil mit 200 Punkten wäre für längere
Touren zu grob, kurze Steilstufen würden weggemittelt.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Literal

import shapely
from shapely.geometry import Point

from app.core.waypoint_detection import RoutePoint

DangerLevel = Literal["normal", "steep_exposed", "alpine"]

# Gewünschter Abstand der Höhenpunkte für die Geländeanalyse.
SAMPLE_SPACING_M = 10.0

# Ab dieser Steigung/Gefälle entlang des Weges (über ein GRADIENT_WINDOW_M-Fenster) gilt eine
# Stelle als "sehr steil". Bewusst ein eigener, höherer Schwellwert als
# routing_cost.STEEP_GRADIENT_THRESHOLD_PERCENT (25%) - jener markiert für die Routenpräferenz
# bereits moderates Gelände, hier geht es um eine tatsächliche Gefahrenmarkierung auf der Karte.
STEEP_GRADIENT_DANGER_PERCENT = 40.0
GRADIENT_WINDOW_M = 40.0

# Ab diesem Gefälle quer zum Weg (Höhenverlust über CROSS_SECTION_OFFSET_M neben dem Weg) gilt
# eine Stelle als "ausgesetzt" (z. B. Gratweg oder Querung über einer Steilflanke). 70% ≈ 35°.
EXPOSED_CROSS_SLOPE_PERCENT = 70.0
CROSS_SECTION_OFFSET_M = 15.0
# Ein Querprofilpunkt zählt nur, wenn er höchstens so weit vom gewünschten Querpunkt entfernt
# liegt - sonst ist die Zuordnung zu unsicher und die Stelle bleibt ohne Querwert.
CROSS_SECTION_MATCH_TOLERANCE_M = CROSS_SECTION_OFFSET_M / 2

# Kurze "normale" Lücken zwischen zwei Gefahrenabschnitten werden zugeschlagen, damit eine
# durchgehende Steilstufe nicht wegen einzelner flacherer Messpunkte in Stücke zerfällt.
DANGER_GAP_BRIDGE_M = 30.0


@dataclass(frozen=True)
class DangerSegment:
    from_m: float
    to_m: float
    danger: DangerLevel

    def as_dict(self) -> dict:
        return {"from_m": self.from_m, "to_m": self.to_m, "danger": self.danger}


Lv95 = tuple[float, float]


def cross_section_targets(centerline: list[Lv95], *, offset_m: float = CROSS_SECTION_OFFSET_M) -> tuple[list[Lv95], list[Lv95]]:
    """Querpunkte links/rechts jedes Linienpunkts (LV95, Meter), senkrecht zur lokalen
    Wegrichtung (aus Vorgänger und Nachfolger). Gleich lang und gleich sortiert wie
    centerline; leer, wenn die Linie keine Richtung hat (alle Punkte identisch)."""
    normals: list[Lv95 | None] = []
    for index in range(len(centerline)):
        e0, n0 = centerline[max(index - 1, 0)]
        e1, n1 = centerline[min(index + 1, len(centerline) - 1)]
        length = math.hypot(e1 - e0, n1 - n0)
        normals.append((-(n1 - n0) / length, (e1 - e0) / length) if length > 0 else None)
    known = [normal for normal in normals if normal is not None]
    if not known:
        return [], []
    # Punkte ohne eigene Richtung (doppelte Stützpunkte) übernehmen die des Vorgängers bzw. am
    # Anfang die erste bekannte.
    last = known[0]
    filled: list[Lv95] = []
    for normal in normals:
        last = normal or last
        filled.append(last)
    left = [(e + ne * offset_m, n + nn * offset_m) for (e, n), (ne, nn) in zip(centerline, filled)]
    right = [(e - ne * offset_m, n - nn * offset_m) for (e, n), (ne, nn) in zip(centerline, filled)]
    return left, right


def downhill_cross_slopes(
    centerline: list[tuple[float, float, float]],
    targets: list[Lv95],
    side_samples: list[tuple[float, float, float]],
    *,
    tolerance_m: float = CROSS_SECTION_MATCH_TOLERANCE_M,
) -> list[float | None]:
    """Gefälle (%) vom Weg zum jeweiligen Querpunkt, pro Linienpunkt. centerline und
    side_samples sind (easting, northing, elevation_m); targets die gewünschten Querpunkte aus
    cross_section_targets(). Die Höhendaten der Querlinie kommen vom Dienst in eigenen
    Abständen zurück - zugeordnet wird deshalb über die Lage (nächster Messpunkt zum
    Querpunkt), nicht über die Distanz entlang der Querlinie, die in Kurven von der
    Wegdistanz abweicht. Ansteigendes Gelände ergibt 0.0, fehlende Zuordnung None."""
    slopes: list[float | None] = [None] * len(centerline)
    if not targets or not side_samples:
        return slopes
    tree = shapely.STRtree([Point(e, n) for e, n, _ in side_samples])
    target_indices, sample_indices = tree.query_nearest(
        [Point(e, n) for e, n in targets], max_distance=tolerance_m, all_matches=False
    )
    for target_index, sample_index in zip(target_indices.tolist(), sample_indices.tolist()):
        center_e, center_n, center_elevation = centerline[target_index]
        sample_e, sample_n, sample_elevation = side_samples[sample_index]
        horizontal_m = math.hypot(sample_e - center_e, sample_n - center_n)
        if horizontal_m < tolerance_m:
            continue
        slopes[target_index] = max(center_elevation - sample_elevation, 0.0) / horizontal_m * 100
    return slopes


def _interval_gradient_percent(points: list[RoutePoint], distances: list[float], index: int, *, window_m: float) -> float:
    """Steigung/Gefälle (Betrag, %) für das Intervall points[index-1]..points[index]: über alle
    Punkte in einem window_m-Fenster um die Intervallmitte, mindestens aber über das Intervall
    selbst - liegen die Punkte weiter auseinander als das Fenster, zählt also der Abstand der
    beiden Nachbarpunkte (vorher ergab das fälschlich 0%)."""
    midpoint = (distances[index - 1] + distances[index]) / 2
    start = min(bisect_left(distances, midpoint - window_m / 2), index - 1)
    end = max(bisect_right(distances, midpoint + window_m / 2) - 1, index)
    span = distances[end] - distances[start]
    if span <= 0:
        return 0.0
    return abs(points[end].elevation_m - points[start].elevation_m) / span * 100  # type: ignore[operator]


def _run_length(intervals: list[tuple[float, float, DangerLevel]]) -> list[DangerSegment]:
    segments: list[DangerSegment] = []
    for from_m, to_m, danger in intervals:
        if segments and segments[-1].danger == danger:
            segments[-1] = DangerSegment(segments[-1].from_m, to_m, danger)
        else:
            segments.append(DangerSegment(from_m, to_m, danger))
    return segments


def _bridge_short_gaps(segments: list[DangerSegment], *, gap_m: float) -> list[DangerSegment]:
    """Kurze normale Abschnitte zwischen zwei steep_exposed-Abschnitten zuschlagen."""
    bridged = [
        DangerSegment(segment.from_m, segment.to_m, "steep_exposed")
        if 0 < index < len(segments) - 1
        and segment.danger == "normal"
        and segment.to_m - segment.from_m < gap_m
        and segments[index - 1].danger == segments[index + 1].danger == "steep_exposed"
        else segment
        for index, segment in enumerate(segments)
    ]
    return _run_length([(segment.from_m, segment.to_m, segment.danger) for segment in bridged])


def classify_terrain(points: list[RoutePoint], *, cross_slopes: list[float | None] | None = None) -> list[DangerSegment]:
    """Lauflängenkodierte Geländeklassifikation ("normal"/"steep_exposed") entlang der Route.
    "alpine" kommt erst beim Mergen mit der amtlichen Kategorie dazu, siehe
    merge_with_official_status() - diese Funktion kennt den amtlichen Status nicht.

    cross_slopes: Gefälle quer zum Weg pro Punkt (gleiche Reihenfolge/Länge wie points, siehe
    downhill_cross_slopes()), None = kein Querwert. Klassifiziert wird pro Intervall zwischen
    zwei aufeinanderfolgenden Punkten; ein ausgesetzter Punkt markiert beide angrenzenden
    Intervalle. So partitionieren die Segmente lückenlos genau [erster, letzter Punkt]."""
    slopes = cross_slopes if cross_slopes is not None else [None] * len(points)
    pairs = [(point, slope) for point, slope in zip(points, slopes) if point.elevation_m is not None]
    if len(pairs) < 2:
        return []
    with_elevation = [point for point, _ in pairs]
    exposed = [slope is not None and slope > EXPOSED_CROSS_SLOPE_PERCENT for _, slope in pairs]
    distances = [point.distance_m for point in with_elevation]

    intervals: list[tuple[float, float, DangerLevel]] = []
    for index in range(1, len(with_elevation)):
        gradient = _interval_gradient_percent(with_elevation, distances, index, window_m=GRADIENT_WINDOW_M)
        danger: DangerLevel = (
            "steep_exposed"
            if gradient > STEEP_GRADIENT_DANGER_PERCENT or exposed[index - 1] or exposed[index]
            else "normal"
        )
        intervals.append((distances[index - 1], distances[index], danger))
    return _bridge_short_gaps(_run_length(intervals), gap_m=DANGER_GAP_BRIDGE_M)


def merge_with_official_status(terrain_segments: list[DangerSegment], wanderweg_segments: list[dict]) -> list[DangerSegment]:
    """Amtlicher Status "alpinwanderweg" überschreibt die Geländeklassifikation an der
    jeweiligen Distanz immer mit "alpine" (Auftrag: "alle Alpinwanderwege blau markieren,
    unabhängig vom Geländewert"). wanderweg_segments: [{"from_m","to_m","status"}, ...] mit
    bereits tourweiter (nicht leg-relativer) Distanz, siehe terrain_danger_service.py."""
    terrain = sorted(terrain_segments, key=lambda segment: segment.from_m)
    terrain_starts = [segment.from_m for segment in terrain]
    alpine = sorted(
        (segment["from_m"], segment["to_m"]) for segment in wanderweg_segments if segment["status"] == "alpinwanderweg"
    )
    boundaries = sorted(
        {bound for segment in terrain for bound in (segment.from_m, segment.to_m)}
        | {bound for interval in alpine for bound in interval}
    )

    def terrain_at(distance_m: float) -> DangerLevel:
        index = bisect_right(terrain_starts, distance_m) - 1
        if index >= 0 and terrain[index].to_m >= distance_m:
            return terrain[index].danger
        return "normal"

    def is_alpine(distance_m: float) -> bool:
        # Wenige amtliche Alpin-Abschnitte pro Tour - lineare Suche reicht.
        return any(from_m <= distance_m <= to_m for from_m, to_m in alpine)

    intervals: list[tuple[float, float, DangerLevel]] = []
    for from_m, to_m in zip(boundaries, boundaries[1:]):
        midpoint = (from_m + to_m) / 2
        intervals.append((from_m, to_m, "alpine" if is_alpine(midpoint) else terrain_at(midpoint)))
    return _run_length(intervals)
