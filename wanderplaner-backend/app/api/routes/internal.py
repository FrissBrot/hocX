"""Service-zu-Service-Endpunkte fuer das hocX-Backend (nie vom Browser aufgerufen)."""

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.internal_auth import verify_internal_token
from app.models import HikingTour
from app.schemas.internal import PhotoMatch, PhotoMatchRequest, PhotoMatchResponse, TourRef
from app.services.photo_match_service import PhotoPosition, match_photos

router = APIRouter(dependencies=[Depends(verify_internal_token)])


@router.post("/internal/tenants/{tenant_id}/photo-matches", response_model=PhotoMatchResponse)
def photo_matches(tenant_id: int, payload: PhotoMatchRequest, db: Session = Depends(get_db)):
    photos = [PhotoPosition(file_id=p.file_id, lat=p.lat, lon=p.lon, taken_on=p.taken_on) for p in payload.photos]
    tours, matches = match_photos(db, tenant_id, photos)
    return PhotoMatchResponse(
        tours=[TourRef(id=tour.public_id, title=tour.title) for tour in tours],
        matches=[PhotoMatch(file_id=file_id, tour_id=tour.public_id) for file_id, tour in matches.items()],
    )


@router.delete("/internal/tenants/{tenant_id}", response_model=dict[str, int])
def delete_tenant_data(tenant_id: int, db: Session = Depends(get_db)):
    """Wird von hocX nach dem Loeschen eines Mandanten aufgerufen. Wegpunkte und Routen
    haengen per ON DELETE CASCADE an der Tour."""
    deleted = db.execute(delete(HikingTour).where(HikingTour.tenant_id == tenant_id)).rowcount
    db.commit()
    return {"deleted_tours": deleted}
