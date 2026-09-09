import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_current_user
from app.models import Tenant, TenantDomain
from app.schemas.user import TenantDomainCreate, TenantDomainRead, TenantRead, TenantUpdate
from app.services import public_id_service
from app.services.file_service import _safe_storage_path
from app.services.tenant_service import TenantService

router = APIRouter()
service = TenantService()


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_tenants(db, user)


@router.patch("/tenants/{tenant_id}", response_model=TenantRead)
async def patch_tenant(
    tenant_id: uuid.UUID,
    name: str | None = Form(default=None),
    public_slug: str | None = Form(default=None),
    profile_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        tenant = await service.update_tenant(
            db, internal_id, user, TenantUpdate(name=name, public_slug=public_slug), profile_image
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be updated") from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/profile-image")
def tenant_profile_image(tenant_id: uuid.UUID, db: Session = Depends(get_db)):
    # Deliberately public (no auth) - this is an organisation logo, not sensitive data, and
    # needs to be renderable on the login page before the visitor has authenticated at all.
    tenant = public_id_service.get_by_public_id(db, Tenant, tenant_id)
    if tenant is None or tenant.profile_image_path is None:
        raise HTTPException(status_code=404, detail="Tenant profile image not found")
    file_path = _safe_storage_path(settings.storage_root, tenant.profile_image_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Tenant profile image missing")
    return FileResponse(file_path)


@router.get("/tenants/{tenant_id}/domains", response_model=list[TenantDomainRead])
def list_tenant_domains(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return service.list_domains(db, internal_id, user)


@router.post("/tenants/{tenant_id}/domains", response_model=TenantDomainRead)
def create_tenant_domain(
    tenant_id: uuid.UUID,
    payload: TenantDomainCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Each create/verify/delete triggers a full Traefik dynamic-config rewrite + reload (and
    # verify can trigger a Let's-Encrypt certificate request) - cap how often a tenant can do
    # that instead of leaving it fully unbounded.
    enforce_rate_limit(f"tenant-domain-mutation:{internal_id}", limit=5, period_seconds=3600)
    return service.create_domain(db, internal_id, user, payload)


@router.post("/tenants/{tenant_id}/domains/{domain_id}/verify", response_model=TenantDomainRead)
def verify_tenant_domain(
    tenant_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    tenant_internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    domain_internal_id = public_id_service.resolve_internal_id(db, TenantDomain, domain_id)
    if tenant_internal_id is None or domain_internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant or domain not found")
    enforce_rate_limit(f"tenant-domain-mutation:{tenant_internal_id}", limit=5, period_seconds=3600)
    return service.verify_domain(db, tenant_internal_id, user, domain_internal_id)


@router.delete("/tenants/{tenant_id}/domains/{domain_id}", response_model=dict[str, str])
def delete_tenant_domain(
    tenant_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    tenant_internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    domain_internal_id = public_id_service.resolve_internal_id(db, TenantDomain, domain_id)
    if tenant_internal_id is None or domain_internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant or domain not found")
    enforce_rate_limit(f"tenant-domain-mutation:{tenant_internal_id}", limit=5, period_seconds=3600)
    service.delete_domain(db, tenant_internal_id, user, domain_internal_id)
    return {"message": "Domain removed"}
