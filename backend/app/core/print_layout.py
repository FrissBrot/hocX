"""Druckflächen-Geometrie und Blattplatzierung fürs Kartenblatt-PDF (Auftrag Abschnitt 15).
Reine Funktionen, keine DB-/Netzwerkabhängigkeit (weder Bildkompositierung noch LaTeX) -
`map_print_service.py` übersetzt die hier berechneten Blätter in tatsächliche Kartenbilder.

Zwei getrennte Berechnungen:

1. `compute_page_geometry()`: aus Papierformat/Ausrichtung/Massstab die tatsächlich auf dem
   Papier bedruckbare Fläche und die dadurch am Boden abgedeckte Fläche in Metern - das ist
   die Grundlage für "der Massstab im fertigen PDF muss physikalisch korrekt sein" (die
   Bildkompositierung skaliert später exakt auf `ground_width_m`/`ground_height_m`).
2. `plan_sheets()`: platziert Blätter entlang der Route (nicht als starres Raster, siehe
   Docstring dort) mit konfigurierbarer Überlappung, bis die ganze Route abgedeckt ist.
"""

from __future__ import annotations

from dataclasses import dataclass

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

DEFAULT_OVERLAP_FRACTION = 0.15


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
    overlap_fraction: float = DEFAULT_OVERLAP_FRACTION,
) -> list[PrintSheet]:
    """Platziert Blätter entlang der Route statt als starres Nord-Süd-Raster (Auftrag
    Abschnitt 15): ein gieriger Durchlauf, der pro Blatt so viele aufeinanderfolgende
    Routenpunkte wie möglich in eine Bounding Box von `ground_width_m` x `ground_height_m`
    packt, bevor das nächste Blatt beginnt. Dadurch braucht ein gerader Streckenabschnitt
    wenige Blätter (die Bounding Box füllt sich langsam), ein verwinkelter Abschnitt
    (Kehren, Spitzkehren) mehr (die Bounding Box füllt sich schnell, obwohl die
    Streckenlänge klein ist) - genau das durch die Streckenform selbst, nicht durch ein
    festes Raster.

    Jedes Blatt ist exakt `ground_width_m` x `ground_height_m` gross (die durch
    `compute_page_geometry()` vorgegebene physische Grösse) und auf den Mittelpunkt der
    abgedeckten Punkte zentriert - die ganze Route bleibt damit lückenlos abgedeckt, auch an
    den Blatträndern.
    """
    if ground_width_m <= 0 or ground_height_m <= 0:
        raise ValueError("Blattgrösse muss positiv sein")
    if not points:
        return []

    sheets: list[PrintSheet] = []
    start_index = 0
    n = len(points)

    while start_index < n:
        min_x = max_x = points[start_index].x
        min_y = max_y = points[start_index].y
        end_index = start_index

        for i in range(start_index + 1, n):
            new_min_x, new_max_x = min(min_x, points[i].x), max(max_x, points[i].x)
            new_min_y, new_max_y = min(min_y, points[i].y), max(max_y, points[i].y)
            if (new_max_x - new_min_x) > ground_width_m or (new_max_y - new_min_y) > ground_height_m:
                break
            min_x, max_x, min_y, max_y = new_min_x, new_max_x, new_min_y, new_max_y
            end_index = i

        center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
        half_w, half_h = ground_width_m / 2, ground_height_m / 2
        lat, lon = lv95_to_wgs84(center_x, center_y)
        sheets.append(
            PrintSheet(
                sequence=len(sheets) + 1,
                center_lat=lat,
                center_lon=lon,
                min_x=center_x - half_w,
                max_x=center_x + half_w,
                min_y=center_y - half_h,
                max_y=center_y + half_h,
                start_distance_m=points[start_index].distance_m,
                end_distance_m=points[end_index].distance_m,
            )
        )

        if end_index == n - 1:
            break
        if end_index == start_index:
            # Schon zwei aufeinanderfolgende Punkte passen nicht mehr in ein Blatt (bei
            # sinnvollen Massstab/Papier-Kombinationen praktisch ausgeschlossen) -
            # garantiert trotzdem Fortschritt statt einer Endlosschleife.
            start_index += 1
            continue

        overlap_m = overlap_fraction * min(ground_width_m, ground_height_m)
        target_distance = points[end_index].distance_m - overlap_m
        next_start = end_index
        for i in range(start_index, end_index + 1):
            if points[i].distance_m >= target_distance:
                next_start = i
                break
        start_index = next_start if next_start > start_index else start_index + 1

    return sheets
