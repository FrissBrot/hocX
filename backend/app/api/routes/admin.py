import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.config import settings
from app.core.db import get_db
from app.schemas.admin import (
    AdminDomainPage,
    AdminDomainRead,
    AdminTenantCreate,
    AdminTenantPage,
    AdminTenantRead,
    AdminTenantUserGrant,
    AdminTenantUserRead,
    AdminUserMergeRequest,
    AdminUserPage,
    PlatformAdminCreate,
    PlatformAdminRead,
    PlatformAdminUpdate,
    SystemErrorLogFilterOptions,
    SystemErrorLogPage,
    TenantCleanupCounts,
    TenantCleanupRequest,
    TenantCloneRequest,
    TenantImportResult,
)
from app.schemas.oidc import PlatformOidcConfigRead, PlatformOidcConfigWrite
from app.schemas.user import TenantUpdate, UserCreate, UserRead, UserUpdate
from app.services.admin_domain_service import AdminDomainService
from app.services.admin_error_log_service import AdminErrorLogService
from app.services.admin_tenant_service import AdminTenantService
from app.services.admin_tenant_user_service import AdminTenantUserService
from app.services.admin_user_service import AdminUserService, PlatformAdminService
from app.services.file_service import _safe_storage_path
from app.services.audit_service import AuditService
from app.services.platform_oidc_service import PlatformOidcService
from app.services.tenant_clone_service import TenantCloneService
from app.services.tenant_cleanup_service import TenantCleanupService
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService

router = APIRouter(dependencies=[Depends(get_current_admin)])

tenant_service = AdminTenantService()
tenant_user_service = AdminTenantUserService()
user_service = AdminUserService()
admin_account_service = PlatformAdminService()
oidc_service = PlatformOidcService()
clone_service = TenantCloneService()
cleanup_service = TenantCleanupService()
domain_service = AdminDomainService()
error_log_service = AdminErrorLogService()
export_service = TenantExportService()
import_service = TenantImportService()
audit = AuditService()


@router.get("/tenants", response_model=AdminTenantPage)
def list_tenants(
    limit: int | None = Query(None, gt=0, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return tenant_service.list_tenants(db, limit=limit, offset=offset, q=q)


@router.get("/domains", response_model=AdminDomainPage)
def list_domains(
    limit: int | None = Query(None, gt=0, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return domain_service.list_domains(db, limit=limit, offset=offset, q=q)


@router.delete("/domains/{domain_id}", status_code=204)
def delete_domain(
    domain_id: int,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    domain = domain_service.delete_domain(db, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    audit.log(
        db, action="admin.domain_deleted", actor_email=current_admin.email, tenant_id=domain.tenant_id,
        entity_type="tenant_domain", entity_id=domain_id, details={"domain": domain.domain, "purpose": domain.purpose},
    )


@router.get("/error-logs", response_model=SystemErrorLogPage)
def list_error_logs(
    tenant_id: int | None = None,
    error_type: str | None = None,
    source: str | None = None,
    limit: int = Query(50, gt=0),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return error_log_service.list_errors(
        db, tenant_id=tenant_id, error_type=error_type, source=source, limit=min(limit, 200), offset=offset
    )


@router.get("/error-logs/filter-options", response_model=SystemErrorLogFilterOptions)
def error_log_filter_options(db: Session = Depends(get_db)):
    return error_log_service.filter_options(db)


@router.post("/tenants", response_model=AdminTenantRead, status_code=201)
def create_tenant(
    payload: AdminTenantCreate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        tenant = tenant_service.create_tenant(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be created") from exc
    audit.log(
        db, action="admin.tenant_created", actor_email=current_admin.email, tenant_id=tenant.id,
        entity_type="tenant", entity_id=tenant.id, details={"name": payload.name},
    )
    return tenant


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
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        tenant = await tenant_service.update_tenant(db, tenant_id, TenantUpdate(name=name, public_slug=public_slug), profile_image)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be updated") from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit.log(
        db, action="admin.tenant_updated", actor_email=current_admin.email, tenant_id=tenant_id,
        entity_type="tenant", entity_id=tenant_id,
        details={"name": name, "public_slug": public_slug, "profile_image_changed": profile_image is not None},
    )
    return tenant


@router.delete("/tenants/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        deleted = tenant_service.delete_tenant(db, tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit.log(db, action="admin.tenant_deleted", actor_email=current_admin.email, tenant_id=tenant_id, entity_type="tenant", entity_id=tenant_id)


@router.get("/tenants/{tenant_id}/cleanup/preview", response_model=TenantCleanupCounts)
def preview_tenant_cleanup(tenant_id: int, db: Session = Depends(get_db)):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return cleanup_service.preview(db, tenant_id)


@router.post("/tenants/{tenant_id}/cleanup", response_model=TenantCleanupCounts)
def cleanup_tenant(
    tenant_id: int,
    payload: TenantCleanupRequest,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.confirm_name.strip() != tenant.name:
        raise HTTPException(status_code=400, detail="Mandantenname stimmt nicht überein")
    if not payload.categories:
        raise HTTPException(status_code=400, detail="Keine Kategorien ausgewählt")
    try:
        counts = cleanup_service.cleanup(db, tenant_id, payload.categories)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufräumen fehlgeschlagen") from exc
    if counts is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit.log(
        db, action="admin.tenant_cleanup", actor_email=current_admin.email, tenant_id=tenant_id,
        entity_type="tenant", entity_id=tenant_id,
        details={"categories": payload.categories, "counts": counts.model_dump()},
    )
    return counts


@router.post("/tenants/{tenant_id}/clone", response_model=AdminTenantRead, status_code=201)
def clone_tenant(
    tenant_id: int,
    payload: TenantCloneRequest,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
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
    audit.log(
        db, action="admin.tenant_cloned", actor_email=current_admin.email, tenant_id=new_tenant.id,
        entity_type="tenant", entity_id=new_tenant.id,
        details={"source_tenant_id": tenant_id, "new_name": payload.new_name, "mode": payload.mode},
    )
    return result


@router.get("/tenants/{tenant_id}/export")
def export_tenant(
    tenant_id: int,
    scope: Literal["structure", "structure_lists", "full", "full_abgabebox"] = "structure",
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(get_current_admin),
):
    try:
        zip_path, filename = export_service.export(db, tenant_id, scope)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit.log(
        db, action="admin.tenant_exported", actor_email=current_admin.email, tenant_id=tenant_id,
        entity_type="tenant", entity_id=tenant_id, details={"scope": scope},
    )
    return FileResponse(
        zip_path,
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(lambda: zip_path.unlink(missing_ok=True)),
    )



# Generous (tenant exports can legitimately be large - full history, abgabebox files) but
# finite, so a single request can't buffer an unbounded amount into memory before any check
# runs (audit S13, 2026-08-16) - only "owner"-role admins can hit this route at all, so this
# is a self-DoS guard rather than a real attacker-facing one. Matches the abgabebox public
# upload ceiling.
MAX_TENANT_IMPORT_UPLOAD_BYTES = 2000 * 1024 * 1024


@router.post("/tenants/import", response_model=TenantImportResult, status_code=201)
async def import_tenant(
    new_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    if file.size is not None and file.size > MAX_TENANT_IMPORT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_TENANT_IMPORT_UPLOAD_BYTES // 1024 // 1024} MB")
    with tempfile.NamedTemporaryFile(prefix="hocx-import-upload-", suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        if len(content) > MAX_TENANT_IMPORT_UPLOAD_BYTES:
            os.unlink(tmp_path)
            raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_TENANT_IMPORT_UPLOAD_BYTES // 1024 // 1024} MB")
        tmp.write(content)
    try:
        new_tenant, warnings = import_service.import_zip(db, tmp_path, new_name)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be imported") from exc
    finally:
        os.unlink(tmp_path)
    result = tenant_service.get_tenant(db, new_tenant.id)
    if result is None:
        raise HTTPException(status_code=500, detail="Imported tenant could not be reloaded")
    audit.log(
        db, action="admin.tenant_imported", actor_email=current_admin.email, tenant_id=new_tenant.id,
        entity_type="tenant", entity_id=new_tenant.id, details={"new_name": new_name, "warning_count": len(warnings)},
    )
    return TenantImportResult(tenant=result, warnings=warnings)


@router.get("/tenants/{tenant_id}/users", response_model=list[AdminTenantUserRead])
def list_tenant_users(tenant_id: int, db: Session = Depends(get_db)):
    return tenant_user_service.list_users(db, tenant_id)


@router.put("/tenants/{tenant_id}/users/{user_id}", response_model=AdminTenantUserRead)
def grant_tenant_user_role(
    tenant_id: int,
    user_id: int,
    payload: AdminTenantUserGrant,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        result = tenant_user_service.grant_or_update_role(db, tenant_id, user_id, payload.role_code)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Role could not be granted") from exc
    audit.log(
        db, action="admin.tenant_user_role_granted", actor_email=current_admin.email, tenant_id=tenant_id,
        entity_type="user", entity_id=user_id, details={"role_code": payload.role_code},
    )
    return result


@router.delete("/tenants/{tenant_id}/users/{user_id}", status_code=204)
def remove_tenant_user(
    tenant_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        removed = tenant_user_service.remove_user(db, tenant_id, user_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Membership could not be removed") from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Membership not found")
    audit.log(
        db, action="admin.tenant_user_removed", actor_email=current_admin.email, tenant_id=tenant_id,
        entity_type="user", entity_id=user_id,
    )


@router.get("/oidc-config", response_model=PlatformOidcConfigRead)
def get_platform_oidc_config(db: Session = Depends(get_db)):
    return oidc_service.get_config(db)


@router.put("/oidc-config", response_model=PlatformOidcConfigRead)
def update_platform_oidc_config(
    payload: PlatformOidcConfigWrite,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    result = oidc_service.upsert_config(db, payload)
    audit.log(
        db, action="admin.oidc_config_updated", actor_email=current_admin.email,
        details={"enabled": payload.enabled, "issuer_url": payload.issuer_url},
    )
    return result


@router.get("/tenants/{tenant_id}/profile-image")
def tenant_profile_image(tenant_id: int, db: Session = Depends(get_db)):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if tenant is None or tenant.profile_image_path is None:
        raise HTTPException(status_code=404, detail="Tenant profile image not found")
    file_path = _safe_storage_path(settings.storage_root, tenant.profile_image_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Tenant profile image missing")
    return FileResponse(file_path)


@router.get("/users", response_model=AdminUserPage)
def list_users(
    limit: int | None = Query(None, gt=0, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return user_service.list_users(db, limit=limit, offset=offset, q=q)


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        result = user_service.create_user(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be created") from exc
    audit.log(
        db, action="admin.user_created", actor_email=current_admin.email,
        entity_type="user", entity_id=result.id, details={"email": payload.email},
    )
    return result


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        user = user_service.update_user(db, user_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be updated") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    audit.log(
        db, action="admin.user_updated", actor_email=current_admin.email,
        entity_type="user", entity_id=user_id,
        details={"password_changed": bool(payload.password), "is_active": payload.is_active},
    )
    return user


@router.post("/users/merge", response_model=UserRead)
def merge_users(payload: AdminUserMergeRequest, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        result = user_service.merge_users(db, source_user_id=payload.source_user_id, target_user_id=payload.target_user_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Users could not be merged") from exc
    audit.log(
        db, action="admin.users_merged", actor_email=current_admin.email, entity_type="user", entity_id=payload.target_user_id,
        details={"source_user_id": payload.source_user_id, "target_user_id": payload.target_user_id},
    )
    return result


@router.get("/admins", response_model=list[PlatformAdminRead])
def list_admins(db: Session = Depends(get_db)):
    return admin_account_service.list_admins(db)


@router.post("/admins", response_model=PlatformAdminRead, status_code=201)
def create_admin(
    payload: PlatformAdminCreate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        result = admin_account_service.create_admin(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Admin account could not be created (email already in use?)") from exc
    audit.log(
        db, action="admin.admin_created", actor_email=current_admin.email,
        entity_type="platform_admin", entity_id=result.id, details={"email": payload.email},
    )
    return result


@router.patch("/admins/{admin_id}", response_model=PlatformAdminRead)
def update_admin(
    admin_id: int,
    payload: PlatformAdminUpdate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    admin = admin_account_service.update_admin(db, admin_id, payload, current_admin_id=current_admin.admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin account not found")
    audit.log(
        db, action="admin.admin_updated", actor_email=current_admin.email,
        entity_type="platform_admin", entity_id=admin_id,
        details={"password_changed": bool(payload.password), "is_active": payload.is_active},
    )
    return admin
