"""Kartenblatt-Rendering fürs Druck-PDF (Auftrag Abschnitt 15). Lädt WMTS-Rasterkacheln von
swisstopo, kompositiert sie zu einem Bild pro Blatt in der exakten physischen Grösse/
Auflösung, die `print_layout.compute_page_geometry()` vorgibt (das ist die Grundlage für
"der Massstab im fertigen PDF muss physikalisch korrekt sein" - das Bild wird spaeter in
der PDF-Vorlage mit exakt `printable_width_mm`/`printable_height_mm` eingebettet), und
zeichnet Route/Wegpunkt-Marker/Massstabsleiste/Nordpfeil/Seitenzahl/Attribution darauf.

WMTS statt Vector Tiles (anders als die interaktive Karte, hiking-tour-map.tsx): serverseitig
gibt es keinen MapLibre-Renderer, und ein fertiges Rasterbild pro Kachel lässt sich direkt
zusammensetzen. `ch.swisstopo.pixelkarte-farbe` ist laut docs.geo.admin.ch frei nutzbar,
inklusive für eigene Kartenprodukte - Pflicht ist nur die Quellenangabe, die jedes Blatt
ohnehin bekommt (Auftrag Abschnitt 15)."""

from __future__ import annotations

import base64
import io
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from app.core.print_layout import PageGeometry, PrintSheet
from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95
from app.core.web_mercator import TILE_SIZE_PX, choose_zoom, lonlat_to_pixel, pixel_to_tile

WMTS_URL_TEMPLATE = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.jpeg"
WMTS_LAYER = "ch.swisstopo.pixelkarte-farbe"
PRINT_DPI = 200
FOOTER_FONT_SIZE_PX = 26
SCALE_BAR_FONT_SIZE_PX = 22
REQUEST_TIMEOUT_SECONDS = 15
# Mehr Kacheln als das fuer ein einzelnes Blatt zu laden waere ein Zeichen eines Bugs
# (falscher Zoom/falsche Bounding Box) - lieber laut scheitern als eine Endlosschleife/
# einen riesigen Speicherverbrauch riskieren (Auftrag Abschnitt 22).
MAX_TILES_PER_SHEET = 400
TILE_CACHE_KEY_PREFIX = "wanderplaner:wmts-tile:"
TILE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 Tage, wie elevation_service.py


def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """PILs eingebauter `load_default()` ist eine winzige Bitmap-Schrift (~10px) - auf einem
    200-DPI-Druckbild praktisch unlesbar. matplotlib (bereits eine Abhängigkeit, siehe
    chart-Export) bringt DejaVu Sans mit; darüber statt eines fest einprogrammierten Pfads
    aufgelöst, damit der Pfad nicht an eine bestimmte matplotlib-Version gebunden ist. Fällt
    defensiv auf die Bitmap-Schrift zurück, falls die Schriftauflösung aus irgendeinem Grund
    fehlschlägt (z. B. kein Font-Cache aufgebaut) - lieber ein kleines Label als ein Absturz."""
    try:
        from matplotlib import font_manager

        return ImageFont.truetype(font_manager.findfont("DejaVu Sans"), size_px)
    except Exception:
        return ImageFont.load_default()

# Grobe Entsprechung der Wegpunkt-Farbtokens aus hiking-tour-map.tsx (KIND_COLOR_TOKEN) - als
# RGB-Tupel, weil serverseitiges Python die CSS-Custom-Properties aus design/tokens.css nicht
# lesen kann; keine Design-Regel-Datei deckt Backend-Code ab (siehe design/DESIGN.md Abschnitt
# 1: "jede UI-Änderung" - Rasterbilder in einem PDF sind keine hocX-UI-Oberfläche).
KIND_COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "START": (34, 153, 84),
    "END": (196, 60, 60),
    "NAVIGATION": (52, 106, 196),
    "BREAK": (196, 148, 40),
    "SUMMIT": (90, 60, 160),
    "PASS": (90, 60, 160),
    "HUT": (52, 106, 196),
    "WATER": (52, 106, 196),
    "DECISION": (196, 148, 40),
    "EMERGENCY_EXIT": (196, 60, 60),
    "USER_DEFINED": (52, 106, 196),
}
ROUTE_COLOR_RGB = (90, 60, 160)
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)


class MapPrintServiceError(RuntimeError):
    """Kartendienst (swisstopo WMTS) nicht erreichbar oder Blatt zu gross (Auftrag Abschnitt 20)."""


@dataclass(frozen=True)
class OverlayWaypoint:
    lat: float
    lon: float
    kind: str
    label: str | None = None


@dataclass(frozen=True)
class SheetOverlay:
    route_points: list[tuple[float, float]] = field(default_factory=list)
    """(lat, lon)-Paare entlang der Route."""
    waypoints: list[OverlayWaypoint] = field(default_factory=list)
    sheet_number: int = 1
    total_sheets: int = 1


def _nice_scale_bar_length_m(ground_width_m: float) -> float:
    """Rundet auf einen "schönen" Wert (1/2/5 * 10^n) für die Massstabsleiste, ungefähr ein
    Fünftel der Blattbreite."""
    raw = ground_width_m / 5
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 5, 10):
        candidate = step * magnitude
        if candidate >= raw:
            return candidate
    return 10 * magnitude


class MapPrintService:
    def fetch_tile(self, zoom: int, x: int, y: int) -> Image.Image:
        # Auftrag Abschnitt 21: "Kartendaten [cachen], soweit Lizenz/API dies zulassen" -
        # swisstopo-Rasterkacheln sind statische, oeffentliche Geodaten (aendern sich
        # praktisch nie zwischen zwei Drucken derselben Gegend), Redis-Cache-Key = Kachel-
        # Koordinate (nicht Tour-Id - zwei Touren durch dieselbe Gegend teilen sich Kacheln,
        # genau wie beim Hoehenprofil-Cache in elevation_service.py). TTL 30 Tage, dieselbe
        # Begruendung wie dort.
        # get_redis_sync() ist auf decode_responses=True gepoolt (fuer die ueberall sonst
        # gespeicherten Text-/JSON-Werte, z.B. elevation_service.py) - binaere JPEG-Bytes
        # muessen deshalb base64-kodiert werden, sonst schlaegt schon das Lesen mit einem
        # UnicodeDecodeError fehl.
        cache = get_redis_sync()
        cache_key = f"{TILE_CACHE_KEY_PREFIX}{WMTS_LAYER}:{zoom}:{x}:{y}"
        cached = cache.get(cache_key)
        if cached:
            return Image.open(io.BytesIO(base64.b64decode(cached))).convert("RGB")

        url = WMTS_URL_TEMPLATE.format(layer=WMTS_LAYER, z=zoom, x=x, y=y)
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MapPrintServiceError("Kartendienst (swisstopo) nicht erreichbar") from exc
        cache.setex(cache_key, TILE_CACHE_TTL_SECONDS, base64.b64encode(data).decode("ascii"))
        return Image.open(io.BytesIO(data)).convert("RGB")

    def _project(self, lat: float, lon: float, sheet: PrintSheet, size: tuple[int, int]) -> tuple[float, float]:
        x, y = wgs84_to_lv95(lat, lon)
        px = (x - sheet.min_x) / (sheet.max_x - sheet.min_x) * size[0]
        py = (sheet.max_y - y) / (sheet.max_y - sheet.min_y) * size[1]
        return px, py

    def _stitch_base_map(self, sheet: PrintSheet, target_size: tuple[int, int], target_m_per_px: float) -> Image.Image:
        zoom = choose_zoom(target_m_per_px, sheet.center_lat)
        lat_min, lon_min = lv95_to_wgs84(sheet.min_x, sheet.min_y)
        lat_max, lon_max = lv95_to_wgs84(sheet.max_x, sheet.max_y)
        px_min, py_max = lonlat_to_pixel(lon_min, lat_min, zoom)  # unten-links (kleine lat -> grosse py)
        px_max, py_min = lonlat_to_pixel(lon_max, lat_max, zoom)  # oben-rechts

        tile_x_min, tile_y_min = pixel_to_tile(px_min, py_min)
        tile_x_max, tile_y_max = pixel_to_tile(px_max, py_max)
        tile_count = (tile_x_max - tile_x_min + 1) * (tile_y_max - tile_y_min + 1)
        if tile_count > MAX_TILES_PER_SHEET or tile_count <= 0:
            raise MapPrintServiceError("Kartenblatt benötigt zu viele Kacheln - Massstab/Papierformat prüfen")

        stitched = Image.new("RGB", ((tile_x_max - tile_x_min + 1) * TILE_SIZE_PX, (tile_y_max - tile_y_min + 1) * TILE_SIZE_PX))
        for tx in range(tile_x_min, tile_x_max + 1):
            for ty in range(tile_y_min, tile_y_max + 1):
                stitched.paste(self.fetch_tile(zoom, tx, ty), ((tx - tile_x_min) * TILE_SIZE_PX, (ty - tile_y_min) * TILE_SIZE_PX))

        crop_box = (
            round(px_min - tile_x_min * TILE_SIZE_PX),
            round(py_min - tile_y_min * TILE_SIZE_PX),
            round(px_min - tile_x_min * TILE_SIZE_PX + (px_max - px_min)),
            round(py_min - tile_y_min * TILE_SIZE_PX + (py_max - py_min)),
        )
        return stitched.crop(crop_box).resize(target_size, Image.LANCZOS)

    def render_sheet_image(self, sheet: PrintSheet, geometry: PageGeometry, overlay: SheetOverlay) -> Image.Image:
        target_size = (
            round(geometry.printable_width_mm / 25.4 * PRINT_DPI),
            round(geometry.printable_height_mm / 25.4 * PRINT_DPI),
        )
        target_m_per_px = geometry.ground_width_m / target_size[0]

        image = self._stitch_base_map(sheet, target_size, target_m_per_px)
        draw = ImageDraw.Draw(image)

        if len(overlay.route_points) >= 2:
            line = [self._project(lat, lon, sheet, target_size) for lat, lon in overlay.route_points]
            draw.line(line, fill=ROUTE_COLOR_RGB, width=max(3, target_size[0] // 300))

        marker_radius = max(6, target_size[0] // 150)
        for waypoint in overlay.waypoints:
            px, py = self._project(waypoint.lat, waypoint.lon, sheet, target_size)
            color = KIND_COLOR_RGB.get(waypoint.kind, ROUTE_COLOR_RGB)
            draw.ellipse((px - marker_radius, py - marker_radius, px + marker_radius, py + marker_radius), fill=color, outline=WHITE, width=2)

        self._draw_scale_bar(draw, target_size, geometry)
        self._draw_north_arrow(draw, target_size)
        self._draw_footer_text(draw, target_size, geometry, overlay)
        return image

    def _draw_label(self, draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: ImageFont.ImageFont, *, anchor: str = "la") -> None:
        """Text mit weisser Unterlage - ohne die wäre die Beschriftung auf manchen
        Kartenfarben (Wald, Wasser) kaum lesbar. Volldeckend statt halbtransparent: das
        Basisbild ist RGB (kein Alphakanal), ImageDraw kann darauf nicht echt überblenden."""
        bbox = draw.textbbox(xy, text, font=font, anchor=anchor)
        padding = 4
        draw.rectangle((bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding), fill=WHITE)
        draw.text(xy, text, fill=BLACK, font=font, anchor=anchor)

    def _draw_scale_bar(self, draw: ImageDraw.ImageDraw, size: tuple[int, int], geometry: PageGeometry) -> None:
        bar_length_m = _nice_scale_bar_length_m(geometry.ground_width_m)
        bar_length_px = bar_length_m / geometry.ground_width_m * size[0]
        x0, y0 = 24, size[1] - 24
        label = f"{round(bar_length_m)} m" if bar_length_m < 1000 else f"{bar_length_m / 1000:.1f} km"
        font = _load_font(SCALE_BAR_FONT_SIZE_PX)
        self._draw_label(draw, (x0, y0 - SCALE_BAR_FONT_SIZE_PX - 10), label, font)
        draw.line([(x0, y0), (x0 + bar_length_px, y0)], fill=BLACK, width=4)
        for x in (x0, x0 + bar_length_px):
            draw.line([(x, y0 - 6), (x, y0 + 6)], fill=BLACK, width=4)

    def _draw_north_arrow(self, draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
        # Kein Rotieren der Karte (Auftrag verlangt Ausrichtung nur als Papier-Hoch/Quer, nicht
        # eine an die Route angepasste Kartendrehung) - "oben" ist deshalb immer Norden, der
        # Pfeil ist ein simples Dreieck.
        x, y = size[0] - 40, 50
        draw.polygon([(x, y - 22), (x - 12, y + 14), (x + 12, y + 14)], fill=BLACK, outline=WHITE)
        self._draw_label(draw, (x, y + 18), "N", _load_font(SCALE_BAR_FONT_SIZE_PX), anchor="ma")

    def _draw_footer_text(self, draw: ImageDraw.ImageDraw, size: tuple[int, int], geometry: PageGeometry, overlay: SheetOverlay) -> None:
        text = f"1:{geometry.scale:,}".replace(",", "'") + f"   Blatt {overlay.sheet_number} / {overlay.total_sheets}   © swisstopo"
        self._draw_label(draw, (size[0] - 24, size[1] - 24), text, _load_font(FOOTER_FONT_SIZE_PX), anchor="rs")
