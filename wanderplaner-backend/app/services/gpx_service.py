"""Übersetzt app/core/gpx.py (reines Parsen/Bauen) in HikingTour(Waypoint)-ORM-Objekte und
zurück (Auftrag Abschnitt 16)."""

from __future__ import annotations

import math

from geoalchemy2.shape import to_shape
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.gpx import GpxError, GpxPoint, build_gpx, parse_gpx
from app.core.swiss_coords import wgs84_to_lv95
from app.services.elevation_service import elevation_at_distance
from app.models import HikingTour
from app.schemas.hiking_tour import HikingTourCreate, PointCreate, ViaPointCreate, WaypointUpdate
from app.services.hiking_tour_service import HikingTourService


class GpxImportService:
    def __init__(self, hiking_tour_service: HikingTourService | None = None) -> None:
        self.hiking_tour_service = hiking_tour_service or HikingTourService()

    def import_tour(self, db: Session, content: bytes, *, tenant_id: int, title: str, commit: bool = True) -> HikingTour:
        result = parse_gpx(content)
        try:
            payload = HikingTourCreate(
                title=title,
                start=PointCreate(lat=result.start.lat, lon=result.start.lon),
                end=PointCreate(lat=result.end.lat, lon=result.end.lon),
                via_points=[ViaPointCreate(lat=p.lat, lon=p.lon, label=p.name) for p in result.via_points],
            )
        except ValidationError as exc:
            # Wiederverwendet dieselbe Schweiz/Liechtenstein-Bounding-Box-Pruefung wie ein
            # manuell erstellter Wegpunkt (siehe hiking_tour.py::_validate_within_ch_li) -
            # kein zweites, abweichendes Regelwerk fuer importierte GPX-Punkte.
            raise GpxError("Start/Ziel/Via-Punkte der GPX-Datei liegen ausserhalb der Schweiz/Liechtenstein") from exc
        tour = self.hiking_tour_service.create_tour(db, payload, tenant_id=tenant_id, commit=False)

        # PointCreate (Start/Ziel) kennt anders als ViaPointCreate kein label - benannte
        # Start-/Ziel-Punkte aus der GPX-Datei (z.B. "Start"/"Gipfel") gingen sonst verloren,
        # obwohl die Datei sie mitliefert.
        for waypoint in tour.waypoints:
            name = result.start.name if waypoint.kind == "START" else result.end.name if waypoint.kind == "END" else None
            if name:
                self.hiking_tour_service.update_waypoint(db, waypoint, WaypointUpdate(label=name), commit=False)
        db.flush()
        if commit:
            db.commit()
        db.refresh(tour)
        return tour


class GpxExportService:
    def _track_points(self, tour: HikingTour) -> list[tuple[float, float, float | None]]:
        profile = tour.elevation_profile_json
        points: list[tuple[float, float, float | None]] = []
        cumulative = 0.0
        previous_xy: tuple[float, float] | None = None
        for leg in tour.route_legs:
            line = to_shape(leg.geom)
            for lon, lat in line.coords:
                xy = wgs84_to_lv95(lat, lon)
                if previous_xy is not None:
                    cumulative += math.hypot(xy[0] - previous_xy[0], xy[1] - previous_xy[1])
                previous_xy = xy
                elevation = elevation_at_distance(profile, cumulative) if profile else None
                points.append((lat, lon, elevation))
        return points

    def export_tour(self, tour: HikingTour) -> bytes:
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor ein GPX-Export möglich ist")
        route_points = self._track_points(tour)
        waypoints = []
        for waypoint in tour.waypoints:
            point = to_shape(waypoint.point)
            waypoints.append(GpxPoint(lat=point.y, lon=point.x, name=waypoint.label))
        return build_gpx(title=tour.title, route_points=route_points, waypoints=waypoints)
