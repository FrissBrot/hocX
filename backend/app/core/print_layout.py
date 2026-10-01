"""Druckflächen-Geometrie und Blattplatzierung fürs Kartenblatt-PDF (Auftrag Abschnitt 15).
Reine Funktionen, keine DB-/Netzwerkabhängigkeit (weder Bildkompositierung noch LaTeX) -
`map_print_service.py` übersetzt die hier berechneten Blätter in tatsächliche Kartenbilder.

Zwei getrennte Berechnungen:

1. `compute_page_geometry()`: aus Papierformat/Ausrichtung/Massstab die tatsächlich auf dem
   Papier bedruckbare Fläche und die dadurch am Boden abgedeckte Fläche in Metern - das ist
   die Grundlage für "der Massstab im fertigen PDF muss physikalisch korrekt sein" (die
   Bildkompositierung skaliert später exakt auf `ground_width_m`/`ground_height_m`).
2. `plan_sheets()`: platziert Blätter entlang der Route (nicht als starres Raster, siehe
   Docstring dort) mit fester physischer Überlappung, bis die ganze Route abgedeckt ist.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from app.core.swiss_coords import lv95_to_wgs84

# Papierformate in mm (Hochformat, Breite x Höhe) - ISO 216. A4/A3 sind laut Auftrag
# Pflicht, A2/A1 "wenn technisch einfach erweiterbar" - hier nur weitere Tabellenzeilen,
# also aufgenommen.
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
}

ORIENTATIONS = ("portrait", "landscape")

# Auftrag: "Architektur für weitere Massstäbe offen halten" - deshalb kein Enum/CHECK auf
# feste Werte, nur diese drei als Presets im Frontend (siehe hiking-tour-print.tsx).
DEFAULT_SCALES = (10_000, 25_000, 50_000)

# Rand für Legende/Massstabsleiste/Nordpfeil/Attribution/Seitenzahl - unten mehr Platz als an
# den übrigen drei Seiten, da dort die Fusszeile mit all diesen Elementen sitzt.
MARGIN_SIDE_MM = 10.0
MARGIN_TOP_MM = 10.0
MARGIN_BOTTOM_MM = 25.0

SHEET_OVERLAP_MM = 10.0


@dataclass(frozen=True)
class PageGeometry:
    paper: str
    orientation: str
    scale: int
    width_mm: float
    height_mm: float
    printable_width_mm: float
    printable_height_mm: float
    ground_width_m: float
    ground_height_m: float


def compute_page_geometry(*, paper: str, orientation: str, scale: int) -> PageGeometry:
    if paper not in PAPER_SIZES_MM:
        raise ValueError(f"Unknown paper size: {paper}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"Unknown orientation: {orientation}")
    if scale <= 0:
        raise ValueError("Massstab muss positiv sein")

    width_mm, height_mm = PAPER_SIZES_MM[paper]
    if orientation == "landscape":
        width_mm, height_mm = height_mm, width_mm

    printable_width_mm = width_mm - 2 * MARGIN_SIDE_MM
    printable_height_mm = height_mm - MARGIN_TOP_MM - MARGIN_BOTTOM_MM
    # 1 mm auf Papier = `scale` mm am Boden = `scale` / 1000 m am Boden (Definition Massstab
    # 1:scale) - siehe Wiki "Wanderplaner" für den nachgerechneten Beispielfall.
    ground_width_m = printable_width_mm / 1000 * scale
    ground_height_m = printable_height_mm / 1000 * scale

    return PageGeometry(
        paper=paper,
        orientation=orientation,
        scale=scale,
        width_mm=width_mm,
        height_mm=height_mm,
        printable_width_mm=printable_width_mm,
        printable_height_mm=printable_height_mm,
        ground_width_m=ground_width_m,
        ground_height_m=ground_height_m,
    )


@dataclass(frozen=True)
class RoutePoint2D:
    distance_m: float
    x: float
    """LV95-Easting (Meter) - siehe app/core/swiss_coords.py."""
    y: float
    """LV95-Northing (Meter)."""


@dataclass(frozen=True)
class PrintSheet:
    sequence: int
    center_lat: float
    center_lon: float
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    start_distance_m: float
    end_distance_m: float


def plan_sheets(
    points: list[RoutePoint2D],
    *,
    ground_width_m: float,
    ground_height_m: float,
    scale: int = 25_000,
) -> list[PrintSheet]:
    """Nur von der Route durchlaufene Kartenblätter mit 10 mm Überlappung planen.

    Die Verschiebung zum nächsten Blatt ist Blattbreite/-höhe minus 10 mm im
    jeweiligen Massstab. Auch das letzte Blatt wird nicht nachträglich zentriert:
    sonst würde sein Überlappungsstreifen wieder grösser. Bei einem Eckübergang
    werden beide Achsen verschoben. Wieder besuchte Blätter werden wiederverwendet.
    Segment-Schnittpunkte sichern die lückenlose Abdeckung auch dünner GPX-Geometrien.
    """
    overlap_m = SHEET_OVERLAP_MM * scale / 1000
    if scale <= 0 or not all(math.isfinite(v) for v in (ground_width_m, ground_height_m)):
        raise ValueError("Ungültige Blattgrösse oder Massstab")
    if min(ground_width_m, ground_height_m) <= overlap_m:
        raise ValueError("Blattgrösse muss grösser als die Überlappung sein")
    if not points:
        return []

    # Erstes Blatt auf möglichst viele aufeinanderfolgende Punkte zentrieren.
    min_x = max_x = points[0].x
    min_y = max_y = points[0].y
    for point in points[1:]:
        x0, x1 = min(min_x, point.x), max(max_x, point.x)
        y0, y1 = min(min_y, point.y), max(max_y, point.y)
        if x1 - x0 > ground_width_m or y1 - y0 > ground_height_m:
            break
        min_x, max_x, min_y, max_y = x0, x1, y0, y1
    origin_x, origin_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    step_x, step_y = ground_width_m - overlap_m, ground_height_m - overlap_m
    sheets: list[PrintSheet] = []
    indices: dict[tuple[int, int], int] = {}

    def get_sheet(ix: int, iy: int, distance: float) -> int:
        key = (ix, iy)
        if key in indices:
            return indices[key]
        cx, cy = origin_x + ix * step_x, origin_y + iy * step_y
        lat, lon = lv95_to_wgs84(cx, cy)
        index = len(sheets)
        indices[key] = index
        sheets.append(PrintSheet(index + 1, lat, lon,
                                 cx - ground_width_m / 2, cx + ground_width_m / 2,
                                 cy - ground_height_m / 2, cy + ground_height_m / 2,
                                 distance, distance))
        return index

    ix = iy = 0
    active = get_sheet(ix, iy, points[0].distance_m)
    current = points[0]
    epsilon = 1e-7  # LV95-Meter; nur Rundungsrauschen an einem Blattrand.
    for target in points[1:]:
        while True:
            sheet = sheets[active]
            dx, dy = target.x - current.x, target.y - current.y
            if (sheet.min_x - epsilon <= target.x <= sheet.max_x + epsilon
                    and sheet.min_y - epsilon <= target.y <= sheet.max_y + epsilon):
                sheets[active] = replace(sheet, end_distance_m=target.distance_m)
                current = target
                break
            tx = ((sheet.max_x if dx > 0 else sheet.min_x) - current.x) / dx if dx else math.inf
            ty = ((sheet.max_y if dy > 0 else sheet.min_y) - current.y) / dy if dy else math.inf
            t = max(0.0, min(tx, ty))
            crossing = RoutePoint2D(
                current.distance_m + t * (target.distance_m - current.distance_m),
                current.x + t * dx, current.y + t * dy,
            )
            sheets[active] = replace(sheet, end_distance_m=crossing.distance_m)
            move_x, move_y = tx <= ty + 1e-12, ty <= tx + 1e-12
            if move_x:
                ix += 1 if dx > 0 else -1
            if move_y:
                iy += 1 if dy > 0 else -1
            # Entfernungsbereich ist informativ; die Überlappung selbst wird exakt
            # durch die räumliche Blattverschiebung bestimmt, nicht entlang der Route.
            component = max(abs(dx) if move_x else 0, abs(dy) if move_y else 0)
            overlap_distance = overlap_m * (target.distance_m - current.distance_m) / component
            active = get_sheet(ix, iy, max(points[0].distance_m, crossing.distance_m - overlap_distance))
            current = crossing
    return sheets
