from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HikingTour, HikingTourRouteLeg, HikingTourWaypoint
from app.schemas.hiking_tour import HikingTourCreate, HikingTourPlanRequest
from app.services.elevation_service import ElevationProfileService
from app.services.hiking_tour_analysis_service import HikingTourAnalysisService
from app.services.hiking_tour_service import HikingTourService, _make_point
from app.services.route_landmark_service import RouteLandmarkService
from app.services.routing_service import RoutingService
from app.services.terrain_danger_service import TerrainDangerService


class HikingTourPlanningService:
    """Route, Höhenprofil, Gefahreneinschätzung und Analyse werden gemeinsam oder gar nicht
    gespeichert."""

    def __init__(self, *, tours: HikingTourService | None = None,
                 routing: RoutingService | None = None, elevation: ElevationProfileService | None = None,
                 terrain_danger: TerrainDangerService | None = None,
                 analysis: HikingTourAnalysisService | None = None):
        self.tours = tours or HikingTourService()
        self.routing = routing or RoutingService()
        self.elevation = elevation or ElevationProfileService()
        self.terrain_danger = terrain_danger or TerrainDangerService()
        self.analysis = analysis or HikingTourAnalysisService()

    def create(self, db: Session, payload: HikingTourCreate, *, tenant_id: int) -> HikingTour:
        tour = self.tours.create_tour(db, payload, tenant_id=tenant_id, commit=False)
        return self.recalculate(db, tour, profile=payload.routing_profile or "wanderwege_bevorzugen")

    def save(self, db: Session, tour: HikingTour, payload: HikingTourPlanRequest) -> HikingTour:
        waypoints = {waypoint.public_id: waypoint for waypoint in tour.waypoints}
        update_ids = [update.id for update in payload.updates]
        if len(set(update_ids)) != len(update_ids) or len(set(payload.deletions)) != len(payload.deletions):
            raise ValueError("Wegpunkte dürfen nicht mehrfach geändert werden")
        if set(update_ids) & set(payload.deletions):
            raise ValueError("Ein Wegpunkt kann nicht gleichzeitig geändert und entfernt werden")
        if any(point_id not in waypoints for point_id in update_ids + payload.deletions):
            raise ValueError("Wegpunkt gehört nicht zu dieser Wanderung")
        if any(waypoints[point_id].kind in ("START", "END") for point_id in payload.deletions):
            raise ValueError("Start und Ziel können nur verschoben werden")

        # Alte Abschnitte referenzieren auch automatische Punkte, die gleich ersetzt werden.
        db.query(HikingTourRouteLeg).filter(HikingTourRouteLeg.hiking_tour_id == tour.id).delete()
        db.expire(tour, ["route_legs"])
        for update in payload.updates:
            waypoint = waypoints[update.id]
            for key, value in update.model_dump(exclude={"id", "lat", "lon"}, exclude_unset=True).items():
                setattr(waypoint, key, value)
            if update.lat is not None:
                waypoint.point = _make_point(update.lat, update.lon)
            # Ein bewusst bearbeiteter Automatikpunkt bleibt beim Neuberechnen erhalten.
            if waypoint.auto_generated:
                waypoint.auto_generated = False
                if waypoint.kind != "EMERGENCY_EXIT":
                    waypoint.kind = "USER_DEFINED"
                waypoint.verification_status = None
                waypoint.decision_metrics_json = None
                waypoint.exit_metrics_json = None
            if "break_minutes" in update.model_fields_set:
                waypoint.break_reason = None

        for waypoint in list(tour.waypoints):
            if waypoint.public_id in payload.deletions or waypoint.auto_generated:
                db.delete(waypoint)
        db.flush()
        db.expire(tour, ["waypoints"])
        ordered = list(tour.waypoints)
        end = next((waypoint for waypoint in ordered if waypoint.kind == "END"), None)
        if end is None or not any(waypoint.kind == "START" for waypoint in ordered):
            raise ValueError("Tour benötigt Start und Ziel")
        # UNIQUE(tour, sequence): zuerst in einen freien Sequenzbereich verschieben.
        for waypoint in ordered:
            waypoint.sequence += 1_000_000
        db.flush()
        chain = [waypoint for waypoint in ordered if waypoint is not end]
        names = [waypoint.label for waypoint in ordered]
        landmarks = RouteLandmarkService()
        for addition in payload.additions:
            label = landmarks.unique_name(db, addition.lat, addition.lon, names,
                addition.label or landmarks.nearest_name(db, addition.lat, addition.lon))
            names.append(label)
            waypoint = HikingTourWaypoint(hiking_tour_id=tour.id, kind="USER_DEFINED", label=label,
                description=addition.description, break_minutes=addition.break_minutes, point=_make_point(addition.lat, addition.lon))
            chain.append(waypoint)
            db.add(waypoint)
        chain.append(end)
        for sequence, waypoint in enumerate(chain):
            waypoint.sequence = sequence
        db.flush()
        db.expire(tour, ["waypoints"])
        tour.status = "draft"
        tour.reconnaissance_checklist_json = None
        tour.reconnoitered_at = tour.reconnoitered_by_user_id = None
        tour.approved_at = tour.approved_by_user_id = None
        return self.recalculate(db, tour, profile=payload.routing_profile or tour.routing_profile or "wanderwege_bevorzugen")

    def recalculate(self, db: Session, tour: HikingTour, *, profile: str) -> HikingTour:
        self.routing.compute_route(db, tour, profile=profile, commit=False)
        self.elevation.fetch_and_store(db, tour, commit=False)
        self.terrain_danger.compute_and_store(db, tour, commit=False)
        self.analysis.analyze(db, tour, commit=False)
        db.commit()
        db.refresh(tour)
        return tour
