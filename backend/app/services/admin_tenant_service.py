from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Participant, Tenant, UserTenantRole
from app.schemas.admin import AdminTenantCreate, AdminTenantRead
from app.schemas.user import TenantUpdate
from app.services.document_template_service import DocumentTemplateService
from app.services.tenant_service import apply_tenant_profile_image


def build_admin_tenant_profile_image_url(tenant_id: int, profile_image_path: str | None) -> str | None:
    if not profile_image_path:
        return None
    return f"/api/admin/tenants/{tenant_id}/profile-image"


class AdminTenantService:
    """Cross-tenant tenant management for the platform-admin panel - unscoped by design."""

    def __init__(self) -> None:
        self.document_template_service = DocumentTemplateService()

    def _read_model(self, db: Session, tenant: Tenant) -> AdminTenantRead:
        participant_count = int(
            db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == tenant.id)) or 0
        )
        user_count = int(
            db.scalar(
                select(func.count(func.distinct(UserTenantRole.user_id))).where(
                    UserTenantRole.tenant_id == tenant.id, UserTenantRole.is_active.is_(True)
                )
            )
            or 0
        )
        return AdminTenantRead(
            id=tenant.id,
            name=tenant.name,
            profile_image_path=tenant.profile_image_path,
            profile_image_url=build_admin_tenant_profile_image_url(tenant.id, tenant.profile_image_path),
            public_slug=tenant.public_slug,
            participant_count=participant_count,
            user_count=user_count,
            created_at=tenant.created_at,
        )

    def list_tenants(self, db: Session) -> list[AdminTenantRead]:
        tenants = db.query(Tenant).order_by(Tenant.name.asc()).all()
        return [self._read_model(db, tenant) for tenant in tenants]

    def get_tenant(self, db: Session, tenant_id: int) -> AdminTenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        return self._read_model(db, tenant)

    def create_tenant(self, db: Session, payload: AdminTenantCreate) -> AdminTenantRead:
        tenant = Tenant(name=payload.name, profile_image_path=None)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        self.document_template_service.ensure_default_template_for_tenant(db, tenant.id, tenant.name)
        return self._read_model(db, tenant)

    async def update_tenant(
        self,
        db: Session,
        tenant_id: int,
        payload: TenantUpdate,
        profile_image: UploadFile | None = None,
    ) -> AdminTenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if payload.name is not None:
            tenant.name = payload.name
        if payload.public_slug is not None:
            tenant.public_slug = payload.public_slug
        if profile_image is not None:
            await apply_tenant_profile_image(tenant, profile_image)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return self._read_model(db, tenant)
