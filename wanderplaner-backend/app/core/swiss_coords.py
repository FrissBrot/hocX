"""WGS84 <-> LV95 (Swiss/EPSG:2056) Koordinatenumrechnung fuer die swisstopo-APIs, die keine
lat/lon-Eingabe akzeptieren (z. B. profile.json, siehe elevation_service.py). Offizielle
Approximationsformel von swisstopo ("Approximate formulas for the transformation between
Swiss projection coordinates and WGS84", swisstopo, ~1 m Genauigkeit) - bewusst direkt
implementiert statt einer pyproj-Abhaengigkeit fuer diese eine Umrechnung (vermeidet eine
zusaetzliche C-Extension nur fuer zwei Formeln, siehe "vermeide unnötige neue Dependencies").
"""

from __future__ import annotations


def wgs84_to_lv95(lat: float, lon: float) -> tuple[float, float]:
    """(lat, lon) in Grad (WGS84) -> (easting, northing) in Metern (LV95 / EPSG:2056)."""
    lat_sec = lat * 3600
    lon_sec = lon * 3600
    lat_aux = (lat_sec - 169028.66) / 10000
    lon_aux = (lon_sec - 26782.5) / 10000

    easting = (
        2600072.37
        + 211455.93 * lon_aux
        - 10938.51 * lon_aux * lat_aux
        - 0.36 * lon_aux * lat_aux**2
        - 44.54 * lon_aux**3
    )
    northing = (
        1200147.07
        + 308807.95 * lat_aux
        + 3745.25 * lon_aux**2
        + 76.63 * lat_aux**2
        - 194.56 * lon_aux**2 * lat_aux
        + 119.79 * lat_aux**3
    )
    return easting, northing


def lv95_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """(easting, northing) in Metern (LV95 / EPSG:2056) -> (lat, lon) in Grad (WGS84). Inverse
    der offiziellen swisstopo-Approximationsformel (siehe wgs84_to_lv95)."""
    y_aux = (easting - 2600000) / 1000000
    x_aux = (northing - 1200000) / 1000000

    lon = (
        2.6779094
        + 4.728982 * y_aux
        + 0.791484 * y_aux * x_aux
        + 0.1306 * y_aux * x_aux**2
        - 0.0436 * y_aux**3
    )
    lat = (
        16.9023892
        + 3.238272 * x_aux
        - 0.270978 * y_aux**2
        - 0.002528 * x_aux**2
        - 0.0447 * y_aux**2 * x_aux
        - 0.0140 * x_aux**3
    )
    return lat * 100 / 36, lon * 100 / 36
