"""Hoehenprofil ueber den offiziellen swisstopo-Dienst (Auftrag Abschnitt 6, siehe Wiki-Seite
"Wanderplaner"). Ruft api3.geo.admin.ch/rest/services/profile.json fuer die komplette
Routengeometrie in einem Aufruf auf (nicht pro Leg) - das Ergebnis ist nach Distanz entlang
der uebergebenen Linie sortiert, passend zur bei der Routenberechnung schon konkatenierten
Reihenfolge der Leg-Geometrien (siehe routing_service.py).

Der Dienst akzeptiert nur LV95(2056)/LV03(21781)-Koordinaten, kein WGS84 - siehe
app/core/swiss_coords.py fuer die Umrechnung.

Caching (Auftrag Abschnitt 21): Redis, Key = Hash der (bereits umgerechneten) Routengeometrie,
nicht der Tour-Id - zwei identische Strecken teilen sich das Ergebnis. TTL 30 Tage: Gelaende
aendert sich praktisch nie, ein swisstopo-Hoehenmodell-Update ist selten und fuer diesen
Anwendungsfall unkritisch (kein Sicherheitsmerkmal, siehe Verifizierungsstatus-Konzept fuer
tatsaechlich sicherheitsrelevante Automatik).
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95
from app.models import HikingTour

PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
CACHE_KEY_PREFIX = "wanderplaner:elevation-profile:"
REQUEST_TIMEOUT_SECONDS = 15
# Grenze der API (siehe docs.geo.admin.ch) fuer die Anzahl Stuetzpunkte - deutlich mehr als
# eine Tageswanderung braucht, aber explizit begrenzt statt unbegrenzt an den Dienst
# durchgereicht (Auftrag Abschnitt 22: "unlimitierte Routing-/Analysejobs" vermeiden).
MAX_POINTS = 5000


class ElevationServiceError(RuntimeError):
    """Hoehendienst nicht erreichbar oder ohne verwertbare Daten (Auftrag Abschnitt 20)."""


def _cache_key(coordinates: list[tuple[float, float]]) -> str:
    payload = json.dumps(coordinates, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def fetch_profile(coordinates: list[tuple[float, float]], *, nb_points: int = 200) -> list[dict]:
    """coordinates: [(lon, lat), ...] entlang der Route (WGS84), in Reihenfolge.
    Gibt [{"distance_m": float, "elevation_m": float}, ...] zurueck, aufsteigend nach
    distance_m ab dem ersten Punkt."""
    if len(coordinates) < 2:
        raise ValueError("Hoehenprofil braucht mindestens zwei Punkte")
    nb_points = min(nb_points, MAX_POINTS)

    cache = get_redis_sync()
    key = _cache_key(coordinates)
    cached = cache.get(key)
    if cached:
        return json.loads(cached)

    lv95_coordinates = [wgs84_to_lv95(lat, lon) for lon, lat in coordinates]
    geom = json.dumps({"type": "LineString", "coordinates": [[e, n] for e, n in lv95_coordinates]})
    body = urllib.parse.urlencode({"geom": geom, "sr": "2056", "nb_points": str(nb_points)}).encode("utf-8")
    request = urllib.request.Request(PROFILE_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise ElevationServiceError("Höhendienst (swisstopo) nicht erreichbar") from exc

    profile: list[dict] = []
    for point in raw:
        alts = point.get("alts")
        elevation = alts.get("COMB") if isinstance(alts, dict) else None
        easting, northing = point.get("easting"), point.get("northing")
        if elevation is None or point.get("dist") is None or easting is None or northing is None:
            continue
        lat, lon = lv95_to_wgs84(float(easting), float(northing))
        profile.append(
            {"distance_m": float(point["dist"]), "elevation_m": float(elevation), "lat": lat, "lon": lon}
        )

    if not profile:
        raise ElevationServiceError("Höhendienst (swisstopo) lieferte keine Höhendaten")

    cache.setex(key, CACHE_TTL_SECONDS, json.dumps(profile))
    return profile


def elevation_at_distance(profile: list[dict], distance_m: float) -> float:
    """Lineare Interpolation der Hoehe an einer bestimmten Distanz entlang des Profils - fuer
    das Zuordnen einer Hoehe zu einem einzelnen Wegpunkt (bekannte kumulierte Distanz)."""
    if not profile:
        raise ValueError("Leeres Höhenprofil")
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


class ElevationProfileService:
    """Orchestriert das Abrufen und Speichern des Hoehenprofils fuer eine Tour (DB-Zugriff,
    im Unterschied zu den reinen Funktionen oben). Braucht eine bereits berechnete Route
    (hiking_tour_route_leg) - das Hoehenprofil folgt der tatsaechlichen Routengeometrie, nicht
    der Luftlinie zwischen den Wegpunkten."""

    def fetch_and_store(self, db: Session, tour: HikingTour, *, commit: bool = True) -> HikingTour:
        legs = list(tour.route_legs)
        if not legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor ein Höhenprofil abgerufen werden kann")

        coordinates: list[tuple[float, float]] = []
        for leg in legs:
            line = to_shape(leg.geom)
            points = list(line.coords)
            if coordinates and points and coordinates[-1] == points[0]:
                points = points[1:]
            coordinates.extend(points)

        profile = fetch_profile(coordinates)
        tour.elevation_profile_json = profile
        tour.elevation_profile_fetched_at = datetime.now(UTC)

        # EMERGENCY_EXIT-Wegpunkte (Phase 4) liegen abseits der Route (kein Teil der
        # fortlaufenden legs-Kette) - ihre Hoehe wird hier nicht mitbefuellt, siehe
        # march_time_service.py fuer denselben Filter und die Begruendung.
        waypoints = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        cumulative_distance = 0.0
        for index, waypoint in enumerate(waypoints):
            if index > 0:
                cumulative_distance += legs[index - 1].distance_m
            waypoint.elevation_m = elevation_at_distance(profile, cumulative_distance)
            db.add(waypoint)

        db.add(tour)
        db.flush()
        if commit:
            db.commit()
        db.refresh(tour)
        return tour
