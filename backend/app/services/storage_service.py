from __future__ import annotations

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    GalleryImage,
    ProtocolExportCache,
    ProtocolImage,
    StoredFile,
    SubmissionUploadFile,
    Tenant,
    WordImportDocument,
)
from app.schemas.storage import StorageCategoryUsage, StorageUsageRead

CATEGORY_LABELS: dict[str, str] = {
    "photos": "Fotos",
    "files": "Dateien",
    "protocols": "Protokolle",
    "other": "Sonstiges",
}

# "other" always last.
_KNOWN_CATEGORY_KEYS = ("photos", "files", "protocols")


class StorageService:
    """Computes per-tenant disk usage from `stored_file.file_size_bytes`, grouped the way
    users think about their data rather than by technical origin table - mirroring the
    "Fotos" / "Dateien" split of the files overview (StoredFileRepository.list_tenant_files:
    only_images vs. exclude_images, i.e. `mime_type LIKE 'image/%'`):

    - photos:    uploaded images (protocol images, gallery uploads, image submissions)
    - files:     every other upload (word-import sources, abgabebox documents, ...)
    - protocols: generated PDF/LaTeX exports (protocol_export_cache). The "Dateien"
                 overview deliberately excludes these (a generated PDF isn't something a
                 user "hochgeladen" hat), but they occupy real disk space and belong in a
                 storage report.
    - other:     everything else - tenant-import/-clone artifacts, orphaned rows, non-
                 image-typed leftovers. (The tenant logo is a raw path on Tenant, not a
                 stored_file row at all.) Each stored_file lands in exactly one bucket, so
                 the categories always reconcile with SUM(file_size_bytes), the number that
                 actually matters for a quota check.
    """

    def _category_sums(self, db: Session, tenant_id: int | None) -> dict[int, dict[str, int]]:
        """tenant_id=None sums across every tenant at once (admin list), otherwise scoped to one."""
        is_export = StoredFile.id.in_(select(ProtocolExportCache.generated_file_id))
        is_upload = or_(
            StoredFile.id.in_(select(ProtocolImage.stored_file_id)),
            StoredFile.id.in_(select(GalleryImage.stored_file_id)),
            StoredFile.id.in_(select(WordImportDocument.stored_file_id)),
            StoredFile.id.in_(select(SubmissionUploadFile.stored_file_id)),
        )
        is_image = StoredFile.mime_type.like("image/%")
        category = case(
            (is_export, "protocols"),
            (is_upload & is_image, "photos"),
            (is_upload, "files"),
            else_="other",
        ).label("category")

        query = select(
            StoredFile.tenant_id, category, func.coalesce(func.sum(StoredFile.file_size_bytes), 0)
        ).group_by(StoredFile.tenant_id, category)
        if tenant_id is not None:
            query = query.where(StoredFile.tenant_id == tenant_id)

        totals: dict[int, dict[str, int]] = {}
        for row_tenant_id, key, total in db.execute(query).all():
            bucket = totals.setdefault(row_tenant_id, {})
            bucket[key] = int(total or 0)
            bucket["total"] = bucket.get("total", 0) + int(total or 0)
        return totals

    def total_bytes_by_tenant(self, db: Session) -> dict[int, int]:
        """Cheap one-query total per tenant - used for the admin tenant list, which only
        needs the headline number, not the full per-category breakdown."""
        rows = db.execute(
            select(StoredFile.tenant_id, func.coalesce(func.sum(StoredFile.file_size_bytes), 0)).group_by(
                StoredFile.tenant_id
            )
        ).all()
        return {tenant_id: int(total or 0) for tenant_id, total in rows}

    def breakdown_for_tenant(self, db: Session, tenant_id: int) -> StorageUsageRead:
        sums = self._category_sums(db, tenant_id).get(tenant_id, {})
        total = sums.get("total", 0)
        known = sum(sums.get(key, 0) for key in _KNOWN_CATEGORY_KEYS)
        categories = [
            StorageCategoryUsage(key=key, label=CATEGORY_LABELS[key], bytes=sums.get(key, 0))
            for key in _KNOWN_CATEGORY_KEYS
        ]
        categories.append(StorageCategoryUsage(key="other", label=CATEGORY_LABELS["other"], bytes=max(total - known, 0)))
        tenant = db.get(Tenant, tenant_id)
        quota_bytes = tenant.storage_quota_bytes if tenant is not None else None
        return StorageUsageRead(total_bytes=total, quota_bytes=quota_bytes, categories=categories)

    def set_quota(self, db: Session, tenant_id: int, quota_bytes: int | None) -> Tenant | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        tenant.storage_quota_bytes = quota_bytes
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant
