import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_db
from app.core.gpx import MAX_FILE_SIZE_BYTES as GPX_MAX_FILE_SIZE_BYTES
from app.core.internal_auth import Caller, get_caller
from app.models import HikingTour
from app.schemas.hiking_tour import (
    ElevationProfileRead,
    HikingTourCreate,
    HikingTourPlanRequest,
    HikingTourRead,
    HikingTourSummary,
    HikingTourUpdate,
    PrintRequest,
    ReconnaissanceUpdate,
    RouteComputeRequest,
    TerrainDangerRead,
    ViaPointCreate,
    WaypointRead,
    WaypointUpdate,
    WaypointVerificationUpdate,
)
from app.schemas.march_time import MarchTimeTableRead
from app.services.elevation_service import ElevationProfileService, ElevationServiceError
from app.services.gpx_service import GpxExportService, GpxImportService
from app.services.hiking_tour_analysis_service import HikingTourAnalysisService
from app.services.hiking_tour_print_service import HikingTourPrintService
from app.services.hiking_tour_planning_service import HikingTourPlanningService
from app.services.hiking_tour_service import HikingTourService
from app.services.map_print_service import MapPrintServiceError
from app.services.march_time_service import MarchTimeService
from app.services.routing_service import RoutingError, RoutingService
from app.services.terrain_danger_service import TerrainDangerServiceError

router = APIRouter()
# Anzahl Kartenblaetter des Druck-PDFs, vom hocX-Backend in PrintResponse uebernommen.
SHEET_COUNT_HEADER = "X-Wanderplaner-Sheet-Count"
service = HikingTourService()
planning_service = HikingTourPlanningService()
routing_service = RoutingService()
elevation_service = ElevationProfileService()
march_time_service = MarchTimeService()
analysis_service = HikingTourAnalysisService()
print_service = HikingTourPrintService()
gpx_import_service = GpxImportService()
gpx_export_service = GpxExportService()


def _get_tour_or_404(db: Session, tour_id: uuid.UUID, caller: Caller) -> HikingTour:
    tour = service.get_tour(db, tour_id, tenant_id=caller.tenant_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="Hiking tour not found")
    return tour


@router.get("/hiking-tours", response_model=list[HikingTourSummary])
def list_hiking_tours(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    return service.list_tours(db, tenant_id=caller.tenant_id, skip=skip, limit=limit)


@router.post("/hiking-tours", response_model=HikingTourRead, status_code=status.HTTP_201_CREATED)
def create_hiking_tour(
    payload: HikingTourCreate,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    try:
        return service.create_tour(db, payload, tenant_id=caller.tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be created") from exc


@router.post("/hiking-tours/planned", response_model=HikingTourRead, status_code=status.HTTP_201_CREATED)
def create_planned_hiking_tour(
    payload: HikingTourCreate,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    try:
        return planning_service.create(db, payload, tenant_id=caller.tenant_id)
    except (RoutingError, ElevationServiceError, TerrainDangerServiceError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Wanderung konnte nicht erstellt werden") from exc


@router.post("/hiking-tours/{tour_id}/plan", response_model=HikingTourRead)
def save_hiking_tour_plan(
    tour_id: uuid.UUID,
    payload: HikingTourPlanRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    # Gleichzeitige Speichervorgänge serialisieren; fremde Touren bleiben unzugänglich.
    tour = db.query(HikingTour).filter(
        HikingTour.public_id == tour_id, HikingTour.tenant_id == caller.tenant_id,
    ).with_for_update(of=HikingTour).first()
    if tour is None:
        raise HTTPException(status_code=404, detail="Hiking tour not found")
    if payload.expected_updated_at is not None and payload.expected_updated_at != tour.updated_at:
        raise HTTPException(status_code=409, detail="Die Wanderung wurde inzwischen geändert. Bitte neu laden.")
    try:
        return planning_service.save(db, tour, payload)
    except (RoutingError, ElevationServiceError, TerrainDangerServiceError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Wanderung konnte nicht gespeichert werden") from exc


@router.post("/hiking-tours/gpx-import", response_model=HikingTourRead, status_code=status.HTTP_201_CREATED)
async def import_hiking_tour_gpx(
    title: str = Form(...),
    file: UploadFile = File(...),
    plan: bool = Query(default=False),
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    """Auftrag Abschnitt 16: GPX-Import als Ausgangspunkt einer neuen Tour. Liest höchstens
    `MAX_FILE_SIZE_BYTES + 1` Bytes (Auftrag Abschnitt 22: Ressourcenerschöpfung durch riesige
    Dateien vermeiden) - eine tatsächlich überlange Datei wird nie vollständig gepuffert."""
    content = await file.read(GPX_MAX_FILE_SIZE_BYTES + 1)
    try:
        tour = await run_in_threadpool(gpx_import_service.import_tour, db, content,
            tenant_id=caller.tenant_id, title=title, commit=not plan)
        if plan:
            return await run_in_threadpool(planning_service.recalculate, db, tour, profile="wanderwege_bevorzugen")
        return tour
    except (RoutingError, ElevationServiceError, TerrainDangerServiceError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="GPX-Datei konnte nicht importiert werden") from exc


@router.get("/hiking-tours/{tour_id}", response_model=HikingTourRead)
def get_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    return _get_tour_or_404(db, tour_id, caller)


@router.patch("/hiking-tours/{tour_id}", response_model=HikingTourRead)
def update_hiking_tour(
    tour_id: uuid.UUID,
    payload: HikingTourUpdate,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    try:
        return service.update_tour(db, tour, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be updated") from exc


@router.delete("/hiking-tours/{tour_id}", response_model=dict[str, str])
def delete_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    tour_internal_id = tour.id
    try:
        service.delete_tour(db, tour)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Hiking tour could not be deleted") from exc
    return {"message": "Hiking tour deleted"}


@router.post("/hiking-tours/{tour_id}/route", response_model=HikingTourRead)
def compute_hiking_tour_route(
    tour_id: uuid.UUID,
    payload: RouteComputeRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    if tour.elevation_profile_json is None or tour.elevation_profile_fetched_at is None:
        raise HTTPException(status_code=404, detail="Kein Höhenprofil vorhanden")
    return ElevationProfileRead(fetched_at=tour.elevation_profile_fetched_at, points=tour.elevation_profile_json)


@router.get("/hiking-tours/{tour_id}/terrain-danger", response_model=TerrainDangerRead)
def get_terrain_danger(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    if tour.terrain_danger_json is None or tour.terrain_danger_computed_at is None:
        raise HTTPException(status_code=404, detail="Keine Gefahreneinschätzung vorhanden")
    return TerrainDangerRead(computed_at=tour.terrain_danger_computed_at, segments=tour.terrain_danger_json)


@router.get("/hiking-tours/{tour_id}/march-table", response_model=MarchTimeTableRead)
def get_march_table(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    try:
        table = march_time_service.build_table(tour)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MarchTimeTableRead.from_domain(table)


@router.post("/hiking-tours/{tour_id}/print")
async def print_hiking_tour(
    tour_id: uuid.UUID,
    payload: PrintRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    """Auftrag Abschnitt 15: Kartendruck-PDF (Tourübersicht, Marschzeittabelle, Höhenprofil,
    Kartenblätter). Braucht eine bereits berechnete Route. Liefert das PDF direkt; das
    hocX-Backend legt es als StoredFile ab und antwortet dem Browser mit PrintResponse."""
    tour = _get_tour_or_404(db, tour_id, caller)
    try:
        pdf_bytes, sheet_count = await print_service.export_pdf(
            db, tour, paper=payload.paper, orientation=payload.orientation, scale=payload.scale
        )
    except MapPrintServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = quote(f"{tour.title}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            SHEET_COUNT_HEADER: str(sheet_count),
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )


@router.get("/hiking-tours/{tour_id}/gpx")
def export_hiking_tour_gpx(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    """Auftrag Abschnitt 16: GPX-Export der Route. Klein/schnell genug, um bei jedem Aufruf
    frisch erzeugt zu werden - anders als das Druck-PDF (Phase 6) kein StoredFile nötig."""
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    """Automatische Analyse (Auftrag Abschnitt 7-11, Phase 4): erkennt zusaetzliche
    Wegpunkte, schlaegt Pausen vor und platziert Entscheidungs-/Notausstiegspunkte. Braucht
    eine bereits berechnete Route UND ein abgerufenes Hoehenprofil (kuratierte 422en unten)."""
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    waypoint = service.repository.get_waypoint_by_public_id(db, tour, waypoint_id)
    if waypoint is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    if waypoint.verification_status is None and not waypoint.auto_generated:
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
    caller: Caller = Depends(get_caller),
):
    """Auftrag Abschnitt 17: Rekognoszierungs-Checkliste - eine bewusste Nutzeraktion, die die
    Tour (falls noch nicht weiter) auf 'reconnoitered' setzt."""
    tour = _get_tour_or_404(db, tour_id, caller)
    try:
        updated = service.update_reconnaissance(db, tour, payload, user_id=caller.user_id, user_name=caller.user_name)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Rekognoszierung konnte nicht gespeichert werden") from exc
    return updated


@router.post("/hiking-tours/{tour_id}/approve", response_model=HikingTourRead)
def approve_hiking_tour(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    """Auftrag Abschnitt 17: Freigabe - eine bewusste Nutzeraktion, nur aus 'reconnoitered'."""
    tour = _get_tour_or_404(db, tour_id, caller)
    try:
        updated = service.approve_tour(db, tour, user_id=caller.user_id, user_name=caller.user_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tour konnte nicht freigegeben werden") from exc
    return updated


@router.post("/hiking-tours/{tour_id}/waypoints", response_model=WaypointRead, status_code=status.HTTP_201_CREATED)
def add_waypoint(
    tour_id: uuid.UUID,
    payload: ViaPointCreate,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
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
    caller: Caller = Depends(get_caller),
):
    tour = _get_tour_or_404(db, tour_id, caller)
    waypoint = service.repository.get_waypoint_by_public_id(db, tour, waypoint_id)
    if waypoint is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    try:
        service.delete_waypoint(db, waypoint)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Waypoint could not be deleted") from exc
    return {"message": "Waypoint deleted"}
