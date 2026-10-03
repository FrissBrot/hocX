from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from app.services.route_landmark_service import RouteLandmarkService
from app.models import HikingTour, HikingTourWaypoint
from app.repositories.hiking_tour_repository import HikingTourRepository
from app.schemas.hiking_tour import HikingTourCreate, HikingTourUpdate, ReconnaissanceUpdate, WaypointUpdate, ViaPointCreate


def _make_point(lat: float, lon: float):
    # x=lon, y=lat (Standard-GIS-Reihenfolge), SRID 4326 = WGS84 - siehe Migration 0097.
    return from_shape(Point(lon, lat), srid=4326)


class HikingTourService:
    def __init__(self, repository: HikingTourRepository | None = None) -> None:
        self.repository = repository or HikingTourRepository()

    def list_tours(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[HikingTour]:
        return self.repository.list(db, tenant_id=tenant_id, skip=skip, limit=limit)

    def get_tour(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> HikingTour | None:
        return self.repository.get_by_public_id(db, public_id, tenant_id=tenant_id)

    def create_tour(self, db: Session, payload: HikingTourCreate, *, tenant_id: int) -> HikingTour:
        tour = HikingTour(
            tenant_id=tenant_id,
            title=payload.title,
            description=payload.description,
            tour_date=payload.tour_date,
            group_type=payload.group_type,
            speed_factor_kmh=payload.speed_factor_kmh,
            luggage_type=payload.luggage_type,
            planned_start_time=payload.planned_start_time,
            routing_profile=payload.routing_profile,
        )
        self.repository.create(db, tour, commit=False)

        sequence = 0
        start = HikingTourWaypoint(
            hiking_tour_id=tour.id, sequence=sequence, kind="START",
            label=RouteLandmarkService().nearest_name(db, payload.start.lat, payload.start.lon),
            point=_make_point(payload.start.lat, payload.start.lon)
        )
        self.repository.add_waypoint(db, start, commit=False)
        sequence += 1

        for via in payload.via_points:
            waypoint = HikingTourWaypoint(
                hiking_tour_id=tour.id,
                sequence=sequence,
                kind="USER_DEFINED",
                label=via.label or RouteLandmarkService().nearest_name(db, via.lat, via.lon),
                description=via.description,
                point=_make_point(via.lat, via.lon),
            )
            self.repository.add_waypoint(db, waypoint, commit=False)
            sequence += 1

        end = HikingTourWaypoint(
            hiking_tour_id=tour.id, sequence=sequence, kind="END",
            label=RouteLandmarkService().nearest_name(db, payload.end.lat, payload.end.lon),
            point=_make_point(payload.end.lat, payload.end.lon)
        )
        self.repository.add_waypoint(db, end, commit=False)

        db.flush()
        RouteLandmarkService().assign_unique_names(db, tour)
        db.commit()
        db.refresh(tour)
        return tour

    def update_tour(self, db: Session, tour: HikingTour, payload: HikingTourUpdate) -> HikingTour:
        values = payload.model_dump(exclude_unset=True)
        return self.repository.update(db, tour, values)

    def delete_tour(self, db: Session, tour: HikingTour) -> None:
        self.repository.delete(db, tour)

    def _end_waypoint(self, tour: HikingTour) -> HikingTourWaypoint | None:
        # tour.waypoints is loaded ordered by sequence (see HikingTour.waypoints relationship) -
        # END always holds the highest sequence, exactly one per tour (enforced here, not by a
        # DB constraint - a partial-unique-per-kind index would be more complex than the app-
        # level check this codebase otherwise uses for curated validation, see event_service).
        end_waypoints = [wp for wp in tour.waypoints if wp.kind == "END"]
        return end_waypoints[0] if end_waypoints else None

    def add_via_point(self, db: Session, tour: HikingTour, payload: ViaPointCreate) -> HikingTourWaypoint:
        end = self._end_waypoint(tour)
        if end is None:
            raise ValueError("Tour hat keinen Zielpunkt")
        new_sequence = end.sequence
        self.repository.update_waypoint(db, end, {"sequence": end.sequence + 1}, commit=False)
        waypoint = HikingTourWaypoint(
            hiking_tour_id=tour.id,
            sequence=new_sequence,
            kind="USER_DEFINED",
            label=RouteLandmarkService().unique_name(db, payload.lat, payload.lon,
                [wp.label for wp in tour.waypoints],
                payload.label or RouteLandmarkService().nearest_name(db, payload.lat, payload.lon)),
            description=payload.description,
            point=_make_point(payload.lat, payload.lon),
        )
        created = self.repository.add_waypoint(db, waypoint, commit=False)
        db.commit()
        db.refresh(created)
        return created

    def update_waypoint(self, db: Session, waypoint: HikingTourWaypoint, payload: WaypointUpdate) -> HikingTourWaypoint:
        values = payload.model_dump(exclude={"lat", "lon"}, exclude_unset=True)
        if payload.lat is not None and payload.lon is not None:
            values["point"] = _make_point(payload.lat, payload.lon)
        if payload.label:
            point = to_shape(waypoint.point)
            others = db.query(HikingTourWaypoint).filter(
                HikingTourWaypoint.hiking_tour_id == waypoint.hiking_tour_id,
                HikingTourWaypoint.id != waypoint.id,
            ).all()
            values["label"] = RouteLandmarkService().unique_name(db,
                payload.lat if payload.lat is not None else point.y,
                payload.lon if payload.lon is not None else point.x,
                [other.label for other in others], payload.label)
        return self.repository.update_waypoint(db, waypoint, values)

    def delete_waypoint(self, db: Session, waypoint: HikingTourWaypoint) -> None:
        # Auftrag Abschnitt 7: automatisch erzeugte Punkte muessen loeschbar sein, nicht nur
        # vom Benutzer gesetzte Via-Punkte (Phase 4, siehe hiking_tour_analysis_service.py).
        if waypoint.kind != "USER_DEFINED" and not waypoint.auto_generated:
            raise ValueError("Start und Ziel koennen nicht geloescht werden, nur verschoben")
        self.repository.delete_waypoint(db, waypoint)

    def update_reconnaissance(self, db: Session, tour: HikingTour, payload: ReconnaissanceUpdate, *, user_id: int) -> HikingTour:
        """Auftrag Abschnitt 17: eine bewusste Nutzeraktion, nie automatisch aus der Analyse
        gesetzt. Checkliste wird gemerged (mehrere Aufrufe koennen nach und nach Punkte
        abhaken), nicht ersetzt - remarks dagegen komplett ersetzt, wenn mitgeschickt."""
        if tour.status == "approved":
            raise ValueError("Freigegebene Touren können nicht mehr rekognosziert werden")
        merged_checklist = {**(tour.reconnaissance_checklist_json or {}), **payload.checklist}
        values: dict = {
            "reconnaissance_checklist_json": merged_checklist,
            "reconnoitered_at": datetime.now(UTC),
            "reconnoitered_by_user_id": user_id,
        }
        if payload.remarks is not None:
            values["reconnaissance_remarks"] = payload.remarks
        if tour.status in ("draft", "analyzed"):
            values["status"] = "reconnoitered"
        return self.repository.update(db, tour, values)

    def approve_tour(self, db: Session, tour: HikingTour, *, user_id: int) -> HikingTour:
        """Auftrag Abschnitt 17: "Die Software darf eine Tour nicht allein aufgrund
        automatischer Analysen als 'rekognosziert' markieren" - dieselbe bewusste-Aktion-
        Anforderung gilt sinngemäss für die Freigabe, deshalb nur aus 'reconnoitered' heraus
        möglich (nie direkt aus 'draft'/'analyzed')."""
        if tour.status != "reconnoitered":
            raise ValueError("Tour muss zuerst rekognosziert werden, bevor sie freigegeben werden kann")
        return self.repository.update(
            db, tour, {"status": "approved", "approved_at": datetime.now(UTC), "approved_by_user_id": user_id}
        )
