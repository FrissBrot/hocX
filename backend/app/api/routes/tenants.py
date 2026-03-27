from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.user import TenantCreate, TenantRead, TenantUpdate
from app.services.tenant_service import TenantService

router = APIRouter()
service = TenantService()


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_tenants(db, user)


@router.post("/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.create_tenant(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be created") from exc


@router.patch("/tenants/{tenant_id}", response_model=TenantRead)
async def patch_tenant(
    tenant_id: int,
    name: str | None = Form(default=None),
    profile_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        tenant = await service.update_tenant(db, tenant_id, user, TenantUpdate(name=name), profile_image)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be updated") from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/profile-image")
def tenant_profile_image(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    tenant = service.get_tenant(db, tenant_id, user)
    if tenant is None or tenant.profile_image_path is None:
        raise HTTPException(status_code=404, detail="Tenant profile image not found")
    file_path = Path(settings.storage_root) / tenant.profile_image_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Tenant profile image missing")
    return FileResponse(file_path)
