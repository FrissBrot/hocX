from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.config import settings
from app.core.db import get_db
from app.schemas.admin import (
    AdminDomainRead,
    AdminTenantCreate,
    AdminTenantRead,
    AdminUserMergeRequest,
    PlatformAdminCreate,
    PlatformAdminRead,
    PlatformAdminUpdate,
    TenantCloneRequest,
)
from app.schemas.oidc import OidcConfigRead, OidcConfigWrite
from app.schemas.user import TenantUpdate, UserCreate, UserRead, UserUpdate
from app.services.admin_domain_service import AdminDomainService
from app.services.admin_tenant_service import AdminTenantService
from app.services.admin_user_service import AdminUserService, PlatformAdminService
from app.services.file_service import _safe_storage_path
from app.services.oidc_service import OidcService
from app.services.tenant_clone_service import TenantCloneService

router = APIRouter(dependencies=[Depends(get_current_admin)])

tenant_service = AdminTenantService()
user_service = AdminUserService()
admin_account_service = PlatformAdminService()
oidc_service = OidcService()
clone_service = TenantCloneService()
domain_service = AdminDomainService()


@router.get("/tenants", response_model=list[AdminTenantRead])
def list_tenants(db: Session = Depends(get_db)):
    return tenant_service.list_tenants(db)


@router.get("/domains", response_model=list[AdminDomainRead])
def list_domains(db: Session = Depends(get_db)):
    return domain_service.list_domains(db)


@router.post("/tenants", response_model=AdminTenantRead, status_code=201)
def create_tenant(payload: AdminTenantCreate, db: Session = Depends(get_db)):
    try:
        return tenant_service.create_tenant(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be created") from exc


@router.get("/tenants/{tenant_id}", response_model=AdminTenantRead)
def get_tenant(tenant_id: int, db: Session = Depends(get_db)):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=AdminTenantRead)
async def update_tenant(
    tenant_id: int,
    name: str | None = Form(default=None),
    public_slug: str | None = Form(default=None),
    profile_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    try:
        tenant = await tenant_service.update_tenant(db, tenant_id, TenantUpdate(name=name, public_slug=public_slug), profile_image)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be updated") from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.post("/tenants/{tenant_id}/clone", response_model=AdminTenantRead, status_code=201)
def clone_tenant(tenant_id: int, payload: TenantCloneRequest, db: Session = Depends(get_db)):
    try:
        if payload.mode == "full":
            new_tenant = clone_service.clone_full(db, tenant_id, payload.new_name)
        else:
            new_tenant = clone_service.clone_structure(db, tenant_id, payload.new_name)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be cloned") from exc
    result = tenant_service.get_tenant(db, new_tenant.id)
    if result is None:
        raise HTTPException(status_code=500, detail="Cloned tenant could not be reloaded")
    return result


@router.get("/tenants/{tenant_id}/oidc-config", response_model=OidcConfigRead)
def get_tenant_oidc_config(tenant_id: int, db: Session = Depends(get_db)):
    cfg = oidc_service.get_config(db, tenant_id)
    if cfg is None:
        return OidcConfigRead(tenant_id=tenant_id, enabled=False, auto_redirect=False, issuer_url="", client_id="", scopes="openid email profile")
    return cfg


@router.put("/tenants/{tenant_id}/oidc-config", response_model=OidcConfigRead)
def update_tenant_oidc_config(tenant_id: int, payload: OidcConfigWrite, db: Session = Depends(get_db)):
    return oidc_service.upsert_config(db, tenant_id, payload)


@router.get("/tenants/{tenant_id}/profile-image")
def tenant_profile_image(tenant_id: int, db: Session = Depends(get_db)):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if tenant is None or tenant.profile_image_path is None:
        raise HTTPException(status_code=404, detail="Tenant profile image not found")
    file_path = _safe_storage_path(settings.storage_root, tenant.profile_image_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Tenant profile image missing")
    return FileResponse(file_path)


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return user_service.list_users(db)


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    try:
        return user_service.create_user(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be created") from exc


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    try:
        user = user_service.update_user(db, user_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be updated") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/merge", response_model=UserRead)
def merge_users(payload: AdminUserMergeRequest, db: Session = Depends(get_db)):
    try:
        return user_service.merge_users(db, source_user_id=payload.source_user_id, target_user_id=payload.target_user_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Users could not be merged") from exc


@router.get("/admins", response_model=list[PlatformAdminRead])
def list_admins(db: Session = Depends(get_db)):
    return admin_account_service.list_admins(db)


@router.post("/admins", response_model=PlatformAdminRead, status_code=201)
def create_admin(payload: PlatformAdminCreate, db: Session = Depends(get_db)):
    try:
        return admin_account_service.create_admin(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Admin account could not be created (email already in use?)") from exc


@router.patch("/admins/{admin_id}", response_model=PlatformAdminRead)
def update_admin(
    admin_id: int,
    payload: PlatformAdminUpdate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(get_current_admin),
):
    admin = admin_account_service.update_admin(db, admin_id, payload, current_admin_id=current_admin.admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin account not found")
    return admin
