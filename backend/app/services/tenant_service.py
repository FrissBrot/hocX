from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser, require_admin
from app.models import Tenant
from app.schemas.user import TenantRead, TenantUpdate
from app.services.document_template_service import DocumentTemplateService


def build_tenant_profile_image_url(tenant_id: int, profile_image_path: str | None) -> str | None:
    if not profile_image_path:
        return None
    return f"/api/tenants/{tenant_id}/profile-image"


async def apply_tenant_profile_image(tenant: Tenant, profile_image: UploadFile) -> None:
    """Stores an uploaded profile image on disk and updates tenant.profile_image_path in place."""
    profile_dir = Path(settings.upload_root) / "tenant-profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(profile_image.filename or "profile").suffix or ".png"
    file_name = f"tenant-{tenant.id}-{uuid4().hex}{suffix}"
    absolute_path = profile_dir / file_name
    content = await profile_image.read()
    absolute_path.write_bytes(content)
    tenant.profile_image_path = os.path.relpath(str(absolute_path), settings.storage_root)


class TenantService:
    def __init__(self) -> None:
        self.document_template_service = DocumentTemplateService()

    def _manageable_tenant_ids(self, actor: CurrentUser) -> set[int]:
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
            public_slug=tenant.public_slug,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )

    def list_tenants(self, db: Session, actor: CurrentUser) -> list[TenantRead]:
        tenant_ids = self._manageable_tenant_ids(actor)
        tenants = db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).order_by(Tenant.name.asc()).all()
        return [self._read_model(tenant) for tenant in tenants]

    def get_tenant(self, db: Session, tenant_id: int, actor: CurrentUser) -> TenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if tenant_id not in self._manageable_tenant_ids(actor):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not accessible")
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
        if tenant_id not in self._manageable_tenant_ids(actor):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant cannot be edited by current user")
        require_admin(actor)

        if payload.name is not None:
            tenant.name = payload.name
        if payload.public_slug is not None:
            tenant.public_slug = payload.public_slug

        if profile_image is not None:
            await apply_tenant_profile_image(tenant, profile_image)

        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return self._read_model(tenant)
