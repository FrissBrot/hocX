from __future__ import annotations

from sqlalchemy import func, select
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
    "protocol_image": "Protokoll-Bilder",
    "word_import": "Word-Import-Dateien",
    "submission_upload": "Abgabebox-Uploads",
    "gallery_upload": "Galerie-Uploads",
    "export": "PDF-/LaTeX-Exporte",
    "other": "Sonstiges",
}

# Order mirrors the join branches below, "other" always last.
_KNOWN_CATEGORY_KEYS = ("protocol_image", "word_import", "submission_upload", "gallery_upload", "export")


class StorageService:
    """Computes per-tenant disk usage from `stored_file.file_size_bytes`, broken down by
    which feature produced the file. The three main categories mirror
    StoredFileRepository._files_overview_branches (protocol_image/word_import/
    submission_upload); "export" adds protocol_export_cache, which that "Dateien" overview
    deliberately excludes (see file_repository.py) because a generated PDF isn't something a
    user "hochgeladen" hat - but it still occupies real disk space and belongs in a storage
    report. Everything else - tenant-import/-clone artifacts, orphaned rows, the tenant logo
    (a raw path on Tenant, not a stored_file row at all) - falls into "other" so total always
    reconciles with SUM(file_size_bytes), the number that actually matters for a quota check.
    """

    def _category_sums(self, db: Session, tenant_id: int | None) -> dict[int, dict[str, int]]:
        """tenant_id=None sums across every tenant at once (admin list), otherwise scoped to one."""
        totals: dict[int, dict[str, int]] = {}

        def add(rows, key: str) -> None:
            for row_tenant_id, total in rows:
                totals.setdefault(row_tenant_id, {})[key] = int(total or 0)

        def scoped(query):
            return query if tenant_id is None else query.where(StoredFile.tenant_id == tenant_id)

        joins: dict[str, type] = {
            "protocol_image": ProtocolImage,
            "word_import": WordImportDocument,
            "gallery_upload": GalleryImage,
        }
        for key, model in joins.items():
            query = scoped(
                select(StoredFile.tenant_id, func.coalesce(func.sum(StoredFile.file_size_bytes), 0))
                .select_from(StoredFile)
                .join(model, model.stored_file_id == StoredFile.id)
                .group_by(StoredFile.tenant_id)
            )
            add(db.execute(query).all(), key)

        submission_query = scoped(
            select(StoredFile.tenant_id, func.coalesce(func.sum(StoredFile.file_size_bytes), 0))
            .select_from(StoredFile)
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .group_by(StoredFile.tenant_id)
        )
        add(db.execute(submission_query).all(), "submission_upload")

        export_query = scoped(
            select(StoredFile.tenant_id, func.coalesce(func.sum(StoredFile.file_size_bytes), 0))
            .select_from(StoredFile)
            .join(ProtocolExportCache, ProtocolExportCache.generated_file_id == StoredFile.id)
            .group_by(StoredFile.tenant_id)
        )
        add(db.execute(export_query).all(), "export")

        total_query = scoped(
            select(StoredFile.tenant_id, func.coalesce(func.sum(StoredFile.file_size_bytes), 0)).group_by(
                StoredFile.tenant_id
            )
        )
        add(db.execute(total_query).all(), "total")

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
