import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_wanderplaner_read, require_wanderplaner_write
from app.models.entities import HikingTour
from app.schemas.hiking_tour import (
    HikingTourCreate,
    HikingTourRead,
    HikingTourSummary,
    HikingTourUpdate,
    RouteComputeRequest,
    ViaPointCreate,
    WaypointRead,
    WaypointUpdate,
)
from app.services.audit_service import AuditService
from app.services.hiking_tour_service import HikingTourService
from app.services.routing_service import RoutingError, RoutingService

router = APIRouter()
service = HikingTourService()
routing_service = RoutingService()
audit = AuditService()


def _get_tour_or_404(db: Session, tour_id: uuid.UUID, user: CurrentUser) -> HikingTour:
    tour = service.get_tour(db, tour_id, tenant_id=user.current_tenant_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="Hiking tour not found")
    return tour


@router.get("/hiking-tours", response_model=list[HikingTourSummary])
def list_hiking_tours(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_read(user)
    return service.list_tours(db, tenant_id=user.current_tenant_id, skip=skip, limit=limit)


@router.post("/hiking-tours", response_model=HikingTourRead, status_code=status.HTTP_201_CREATED)
def create_hiking_tour(
    payload: HikingTourCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    try:
        return service.create_tour(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be created") from exc


@router.get("/hiking-tours/{tour_id}", response_model=HikingTourRead)
def get_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_read(user)
    return _get_tour_or_404(db, tour_id, user)


@router.patch("/hiking-tours/{tour_id}", response_model=HikingTourRead)
def update_hiking_tour(
    tour_id: uuid.UUID,
    payload: HikingTourUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        return service.update_tour(db, tour, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be updated") from exc


@router.delete("/hiking-tours/{tour_id}", response_model=dict[str, str])
def delete_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    tour_internal_id = tour.id
    try:
        service.delete_tour(db, tour)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be deleted") from exc
    audit.log(db, action="hiking_tour.deleted", actor=user, entity_type="hiking_tour", entity_id=tour_internal_id)
    return {"message": "Hiking tour deleted"}


@router.post("/hiking-tours/{tour_id}/route", response_model=HikingTourRead)
def compute_hiking_tour_route(
    tour_id: uuid.UUID,
    payload: RouteComputeRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    profile = payload.routing_profile or tour.routing_profile
    if profile is None:
        raise HTTPException(status_code=422, detail="Kein Routingprofil gewählt")
    try:
        return routing_service.compute_route(db, tour, profile=profile)
    except RoutingError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Route konnte nicht berechnet werden") from exc


@router.post("/hiking-tours/{tour_id}/waypoints", response_model=WaypointRead, status_code=status.HTTP_201_CREATED)
def add_waypoint(
    tour_id: uuid.UUID,
    payload: ViaPointCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        return service.add_via_point(db, tour, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Waypoint could not be created") from exc


@router.patch("/hiking-tours/{tour_id}/waypoints/{waypoint_id}", response_model=WaypointRead)
def update_waypoint(
    tour_id: uuid.UUID,
    waypoint_id: uuid.UUID,
    payload: WaypointUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    waypoint = service.repository.get_waypoint_by_public_id(db, tour, waypoint_id)
    if waypoint is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    try:
        return service.update_waypoint(db, waypoint, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Waypoint could not be updated") from exc


@router.delete("/hiking-tours/{tour_id}/waypoints/{waypoint_id}", response_model=dict[str, str])
def delete_waypoint(
    tour_id: uuid.UUID,
    waypoint_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    waypoint = service.repository.get_waypoint_by_public_id(db, tour, waypoint_id)
    if waypoint is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    try:
        service.delete_waypoint(db, waypoint)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Waypoint could not be deleted") from exc
    return {"message": "Waypoint deleted"}
