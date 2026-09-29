"""GPX-Import/-Export (Auftrag Abschnitt 16, priorisiert vor weiteren Komfortfeatures in
Phase 7). Reine Funktionen, keine DB-Abhängigkeit - app/services/gpx_service.py übersetzt
Ergebnisse in HikingTour(Create)/HikingTourWaypoint.

GPX-Dateien sind nicht vertrauenswürdige Eingaben (Auftrag Abschnitt 22, potenziell von
Fremdquellen hochgeladen). `defusedxml` statt der Standardbibliothek: `xml.etree.ElementTree`
löst zwar keine externen Entities auf (kein klassisches XXE-Dateilesen), begrenzt aber NICHT
die Expansion interner Entities ("billion laughs") - eine Ressourcenerschöpfung, die Abschnitt
22 explizit nennt. `defusedxml` blockiert beides standardmässig."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as defused_ET

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB - grosszügig für eine einzelne Tagestour-GPX
MAX_TRACK_POINTS = 20_000
# Auftrag Abschnitt 22: "unlimitierte Routing-/Analysejobs" vermeiden - jeder importierte
# Via-Punkt wird später einzeln gegen das Wegenetz geroutet (Phase 2), eine GPX mit
# tausenden Punkten darf das nicht ungebremst durchreichen.
MAX_IMPORTED_VIA_POINTS = 30


class GpxError(ValueError):
    """Ungültige/nicht verarbeitbare GPX-Datei (Auftrag Abschnitt 20/22) - immer kuratiert,
    nie ein `system_error_log`-Eintrag (siehe CLAUDE.md: ValueError = erwarteter, bereits
    kuratierter Validierungsfehler)."""


@dataclass(frozen=True)
class GpxPoint:
    lat: float
    lon: float
    name: str | None = None


@dataclass(frozen=True)
class GpxImportResult:
    start: GpxPoint
    end: GpxPoint
    via_points: list[GpxPoint]


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_point(element: Element) -> GpxPoint | None:
    lat_raw, lon_raw = element.get("lat"), element.get("lon")
    if lat_raw is None or lon_raw is None:
        return None
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise GpxError("Ungültige Koordinaten in der GPX-Datei")
    name = None
    for child in element:
        if _strip_ns(child.tag) == "name" and child.text:
            name = child.text.strip()
            break
    return GpxPoint(lat=lat, lon=lon, name=name)


def _collect_points(container: Element, child_tag: str) -> list[GpxPoint]:
    points = []
    for element in container:
        if _strip_ns(element.tag) == child_tag:
            point = _parse_point(element)
            if point is not None:
                points.append(point)
    return points


def parse_gpx(content: bytes) -> GpxImportResult:
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise GpxError(f"GPX-Datei zu gross (maximal {MAX_FILE_SIZE_BYTES // 1024 // 1024} MB)")

    try:
        root = defused_ET.fromstring(content)
    except Exception as exc:
        # Nicht wohlgeformtes XML UND von defusedxml verworfene Konstrukte (DTD, externe
        # Entities, Entity-Expansion) landen beide hier - fuer eine hochgeladene Fremddatei
        # ist "kein gueltiges GPX" die einzig sinnvolle, kuratierte Antwort in jedem Fall,
        # der genaue Grund ist fuer die Nutzerin nicht handlungsrelevant.
        raise GpxError("GPX-Datei ist kein gültiges/erlaubtes XML") from exc

    if _strip_ns(root.tag) != "gpx":
        raise GpxError("Keine gültige GPX-Datei (fehlendes <gpx>-Wurzelelement)")

    points = _collect_points(root, "wpt")

    if not points:
        for child in root:
            if _strip_ns(child.tag) == "rte":
                points = _collect_points(child, "rtept")
                if points:
                    break

    if not points:
        track_points: list[GpxPoint] = []
        for trk in root:
            if _strip_ns(trk.tag) != "trk":
                continue
            for trkseg in trk:
                if _strip_ns(trkseg.tag) != "trkseg":
                    continue
                for element in trkseg:
                    if _strip_ns(element.tag) != "trkpt":
                        continue
                    point = _parse_point(element)
                    if point is not None:
                        track_points.append(point)
                    if len(track_points) > MAX_TRACK_POINTS:
                        raise GpxError(f"GPX-Track hat zu viele Punkte (maximal {MAX_TRACK_POINTS})")
        if not track_points:
            raise GpxError("GPX-Datei enthält keine verwertbaren Punkte (weder Wegpunkte, Route noch Track)")

        max_points = MAX_IMPORTED_VIA_POINTS + 2
        if len(track_points) <= max_points:
            points = track_points
        else:
            # Gleichmaessiges Downsampling auf Start + hoechstens MAX_IMPORTED_VIA_POINTS
            # Zwischenpunkte + Ziel, statt jeden einzelnen Trackpunkt als Wegpunkt zu
            # uebernehmen (eine dichte GPX-Aufzeichnung haette sonst tausende).
            step = (len(track_points) - 1) / (max_points - 1)
            points = [track_points[round(i * step)] for i in range(max_points)]

    if len(points) < 2:
        raise GpxError("GPX-Datei braucht mindestens zwei Punkte (Start und Ziel)")

    via_points = points[1:-1]
    if len(via_points) > MAX_IMPORTED_VIA_POINTS:
        raise GpxError(f"Zu viele Via-/Wegpunkte in der GPX-Datei (maximal {MAX_IMPORTED_VIA_POINTS})")

    return GpxImportResult(start=points[0], end=points[-1], via_points=via_points)


def _escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def build_gpx(*, title: str, route_points: list[tuple[float, float, float | None]], waypoints: list[GpxPoint]) -> bytes:
    """route_points: (lat, lon, elevation_m|None) entlang der berechneten Route. Baut GPX 1.1
    von Hand zusammen (feste, kleine Struktur - kein Template-System nötig, dieselbe
    Konvention wie export_service.py für LaTeX)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="hocX Wanderplaner" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{_escape_xml(title)}</name></metadata>",
    ]
    for point in waypoints:
        lines.append(f'  <wpt lat="{point.lat:.6f}" lon="{point.lon:.6f}">')
        if point.name:
            lines.append(f"    <name>{_escape_xml(point.name)}</name>")
        lines.append("  </wpt>")
    lines.append(f"  <trk>\n    <name>{_escape_xml(title)}</name>\n    <trkseg>")
    for lat, lon, elevation_m in route_points:
        if elevation_m is not None:
            lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{elevation_m:.1f}</ele></trkpt>')
        else:
            lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>')
    lines.append("    </trkseg>\n  </trk>")
    lines.append("</gpx>")
    return "\n".join(lines).encode("utf-8")
