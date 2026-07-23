from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser, require_admin
from app.models import Tenant, TenantDomain
from app.schemas.user import TenantDomainCreate, TenantDomainRead, TenantRead, TenantUpdate
from app.services import domain_verification_service, traefik_config_service
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

    def _require_manageable(self, tenant_id: int, actor: CurrentUser) -> None:
        if tenant_id not in self._manageable_tenant_ids(actor):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not accessible")
        require_admin(actor)

    def _domain_read_model(self, row: TenantDomain) -> TenantDomainRead:
        return TenantDomainRead(
            id=row.id,
            purpose=row.purpose,
            domain=row.domain,
            status=row.status,
            verification_token=row.verification_token,
            challenge_record_name=domain_verification_service.challenge_record_name(row.domain),
            target_host=settings.traefik_domain if row.purpose == "app" else settings.traefik_abgabebox_domain,
            verified_at=row.verified_at,
            is_healthy=row.is_healthy,
            last_checked_at=row.last_checked_at,
        )

    def list_domains(self, db: Session, tenant_id: int, actor: CurrentUser) -> list[TenantDomainRead]:
        self._require_manageable(tenant_id, actor)
        rows = db.query(TenantDomain).filter(TenantDomain.tenant_id == tenant_id).order_by(TenantDomain.purpose.asc()).all()
        return [self._domain_read_model(row) for row in rows]

    def create_domain(
        self, db: Session, tenant_id: int, actor: CurrentUser, payload: TenantDomainCreate
    ) -> TenantDomainRead:
        self._require_manageable(tenant_id, actor)

        domain = domain_verification_service.normalize_domain(payload.domain)
        if not domain_verification_service.is_valid_domain_format(domain):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ungültiges Domain-Format")
        reserved = {d for d in (settings.traefik_domain, settings.traefik_abgabebox_domain) if d}
        if domain in reserved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Diese Domain ist bereits durch hocX belegt")

        # Ersetzt einen ggf. vorhandenen (pending oder active) Eintrag fuer denselben Zweck -
        # ein Mandant hat gemaess Vorgabe genau eine Domain pro Zweck.
        existing = (
            db.query(TenantDomain)
            .filter(TenantDomain.tenant_id == tenant_id, TenantDomain.purpose == payload.purpose)
            .one_or_none()
        )
        if existing is not None:
            db.delete(existing)
            db.flush()

        row = TenantDomain(
            tenant_id=tenant_id,
            purpose=payload.purpose,
            domain=domain,
            verification_token=secrets.token_hex(16),
            status="pending",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Domain ist bereits vergeben") from exc
        db.refresh(row)

        if existing is not None and existing.status == "active":
            traefik_config_service.regenerate(db)

        return self._domain_read_model(row)

    def verify_domain(self, db: Session, tenant_id: int, actor: CurrentUser, domain_id: int) -> TenantDomainRead:
        self._require_manageable(tenant_id, actor)
        row = db.query(TenantDomain).filter(TenantDomain.id == domain_id, TenantDomain.tenant_id == tenant_id).one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain nicht gefunden")

        target_host = settings.traefik_domain if row.purpose == "app" else settings.traefik_abgabebox_domain
        if not target_host:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server-Domain nicht konfiguriert")

        ok, message = domain_verification_service.verify_domain(row.domain, row.verification_token, target_host)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

        row.status = "active"
        row.verified_at = datetime.now(timezone.utc)
        row.is_healthy = True
        row.last_checked_at = row.verified_at
        db.add(row)
        db.commit()
        db.refresh(row)

        traefik_config_service.regenerate(db)
        return self._domain_read_model(row)

    def delete_domain(self, db: Session, tenant_id: int, actor: CurrentUser, domain_id: int) -> None:
        self._require_manageable(tenant_id, actor)
        row = db.query(TenantDomain).filter(TenantDomain.id == domain_id, TenantDomain.tenant_id == tenant_id).one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain nicht gefunden")

        was_active = row.status == "active"
        db.delete(row)
        db.commit()

        if was_active:
            traefik_config_service.regenerate(db)
