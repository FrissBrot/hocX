from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser, require_admin, require_superadmin
from app.models import Tenant
from app.schemas.user import TenantCreate, TenantRead, TenantUpdate


def build_tenant_profile_image_url(tenant_id: int, profile_image_path: str | None) -> str | None:
    if not profile_image_path:
        return None
    return f"/api/tenants/{tenant_id}/profile-image"


class TenantService:
    def _manageable_tenant_ids(self, actor: CurrentUser) -> set[int]:
        if actor.is_superadmin:
            return {membership.tenant_id for membership in actor.available_tenants}
        return {
            membership.tenant_id
            for membership in actor.available_tenants
            if membership.role_code == "admin" and membership.is_active
        }

    def _read_model(self, tenant: Tenant) -> TenantRead:
        return TenantRead(
            id=tenant.id,
            name=tenant.name,
            profile_image_path=tenant.profile_image_path,
            profile_image_url=build_tenant_profile_image_url(tenant.id, tenant.profile_image_path),
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )

    def list_tenants(self, db: Session, actor: CurrentUser) -> list[TenantRead]:
        if actor.is_superadmin:
            return [self._read_model(tenant) for tenant in db.query(Tenant).order_by(Tenant.name.asc()).all()]
        tenant_ids = self._manageable_tenant_ids(actor)
        tenants = db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).order_by(Tenant.name.asc()).all()
        return [self._read_model(tenant) for tenant in tenants]

    def get_tenant(self, db: Session, tenant_id: int, actor: CurrentUser) -> TenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if not actor.is_superadmin and tenant_id not in self._manageable_tenant_ids(actor):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not accessible")
        return self._read_model(tenant)

    def create_tenant(self, db: Session, actor: CurrentUser, payload: TenantCreate) -> TenantRead:
        require_superadmin(actor)
        tenant = Tenant(name=payload.name, profile_image_path=None)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return self._read_model(tenant)

    async def update_tenant(
        self,
        db: Session,
        tenant_id: int,
        actor: CurrentUser,
        payload: TenantUpdate,
        profile_image: UploadFile | None = None,
    ) -> TenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if actor.is_superadmin:
            pass
        elif tenant_id not in self._manageable_tenant_ids(actor):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant cannot be edited by current user")
        else:
            require_admin(actor)

        if payload.name is not None:
            tenant.name = payload.name

        if profile_image is not None:
            profile_dir = Path(settings.upload_root) / "tenant-profiles"
            profile_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(profile_image.filename or "profile").suffix or ".png"
            file_name = f"tenant-{tenant_id}-{uuid4().hex}{suffix}"
            absolute_path = profile_dir / file_name
            content = await profile_image.read()
            absolute_path.write_bytes(content)
            tenant.profile_image_path = os.path.relpath(str(absolute_path), settings.storage_root)

        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return self._read_model(tenant)
