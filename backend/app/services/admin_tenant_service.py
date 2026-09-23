from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AppUser,
    Feature,
    Participant,
    Protocol,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    Template,
    Tenant,
    TenantFeature,
    WordImportDocument,
)
from app.schemas.admin import AdminFeatureRead, AdminTenantCreate, AdminTenantPage, AdminTenantRead
from app.schemas.user import TenantUpdate
from app.services.document_template_service import DocumentTemplateService
from app.services.file_service import _safe_storage_path
from app.services import submission_link_service
from app.services.storage_service import StorageService
from app.services.tenant_service import apply_tenant_profile_image


def build_admin_tenant_profile_image_url(tenant_public_id: uuid.UUID, profile_image_path: str | None) -> str | None:
    if not profile_image_path:
        return None
    return f"/api/admin/tenants/{tenant_public_id}/profile-image"


class AdminTenantService:
    """Cross-tenant tenant management for the platform-admin panel - unscoped by design."""

    def __init__(self) -> None:
        self.document_template_service = DocumentTemplateService()
        self.storage_service = StorageService()

    def _read_model(
        self,
        db: Session,
        tenant: Tenant,
        *,
        storage_used_bytes: int | None = None,
        enabled_features: list[str] | None = None,
    ) -> AdminTenantRead:
        participant_count = int(
            db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == tenant.id)) or 0
        )
        user_count = int(
            db.scalar(select(func.count(AppUser.id)).where(AppUser.tenant_id == tenant.id, AppUser.is_active.is_(True))) or 0
        )
        # Single-tenant callers (get_tenant, create/update/clone/import) don't have a
        # prefetched totals dict - fall back to one query for just this tenant.
        if storage_used_bytes is None:
            storage_used_bytes = self.storage_service.total_bytes_by_tenant(db).get(tenant.id, 0)
        if enabled_features is None:
            enabled_features = sorted(
                db.scalars(select(TenantFeature.feature_code).where(TenantFeature.tenant_id == tenant.id))
            )
        return AdminTenantRead(
            id=tenant.public_id,
            name=tenant.name,
            profile_image_path=tenant.profile_image_path,
            profile_image_url=build_admin_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path),
            public_slug=tenant.public_slug,
            participant_count=participant_count,
            user_count=user_count,
            created_at=tenant.created_at,
            storage_used_bytes=storage_used_bytes,
            storage_quota_bytes=tenant.storage_quota_bytes,
            enabled_features=enabled_features,
        )

    def list_tenants(self, db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None) -> AdminTenantPage:
        query = db.query(Tenant).order_by(Tenant.name.asc())
        # Applied before the offset/limit slice (audit A1, 2026-08-16) - the frontend used
        # to filter only the already-fetched current page, so a match on a later page was
        # invisible while browsing an earlier one.
        if q and q.strip():
            query = query.filter(Tenant.name.ilike(f"%{q.strip()}%"))
        total = query.count()
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        tenants = query.all()
        # One query for every tenant's storage total / booked features instead of N+1 -
        # list_tenants can return up to 500 rows (see the route's `le=500` cap).
        storage_totals = self.storage_service.total_bytes_by_tenant(db)
        features_by_tenant: dict[int, list[str]] = {}
        for tenant_id, feature_code in db.execute(select(TenantFeature.tenant_id, TenantFeature.feature_code)).all():
            features_by_tenant.setdefault(tenant_id, []).append(feature_code)
        return AdminTenantPage(
            items=[
                self._read_model(
                    db,
                    tenant,
                    storage_used_bytes=storage_totals.get(tenant.id, 0),
                    enabled_features=sorted(features_by_tenant.get(tenant.id, [])),
                )
                for tenant in tenants
            ],
            total=total,
        )

    def list_features(self, db: Session) -> list[AdminFeatureRead]:
        features = db.query(Feature).order_by(Feature.code.asc()).all()
        return [AdminFeatureRead(code=f.code, name=f.name, description=f.description) for f in features]

    def update_tenant_features(
        self, db: Session, tenant_id: int, enabled_codes: list[str], *, admin_id: int
    ) -> AdminTenantRead | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        wanted = set(enabled_codes)
        current = {
            row.feature_code: row
            for row in db.query(TenantFeature).filter(TenantFeature.tenant_id == tenant_id).all()
        }
        for code, row in current.items():
            if code not in wanted:
                db.delete(row)
        for code in wanted - current.keys():
            db.add(TenantFeature(tenant_id=tenant_id, feature_code=code, enabled_by_admin_id=admin_id))
        db.commit()
        return self._read_model(db, tenant)

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
        # Every new tenant starts with a default Abgabe link (preselected for new Abgaben).
        submission_link_service.create_default_link(db, tenant.id)
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

    def delete_tenant(self, db: Session, tenant_id: int) -> bool:
        """Deletes a tenant and everything under it.

        Plain `DELETE FROM tenant` would fail: several tenant-scoped tables have an
        `ondelete="RESTRICT"` FK into another tenant-scoped table that Postgres may not have
        gotten around to cascading away yet within the same statement - e.g. protocol_image
        RESTRICTs into stored_file, but both cascade from tenant independently, and Postgres
        doesn't guarantee it resolves the longer chain (tenant->protocol->...->protocol_image)
        before the shorter one (tenant->stored_file). Deleting these three tables explicitly
        first (each cascading its own dependents in one self-contained statement) clears every
        such RESTRICT before the final tenant delete ever touches its cascade targets:
        - protocol: takes protocol_element/_block/_image/_text/... and attendance_fine with it,
          clearing protocol_image's restrict into stored_file and protocol's own restricts into
          template/document_template.
        - submission_assignment: takes submission_upload/_file with it, clearing
          submission_upload_file's restrict into stored_file and its own restrict into
          list_definition.
        - template: takes template_element/_block with it, clearing their restrict into
          element_definition, and its own restrict into document_template.
        - word_import_document: has its own (non-nullable) restricts straight into template
          and stored_file - it doesn't cascade from protocol/submission_assignment/template
          (its protocol_id link is SET NULL, not CASCADE), so it must be cleared explicitly
          before the template delete below and before tenant cascades into stored_file.
        """
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return False

        # Captured before any DB delete below (audit finding, 2026-08-25): this method
        # only ever removed DB rows - not one unlink() for protocol images, document
        # template parts, abgabebox uploads, or the tenant's profile image. Every full
        # tenant delete permanently leaked every physical file the tenant ever had,
        # exactly the failure class behind this app's two prior real disk-full outages.
        # stored_file cascades from tenant_id (ondelete="CASCADE"), so every row for this
        # tenant is about to disappear from the DB regardless - this only needs to record
        # enough to find the physical files afterwards.
        upload_ids = list(
            db.scalars(
                select(SubmissionUpload.id)
                .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
                .where(SubmissionAssignment.tenant_id == tenant_id)
            )
        )
        abgabebox_stored_file_ids: set[int] = (
            set(db.scalars(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.upload_id.in_(upload_ids))))
            if upload_ids
            else set()
        )
        stored_files = db.execute(select(StoredFile.storage_path, StoredFile.id).where(StoredFile.tenant_id == tenant_id)).all()
        stored_file_paths = [
            (row.storage_path, settings.abgabebox_storage_root if row.id in abgabebox_stored_file_ids else settings.storage_root)
            for row in stored_files
        ]
        profile_image_path = tenant.profile_image_path

        db.execute(delete(WordImportDocument).where(WordImportDocument.tenant_id == tenant_id))
        db.execute(delete(Protocol).where(Protocol.tenant_id == tenant_id))
        db.execute(delete(SubmissionAssignment).where(SubmissionAssignment.tenant_id == tenant_id))
        db.execute(delete(Template).where(Template.tenant_id == tenant_id))
        db.delete(tenant)
        db.commit()

        # Only after the DB transaction has actually committed - an unlink can't be rolled
        # back, so it must never run ahead of the delete it depends on succeeding.
        for storage_path, root in stored_file_paths:
            self._unlink_quietly(root, storage_path)
        if profile_image_path:
            self._unlink_quietly(settings.storage_root, profile_image_path)
        for relative_dir in (
            f"document_templates/tenant-{tenant_id}",
            f"document_template_parts/tenant-{tenant_id}",
            f"document_template_snapshots/tenant-{tenant_id}",
            f"tenant_imports/tenant-{tenant_id}",
        ):
            directory = _safe_storage_path(settings.storage_root, relative_dir)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
        return True

    def _unlink_quietly(self, root: str, relative_path: str) -> None:
        try:
            path = _safe_storage_path(root, relative_path)
        except Exception:
            return
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
