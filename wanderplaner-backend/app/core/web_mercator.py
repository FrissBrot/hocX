"""Web-Mercator-Kachel-Mathematik (EPSG:3857, Standard-XYZ/WMTS-Schema) für den
Kartenblatt-Export (Auftrag Abschnitt 15). swisstopo bietet dieselbe Basiskarte auch als
Web-Mercator-WMTS an (`wmts.geo.admin.ch/.../3857/{z}/{x}/{y}.jpeg`) - dasselbe Standardschema
wie MapLibre/Leaflet/OSM, daher hier die üblichen Formeln statt einer swisstopo-spezifischen
Variante. Reine Funktionen, keine Netzwerkabhängigkeit (siehe map_print_service.py für den
tatsächlichen Kachel-Download)."""

from __future__ import annotations

import math

TILE_SIZE_PX = 256
EARTH_CIRCUMFERENCE_M = 40_075_016.68557849  # WGS84-Äquatorumfang


def resolution_m_per_px(zoom: int, lat: float) -> float:
    """Bodenauflösung (m/px) bei gegebenem Zoom UND Breitengrad - Web Mercator verzerrt mit
    cos(lat), am Äquator (lat=0) ist die Formel exakt `EARTH_CIRCUMFERENCE_M / (256 * 2^zoom)`."""
    return (EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat))) / (TILE_SIZE_PX * (2**zoom))


def choose_zoom(target_m_per_px: float, lat: float, *, max_zoom: int = 19) -> int:
    """Kleinster Zoom (= gröbste noch ausreichende Auflösung), dessen Auflösung mindestens so
    fein wie `target_m_per_px` ist - fürs Druck-PDF wird die Bildauflösung ohnehin exakt auf
    die Zielgrösse skaliert (siehe map_print_service.py), daher genügt "mindestens so fein",
    unnötig feinere Zooms würden nur mehr Kacheln laden ohne sichtbaren Gewinn."""
    if target_m_per_px <= 0:
        raise ValueError("target_m_per_px muss positiv sein")
    for zoom in range(0, max_zoom + 1):
        if resolution_m_per_px(zoom, lat) <= target_m_per_px:
            return zoom
    return max_zoom


def lonlat_to_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Globale (nicht kachelrelative) Pixelkoordinate im Standard-Web-Mercator-Schema."""
    lat = max(min(lat, 85.05112878), -85.05112878)  # Web-Mercator-Gültigkeitsbereich
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE_PX
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n * TILE_SIZE_PX
    return x, y


def pixel_to_tile(px: float, py: float) -> tuple[int, int]:
    return int(px // TILE_SIZE_PX), int(py // TILE_SIZE_PX)
