import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.gpx import MAX_FILE_SIZE_BYTES as GPX_MAX_FILE_SIZE_BYTES
from app.core.security import CurrentUser, get_current_user, require_wanderplaner_read, require_wanderplaner_write
from app.models.entities import HikingTour
from app.schemas.hiking_tour import (
    ElevationProfileRead,
    HikingTourCreate,
    HikingTourRead,
    HikingTourSummary,
    HikingTourUpdate,
    PrintRequest,
    PrintResponse,
    ReconnaissanceUpdate,
    RouteComputeRequest,
    ViaPointCreate,
    WaypointRead,
    WaypointUpdate,
    WaypointVerificationUpdate,
)
from app.schemas.march_time import MarchTimeTableRead
from app.services.audit_service import AuditService
from app.services.elevation_service import ElevationProfileService, ElevationServiceError
from app.services.gpx_service import GpxExportService, GpxImportService
from app.services.hiking_tour_analysis_service import HikingTourAnalysisService
from app.services.hiking_tour_print_service import HikingTourPrintService
from app.services.hiking_tour_service import HikingTourService
from app.services.map_print_service import MapPrintServiceError
from app.services.march_time_service import MarchTimeService
from app.services.routing_service import RoutingError, RoutingService

router = APIRouter()
service = HikingTourService()
routing_service = RoutingService()
elevation_service = ElevationProfileService()
march_time_service = MarchTimeService()
analysis_service = HikingTourAnalysisService()
print_service = HikingTourPrintService()
gpx_import_service = GpxImportService()
gpx_export_service = GpxExportService()
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


@router.post("/hiking-tours/gpx-import", response_model=HikingTourRead, status_code=status.HTTP_201_CREATED)
async def import_hiking_tour_gpx(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Auftrag Abschnitt 16: GPX-Import als Ausgangspunkt einer neuen Tour. Liest höchstens
    `MAX_FILE_SIZE_BYTES + 1` Bytes (Auftrag Abschnitt 22: Ressourcenerschöpfung durch riesige
    Dateien vermeiden) - eine tatsächlich überlange Datei wird nie vollständig gepuffert."""
    require_wanderplaner_write(user)
    content = await file.read(GPX_MAX_FILE_SIZE_BYTES + 1)
    try:
        return gpx_import_service.import_tour(db, content, tenant_id=user.current_tenant_id, title=title)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="GPX-Datei konnte nicht importiert werden") from exc


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


@router.post("/hiking-tours/{tour_id}/elevation-profile", response_model=HikingTourRead)
def fetch_elevation_profile(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        return elevation_service.fetch_and_store(db, tour)
    except ElevationServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Höhenprofil konnte nicht abgerufen werden") from exc


@router.get("/hiking-tours/{tour_id}/elevation-profile", response_model=ElevationProfileRead)
def get_elevation_profile(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_read(user)
    tour = _get_tour_or_404(db, tour_id, user)
    if tour.elevation_profile_json is None or tour.elevation_profile_fetched_at is None:
        raise HTTPException(status_code=404, detail="Kein Höhenprofil vorhanden")
    return ElevationProfileRead(fetched_at=tour.elevation_profile_fetched_at, points=tour.elevation_profile_json)


@router.get("/hiking-tours/{tour_id}/march-table", response_model=MarchTimeTableRead)
def get_march_table(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_read(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        table = march_time_service.build_table(tour)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MarchTimeTableRead.from_domain(table)


@router.post("/hiking-tours/{tour_id}/print", response_model=PrintResponse)
async def print_hiking_tour(
    tour_id: uuid.UUID,
    payload: PrintRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Auftrag Abschnitt 15: Kartendruck-PDF (Tourübersicht, Marschzeittabelle, Höhenprofil,
    Kartenblätter). Braucht eine bereits berechnete Route."""
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        stored_file, sheet_count = await print_service.export_pdf(
            db, tour, paper=payload.paper, orientation=payload.orientation, scale=payload.scale, overlap_fraction=payload.overlap_fraction
        )
    except MapPrintServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Druck-PDF konnte nicht erzeugt werden") from exc
    audit.log(db, action="hiking_tour.printed", actor=user, entity_type="hiking_tour", entity_id=tour.id)
    return PrintResponse(
        generated_file_id=stored_file.public_id,
        content_url=f"/api/stored-files/{stored_file.public_id}/content",
        sheet_count=sheet_count,
        created_at=stored_file.created_at,
    )


@router.get("/hiking-tours/{tour_id}/gpx")
def export_hiking_tour_gpx(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Auftrag Abschnitt 16: GPX-Export der Route. Klein/schnell genug, um bei jedem Aufruf
    frisch erzeugt zu werden - anders als das Druck-PDF (Phase 6) kein StoredFile nötig."""
    require_wanderplaner_read(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        content = gpx_export_service.export_tour(tour)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = f"{tour.title}.gpx".replace('"', "")
    return Response(
        content=content,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/hiking-tours/{tour_id}/analyze", response_model=HikingTourRead)
def analyze_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Automatische Analyse (Auftrag Abschnitt 7-11, Phase 4): erkennt zusaetzliche
    Wegpunkte, schlaegt Pausen vor und platziert Entscheidungs-/Notausstiegspunkte. Braucht
    eine bereits berechnete Route UND ein abgerufenes Hoehenprofil (kuratierte 422en unten)."""
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        return analysis_service.analyze(db, tour)
    except (RoutingError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Automatische Analyse konnte nicht durchgeführt werden") from exc


@router.patch("/hiking-tours/{tour_id}/waypoints/{waypoint_id}/verification", response_model=WaypointRead)
def update_waypoint_verification(
    tour_id: uuid.UUID,
    waypoint_id: uuid.UUID,
    payload: WaypointVerificationUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    waypoint = service.repository.get_waypoint_by_public_id(db, tour, waypoint_id)
    if waypoint is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    if waypoint.verification_status is None:
        raise HTTPException(status_code=422, detail="Dieser Wegpunkt hat keinen Verifizierungsstatus")
    try:
        return service.repository.update_waypoint(db, waypoint, {"verification_status": payload.verification_status})
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Waypoint could not be updated") from exc


@router.patch("/hiking-tours/{tour_id}/reconnaissance", response_model=HikingTourRead)
def update_hiking_tour_reconnaissance(
    tour_id: uuid.UUID,
    payload: ReconnaissanceUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Auftrag Abschnitt 17: Rekognoszierungs-Checkliste - eine bewusste Nutzeraktion, die die
    Tour (falls noch nicht weiter) auf 'reconnoitered' setzt."""
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        updated = service.update_reconnaissance(db, tour, payload, user_id=user.user_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Rekognoszierung konnte nicht gespeichert werden") from exc
    audit.log(db, action="hiking_tour.reconnoitered", actor=user, entity_type="hiking_tour", entity_id=tour.id)
    return updated


@router.post("/hiking-tours/{tour_id}/approve", response_model=HikingTourRead)
def approve_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Auftrag Abschnitt 17: Freigabe - eine bewusste Nutzeraktion, nur aus 'reconnoitered'."""
    require_wanderplaner_write(user)
    tour = _get_tour_or_404(db, tour_id, user)
    try:
        updated = service.approve_tour(db, tour, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tour konnte nicht freigegeben werden") from exc
    audit.log(db, action="hiking_tour.approved", actor=user, entity_type="hiking_tour", entity_id=tour.id)
    return updated


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
