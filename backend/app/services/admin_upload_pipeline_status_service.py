from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant
from app.repositories.file_repository import StoredFileRepository
from app.schemas.admin import (
    AbgabeboxQuarantineEntry,
    UploadPipelineFileRead,
    UploadPipelineOverview,
    UploadPipelineStatusPage,
    UploadPipelineSummaryEntry,
)

DEFAULT_PAGE_SIZE = 50


class AdminUploadPipelineStatusService:
    """Read access to the "Datei-Pipeline" admin overview: where every internally-tracked
    upload (protocol image, gallery upload, word import, abgabebox submission) currently
    stands - scan_status per file, aggregate counts, and abgabebox files still sitting in
    quarantine with no StoredFile row yet. Unscoped (cross-tenant) by design, same as
    AdminErrorLogService."""

    def __init__(self, stored_file_repository: StoredFileRepository | None = None) -> None:
        self.stored_file_repository = stored_file_repository or StoredFileRepository()

    def get_overview(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        source: str | None = None,
        scan_status: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> UploadPipelineOverview:
        summary_rows = self.stored_file_repository.count_pipeline_status_summary(db, tenant_id=tenant_id)
        summary = [
            UploadPipelineSummaryEntry(source=row.source, scan_status=row.scan_status, count=row.count)
            for row in summary_rows
        ]

        rows, total = self.stored_file_repository.list_pipeline_status(
            db, tenant_id=tenant_id, source=source, scan_status=scan_status, limit=limit, offset=offset
        )
        files = UploadPipelineStatusPage(
            items=[
                UploadPipelineFileRead(
                    id=row.public_id,
                    tenant_id=row.tenant_public_id,
                    tenant_name=row.tenant_name,
                    original_name=row.original_name,
                    mime_type=row.mime_type,
                    file_size_bytes=row.file_size_bytes,
                    source=row.source,
                    origin_tag=row.origin_tag,
                    scan_status=row.scan_status,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=total,
        )

        # Only relevant when the caller isn't filtering to one of the three internal
        # sources - a submission_upload file still mid-scan has no StoredFile row yet (see
        # abgabebox-backend's upload() route: the quarantine write happens before the
        # scan, the StoredFile insert only after), so it can never show up in `files`
        # above no matter how `source`/`scan_status` are set. This filesystem snapshot is
        # the only way to see it.
        quarantine = (
            self._scan_abgabebox_quarantine(db, tenant_id=tenant_id) if source in (None, "submission_upload") else []
        )
        return UploadPipelineOverview(summary=summary, files=files, abgabebox_quarantine=quarantine)

    def _scan_abgabebox_quarantine(self, db: Session, *, tenant_id: int | None) -> list[AbgabeboxQuarantineEntry]:
        """Live directory listing under abgabebox-backend's quarantine/tenant-<id>/
        assignment-<id>/<uuid>.<ext> (the main backend already mounts this storage
        read-write, see settings.abgabebox_storage_root / submission_service.py). Purely a
        filesystem read for display - not the authoritative source of anything, so a
        best-effort int() parse of the path segments (rather than _safe_storage_path, which
        exists to validate untrusted *input* paths, not to walk a trusted directory tree
        the app itself controls) is enough; a segment that doesn't parse just shows as None
        rather than failing the whole view."""
        quarantine_root = Path(settings.abgabebox_storage_root) / "quarantine"
        if not quarantine_root.is_dir():
            return []

        now = time.time()
        raw: list[tuple[int | None, int | None, str, int, float]] = []
        parsed_tenant_ids: set[int] = set()
        for path in quarantine_root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(quarantine_root).parts
            parsed_tenant_id = _parse_prefixed_int(parts[0], "tenant-") if len(parts) > 0 else None
            parsed_assignment_id = _parse_prefixed_int(parts[1], "assignment-") if len(parts) > 1 else None
            if tenant_id is not None and parsed_tenant_id != tenant_id:
                continue
            if parsed_tenant_id is not None:
                parsed_tenant_ids.add(parsed_tenant_id)
            try:
                stat = path.stat()
            except OSError:
                continue
            raw.append((parsed_tenant_id, parsed_assignment_id, path.name, stat.st_size, now - stat.st_mtime))

        tenant_names: dict[int, tuple[object, str]] = {}
        if parsed_tenant_ids:
            for tenant in db.query(Tenant).filter(Tenant.id.in_(parsed_tenant_ids)).all():
                tenant_names[tenant.id] = (tenant.public_id, tenant.name)

        entries = [
            AbgabeboxQuarantineEntry(
                tenant_id=tenant_names.get(parsed_tenant_id, (None, None))[0],
                tenant_name=tenant_names.get(parsed_tenant_id, (None, None))[1],
                assignment_id=parsed_assignment_id,
                file_name=file_name,
                age_seconds=int(age_seconds),
                file_size_bytes=file_size_bytes,
            )
            for parsed_tenant_id, parsed_assignment_id, file_name, file_size_bytes, age_seconds in raw
        ]
        entries.sort(key=lambda entry: entry.age_seconds, reverse=True)
        return entries


def _parse_prefixed_int(segment: str, prefix: str) -> int | None:
    if not segment.startswith(prefix):
        return None
    try:
        return int(segment[len(prefix) :])
    except ValueError:
        return None
