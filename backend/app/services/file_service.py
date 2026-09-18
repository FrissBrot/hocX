from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.core.cycle_utils import get_cycle_year
from app.models import AppUser, Event, GalleryImage, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolImage, StoredFile
from app.models.entities import CycleConfig, GalleryUploadJob, PhotoAlbum, PhotoAlbumItem, PhotoAnalysisJob, SubmissionAssignment
from app.repositories.file_repository import ProtocolImageRepository, StoredFileRepository
from app.schemas.files import FileAlbumRef, FileOverviewItem, FileStats, PhotoAnalysisProgress, SimilarityGroup, StoredFileMetadata
from app.schemas.protocol import ProtocolImageRead
from app.services import public_id_service
from app.services.photo_quality import compute_quality_scores
from app.services.photo_similarity import MAX_GROUPING_IMAGES, GroupableImage, group_similar_images
from app.services.upload_pipeline import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_TOTAL_BYTES,
    PDF_MIME_TYPE,
    WORD_IMPORT_ALLOWED_MIME_TYPES,
    WORD_IMPORT_MIME_TYPE,
    _closest_perceptual_match,
    _compute_perceptual_hash,
    _content_matches_mime,
    _sniff_image_mime,
    _sniff_word_import_mime,
    extract_word_import_files_from_zip,
    generate_thumbnail_bytes,
    ingest_file,
    iter_gallery_zip_entries,
)

# Max number of tags a suggestion query returns to the frontend's autocomplete dropdown.
MAX_TAG_SUGGESTIONS = 50
# Hard cap on tags per file and on each tag's length - guards against a pathological client
# sending an unbounded array/strings into a jsonb column with a GIN index.
MAX_TAGS_PER_FILE = 30
MAX_TAG_LENGTH = 60

# Distinct namespace (paired with tenant_id as the advisory lock's two int32 keys) from
# the fixed single-bigint lock ids main.py's background loops use (202600xxx range).
_PROTOCOL_IMAGE_QUOTA_LOCK_NAMESPACE = 909100001


@contextmanager
def _tenant_protocol_image_upload_lock(db: Session, tenant_id: int) -> Iterator[None]:
    """Serializes the storage-quota check-then-write sequence in save_protocol_image per
    tenant (mirrors the abgabebox subapp's tenant_upload_lock, closing the same H12-class
    TOCTOU: two near-simultaneous uploads for the same tenant could otherwise both observe
    "under quota" before either has written its bytes). A Postgres advisory lock, not an
    in-process lock - this app runs multiple uvicorn workers (separate OS processes), and
    Postgres is the one piece of state they all already share.

    Transaction-scoped (pg_advisory_xact_lock), not session-scoped - Postgres releases it
    automatically when this Session's current transaction ends (commit or rollback), so
    there is no manual unlock call to get wrong. Audit fix, 2026-09-17: this used to be a
    session-scoped pg_advisory_lock paired with an explicit pg_advisory_unlock in a
    `finally`, but save_protocol_image calls db.commit() *inside* this locked block -
    Session.commit() checks the underlying DBAPI connection back into the pool, so the
    `finally`'s unlock could then run on a *different* physical connection than the one
    that acquired the lock. Postgres advisory-unlock is a silent no-op when the calling
    connection doesn't hold the lock, so the lock stayed held forever on the now-idle,
    pooled first connection - every later protocol-image upload for that tenant that
    landed on a different connection would then block on pg_advisory_lock indefinitely.
    The abgabebox sibling this was meant to mirror already used the transaction-scoped
    form for exactly this reason; this module just picked the wrong one of the two safe
    options."""
    db.execute(text("SELECT pg_advisory_xact_lock(:ns, :tenant_id)"), {"ns": _PROTOCOL_IMAGE_QUOTA_LOCK_NAMESPACE, "tenant_id": tenant_id})
    yield


# Phase 3: cap on how many images a single photo_analysis_job can queue. The worker
# processes one job at a time (see photo-analysis-worker/app/worker.py), so an
# unreasonably large job would monopolize it and starve every other tenant's queued jobs
# behind it - narrower than MAX_GROUPING_IMAGES since this work is genuinely slower
# per-image (face detection) even though it doesn't block a request the way Phase 2 does.
MAX_ANALYSIS_JOB_IMAGES = 2000


def _extract_image_metadata(content: bytes) -> tuple[int | None, int | None, datetime | None, str | None]:
    """(width, height, exif_taken_at, exif_camera) for the file-detail metadata panel.
    Deliberately does not read/return GPS EXIF data (present on some phone photos) - that's
    location data about where a user was, not something this feature needs to expose.
    Returns all-None for non-images or content PIL can't decode."""
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            taken_at: datetime | None = None
            camera: str | None = None
            try:
                exif = image.getexif()
                make = exif.get(271)
                model = exif.get(272)
                camera_parts = [str(p).strip() for p in (make, model) if p and str(p).strip()]
                camera = " ".join(camera_parts) or None
                exif_ifd = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
                raw_taken_at = exif_ifd.get(36867) or exif_ifd.get(36868) or exif.get(306)
                if raw_taken_at:
                    taken_at = datetime.strptime(str(raw_taken_at).strip(), "%Y:%m:%d %H:%M:%S")
            except Exception:
                pass
            return width, height, taken_at, camera
    except Exception:
        return None, None, None, None


def _normalize_tags(tags: list[str]) -> list[str]:
    """Trims/dedupes/caps a user-submitted tag list before it hits the JSONB column - same
    spirit as the trim-and-filter TagInput already does client-side, but enforced server-side
    since this is a real API input, not just a UI convenience."""
    seen: dict[str, None] = {}
    for raw in tags:
        tag = raw.strip()
        if not tag or len(tag) > MAX_TAG_LENGTH:
            continue
        seen.setdefault(tag, None)
        if len(seen) >= MAX_TAGS_PER_FILE:
            break
    return list(seen.keys())


def _safe_storage_path(storage_root: str, relative_path: str) -> Path:
    root = Path(storage_root).resolve()
    full = (root / relative_path).resolve()
    if not str(full).startswith(str(root) + "/") and full != root:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return full


class FileService:
    def __init__(
        self,
        stored_file_repository: StoredFileRepository | None = None,
        protocol_image_repository: ProtocolImageRepository | None = None,
    ) -> None:
        self.stored_file_repository = stored_file_repository or StoredFileRepository()
        self.protocol_image_repository = protocol_image_repository or ProtocolImageRepository()

    def ensure_storage(self) -> None:
        for path in [
            settings.storage_root,
            settings.export_root,
            settings.upload_root,
            settings.latex_template_root,
            settings.thumbnail_root,
            # Gallery-upload staging area (see upload_pipeline.stage_upload_to_disk) - must
            # stay under upload_root (the bind-mounted storage volume), never the process's
            # default tempfile location, which is RAM-backed tmpfs in the release deployment.
            Path(settings.upload_root) / "_staging" / "gallery",
        ]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def build_content_url(self, stored_file_public_id: uuid.UUID) -> str:
        return f"/api/stored-files/{stored_file_public_id}/content"

    def build_thumbnail_url(self, stored_file_public_id: uuid.UUID) -> str:
        return f"/api/stored-files/{stored_file_public_id}/thumbnail"

    def build_tags_url(self, stored_file_public_id: uuid.UUID) -> str:
        return f"/api/stored-files/{stored_file_public_id}/tags"

    def build_metadata_url(self, stored_file_public_id: uuid.UUID) -> str:
        return f"/api/stored-files/{stored_file_public_id}/metadata"

    def ensure_thumbnail(
        self, db: Session, stored_file: StoredFile, storage_root: str, thumbnail_root: str | None = None
    ) -> Path | None:
        """Returns the path to a small JPEG preview of stored_file's content, generating and
        persisting it on first request if none exists yet (covers files uploaded before this
        feature existed, and submission uploads written by abgabebox-backend's restricted DB
        role, which never sets thumbnail_path itself). None for non-images or files whose
        content PIL can't decode - callers fall back to the original in that case.

        Thumbnails live under thumbnail_root (a local-only directory, separate from
        storage_root) so that storage_root can be moved to network-attached storage without
        dragging previews along - see hocx storage-offload plan. Named by stored_file.id
        rather than mirroring the original's path, since storage_root differs between callers
        (tenant files vs. abgabebox submissions) but thumbnail_root is shared."""
        thumbnail_root = thumbnail_root or settings.thumbnail_root
        if not stored_file.mime_type or not stored_file.mime_type.startswith("image/"):
            return None
        if stored_file.thumbnail_path:
            existing = _safe_storage_path(thumbnail_root, stored_file.thumbnail_path)
            if existing.exists():
                return existing

        original_path = _safe_storage_path(storage_root, stored_file.storage_path)
        if not original_path.exists():
            return None
        generated = generate_thumbnail_bytes(original_path.read_bytes())
        if generated is None:
            return None
        thumbnail_bytes, width, height = generated

        Path(thumbnail_root).mkdir(parents=True, exist_ok=True)
        thumbnail_path = Path(thumbnail_root).resolve() / f"{stored_file.id}.jpg"
        thumbnail_path.write_bytes(thumbnail_bytes)
        stored_file.thumbnail_path = thumbnail_path.name
        stored_file.width = width
        stored_file.height = height
        db.add(stored_file)
        db.commit()
        return thumbnail_path

    def list_protocol_images(self, db: Session, protocol_element_block_id: int) -> list[ProtocolImageRead]:
        rows = self.protocol_image_repository.list_for_protocol_block(db, protocol_element_block_id)
        block_public_id = public_id_service.resolve_public_id(db, ProtocolElementBlock, protocol_element_block_id)
        return [
            ProtocolImageRead(
                id=row.ProtocolImage.public_id,
                protocol_element_block_id=block_public_id,
                stored_file_id=row.StoredFile.public_id,
                sort_index=row.ProtocolImage.sort_index,
                title=row.ProtocolImage.title,
                caption=row.ProtocolImage.caption,
                original_name=row.StoredFile.original_name,
                mime_type=row.StoredFile.mime_type,
                file_size_bytes=row.StoredFile.file_size_bytes,
                content_url=self.build_content_url(row.StoredFile.public_id),
            )
            for row in rows
        ]

    def list_tenant_files(
        self,
        db: Session,
        tenant_id: int,
        *,
        skip: int = 0,
        limit: int = 50,
        source: str | None = None,
        only_images: bool = False,
        exclude_images: bool = False,
        search: str | None = None,
        tags: list[str] | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        file_ids: list[uuid.UUID] | None = None,
        album_id: uuid.UUID | None = None,
    ) -> list[FileOverviewItem]:
        rows = self.stored_file_repository.list_tenant_files(
            db,
            tenant_id,
            skip=skip,
            limit=limit,
            source=source,
            only_images=only_images,
            exclude_images=exclude_images,
            search=search,
            tags=tags,
            sort_by=sort_by,
            sort_dir=sort_dir,
            file_ids=file_ids,
            album_id=album_id,
        )
        return [self._build_overview_item(row) for row in rows]

    def analysis_progress(self, db: Session, tenant_id: int) -> PhotoAnalysisProgress:
        """Backs the Fotos page's tenant-wide "Foto-Analyse läuft - X von Y Bildern
        bewertet" progress bar and the "Analyse läuft · N Bilder" pill."""
        counts = self.stored_file_repository.tenant_photo_analysis_progress(db, tenant_id)
        active_jobs = list(
            db.scalars(
                select(PhotoAnalysisJob).where(
                    PhotoAnalysisJob.tenant_id == tenant_id,
                    PhotoAnalysisJob.status.in_(["queued", "running"]),
                )
            )
        )
        active_job_image_count = sum(len(job.stored_file_ids) for job in active_jobs)
        return PhotoAnalysisProgress(
            total_images=counts.total,
            analyzed_images=counts.analyzed,
            pending_images=counts.total - counts.analyzed,
            active_jobs=len(active_jobs),
            active_job_image_count=active_job_image_count,
        )

    def file_stats(self, db: Session, tenant_id: int) -> FileStats:
        """Backs the Dateien page's Dokumente/Fotos/Speicher stat cards."""
        counts = self.stored_file_repository.tenant_file_stats(db, tenant_id)
        return FileStats(
            document_count=counts.document_count,
            photo_count=counts.photo_count,
            total_bytes=int(counts.total_bytes),
        )

    def attach_album_context(self, db: Session, tenant_id: int, items: list[FileOverviewItem]) -> None:
        """Fills item.albums (and, since is_best has no meaning outside an album, the
        unscoped item.is_best = "best-of in at least one album") for a page of items - one
        extra query per page, mirroring the album-scoped best-of lookup list_files already
        does when an album_id filter is given."""
        if not items:
            return
        items_by_id = {item.id: item for item in items}
        rows = db.execute(
            select(PhotoAlbumItem.file_id, PhotoAlbumItem.is_best, PhotoAlbum.id, PhotoAlbum.name, PhotoAlbum.kind)
            .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumItem.album_id)
            .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbumItem.file_id.in_(items_by_id.keys()))
        ).all()
        for file_id, is_best, album_id, album_name, album_kind in rows:
            item = items_by_id.get(file_id)
            if item is None:
                continue
            item.albums.append(FileAlbumRef(id=album_id, name=album_name, kind=album_kind, is_best=is_best))
        for item in items:
            if item.albums:
                item.is_best = any(album.is_best for album in item.albums)

    def _build_overview_item(self, row) -> FileOverviewItem:
        is_image = bool(row.mime_type and row.mime_type.startswith("image/"))
        if row.source == "submission_upload":
            content_url = f"/api/submission-uploads/{row.upload_public_id}/files/{row.public_id}/content"
            thumbnail_url = (
                f"/api/submission-uploads/{row.upload_public_id}/files/{row.public_id}/thumbnail" if is_image else None
            )
            tags_url = f"/api/submission-uploads/{row.upload_public_id}/files/{row.public_id}/tags"
            metadata_url = f"/api/submission-uploads/{row.upload_public_id}/files/{row.public_id}/metadata"
            ref_href = f"/submission-assignments/{row.ref_id}" if row.ref_id is not None else None
        elif row.source == "protocol_image":
            content_url = self.build_content_url(row.public_id)
            thumbnail_url = self.build_thumbnail_url(row.public_id) if is_image else None
            tags_url = self.build_tags_url(row.public_id)
            metadata_url = self.build_metadata_url(row.public_id)
            ref_href = f"/protocols/{row.ref_public_id}" if row.ref_public_id is not None else None
        else:  # word_import / gallery_upload - no dedicated per-document frontend route to link to
            content_url = self.build_content_url(row.public_id)
            thumbnail_url = self.build_thumbnail_url(row.public_id) if is_image else None
            tags_url = self.build_tags_url(row.public_id)
            metadata_url = self.build_metadata_url(row.public_id)
            ref_href = None
        return FileOverviewItem(
            id=row.public_id,
            original_name=row.original_name,
            mime_type=row.mime_type,
            file_size_bytes=row.file_size_bytes,
            created_at=row.created_at,
            source=row.source,
            is_image=is_image,
            content_url=content_url,
            thumbnail_url=thumbnail_url,
            tags_url=tags_url,
            metadata_url=metadata_url,
            ref_label=row.ref_label,
            ref_date=row.ref_date,
            ref_href=ref_href,
            tags=list(row.tags or []),
            origin_tag=row.origin_tag,
            sharpness_score=row.sharpness_score,
            exposure_score=row.exposure_score,
            face_quality_score=row.face_quality_score,
            face_analyzed_at=row.face_analyzed_at,
            width=row.width,
            height=row.height,
            group_date=row.group_date,
            context_label=row.context_label,
        )

    def group_similar_gallery_images(
        self,
        db: Session,
        tenant_id: int,
        *,
        source: str | None = None,
        search: str | None = None,
        tags: list[str] | None = None,
        file_ids: list[uuid.UUID] | None = None,
        min_size: int = 1,
    ) -> list[SimilarityGroup]:
        """Photo-culling Phase 2: clusters the tenant's images (same filters as list_tenant_files,
        always only_images) by perceptual-hash similarity and ranks each cluster by the Phase 1
        quality scores - see photo_similarity.py for why this can run synchronously instead of
        needing the async worker later phases will need. group_similar_images() also returns
        singleton "groups" (an image with nothing similar to it) per its own docstring;
        min_size lets a caller that only cares about actual near-duplicate series (the
        "Ähnliche" tab) filter those out without re-deriving the grouping itself."""
        rows = self.stored_file_repository.list_tenant_files(
            db,
            tenant_id,
            skip=0,
            limit=MAX_GROUPING_IMAGES + 1,
            source=source,
            only_images=True,
            search=search,
            tags=tags,
            file_ids=file_ids,
        )
        if len(rows) > MAX_GROUPING_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Zu viele Bilder für die Gruppierung ausgewählt (max. {MAX_GROUPING_IMAGES}) - Filter eingrenzen (z.B. Album, Tag oder Suche).",
            )

        rows_by_id = {row.id: row for row in rows}
        groupable = [
            GroupableImage(
                id=row.id,
                perceptual_hash=row.perceptual_hash,
                sharpness_score=row.sharpness_score,
                exposure_score=row.exposure_score,
                face_quality_score=row.face_quality_score,
            )
            for row in rows
        ]
        groups = group_similar_images(groupable)
        return [
            SimilarityGroup(
                best_id=rows_by_id[group[0].id].public_id,
                images=[self._build_overview_item(rows_by_id[image.id]) for image in group],
            )
            for group in groups
            if len(group) >= min_size
        ]

    def create_analysis_job(
        self,
        db: Session,
        tenant_id: int,
        *,
        source: str | None = None,
        search: str | None = None,
        tags: list[str] | None = None,
        file_ids: list[uuid.UUID] | None = None,
        requested_by: int | None = None,
    ) -> PhotoAnalysisJob:
        """Photo-culling Phase 3: queues the (filtered) images for photo-analysis-worker to
        score. Same filter shape as group_similar_gallery_images, but this only writes a
        queued row - the actual face-detection work happens out of process, later, in the
        separate worker container (see that container's README for why)."""
        rows = self.stored_file_repository.list_tenant_files(
            db,
            tenant_id,
            skip=0,
            limit=MAX_ANALYSIS_JOB_IMAGES + 1,
            source=source,
            only_images=True,
            search=search,
            tags=tags,
            file_ids=file_ids,
        )
        if len(rows) > MAX_ANALYSIS_JOB_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Zu viele Bilder für einen Analyse-Auftrag ausgewählt (max. {MAX_ANALYSIS_JOB_IMAGES}) - Filter eingrenzen (z.B. Album, Tag oder Suche).",
            )
        if not rows:
            raise HTTPException(status_code=400, detail="Keine Bilder für diesen Filter gefunden.")

        job = PhotoAnalysisJob(
            tenant_id=tenant_id,
            stored_file_ids=[row.id for row in rows],
            requested_by=requested_by,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def get_analysis_job(self, db: Session, tenant_id: int, job_id: uuid.UUID) -> PhotoAnalysisJob:
        job = db.get(PhotoAnalysisJob, job_id)
        if job is None or job.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Analyse-Auftrag nicht gefunden")
        return job

    def create_pending_analysis_jobs(self, db: Session) -> list[PhotoAnalysisJob]:
        """Automatic off-peak counterpart to the manual "Gesichtsqualität analysieren"
        button (create_analysis_job): one job per tenant that has at least one clean image
        not yet analyzed and no job already queued/running - called from main.py's
        photo_analysis_auto_queue_loop. Skips a tenant with an in-flight job rather than
        piling on a second one; it'll be picked up again next loop iteration once that job
        finishes and still leaves unanalyzed images.

        Filters on face_analyzed_at, not face_quality_score - the worker legitimately
        writes a NULL score when no face is detected, so face_quality_score IS NULL means
        either "not analyzed yet" or "analyzed, no face found"; using it here would
        re-queue every faceless photo forever."""
        tenants_with_active_jobs = set(
            db.scalars(select(PhotoAnalysisJob.tenant_id).where(PhotoAnalysisJob.status.in_(["queued", "running"])))
        )
        pending_tenant_ids = db.scalars(
            select(StoredFile.tenant_id)
            .where(
                StoredFile.mime_type.like("image/%"),
                StoredFile.scan_status == "clean",
                StoredFile.face_analyzed_at.is_(None),
            )
            .distinct()
        ).all()

        created: list[PhotoAnalysisJob] = []
        for tenant_id in pending_tenant_ids:
            if tenant_id in tenants_with_active_jobs:
                continue
            stored_file_ids = list(
                db.scalars(
                    select(StoredFile.id)
                    .where(
                        StoredFile.tenant_id == tenant_id,
                        StoredFile.mime_type.like("image/%"),
                        StoredFile.scan_status == "clean",
                        StoredFile.face_analyzed_at.is_(None),
                    )
                    .limit(MAX_ANALYSIS_JOB_IMAGES)
                )
            )
            if not stored_file_ids:
                continue
            job = PhotoAnalysisJob(tenant_id=tenant_id, stored_file_ids=stored_file_ids, requested_by=None)
            db.add(job)
            created.append(job)

        if created:
            db.commit()
            for job in created:
                db.refresh(job)
        return created

    def backfill_missing_quality_scores(self, db: Session, *, limit: int = MAX_ANALYSIS_JOB_IMAGES) -> int:
        """Phase 1 (sharpness_score/exposure_score) is computed inline for protocol-image
        and gallery uploads (see save_protocol_image/save_gallery_uploads above), but the
        abgabebox-backend submission-upload path never computes it - that service runs as
        the separate, minimally-privileged hocx_abgabebox role and doesn't import this
        module (see sql/baseline_schema.sql). Called from main.py's
        photo_quality_backfill_loop to fill it in afterwards, from here, for any clean image
        never yet attempted (quality_analyzed_at IS NULL) regardless of source. Returns the
        number of files updated.

        A file whose disk content is missing still gets quality_analyzed_at stamped (audit
        fix, 2026-09-17) even though no score could be computed - previously such a row
        was silently `continue`d past with both scores left NULL, so the exact same
        unfixable row matched this method's query and was re-attempted on every future
        tick, forever, same failure class as photo-analysis-worker's face-quality
        equivalent (see that worker's comment on writing a NULL score deliberately, for
        the same reason)."""
        pending = list(
            db.scalars(
                select(StoredFile)
                .where(
                    StoredFile.mime_type.like("image/%"),
                    StoredFile.scan_status == "clean",
                    StoredFile.quality_analyzed_at.is_(None),
                )
                .limit(limit)
            )
        )
        updated = 0
        for stored_file in pending:
            file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
            if file_path.exists():
                content = file_path.read_bytes()
                stored_file.sharpness_score, stored_file.exposure_score = compute_quality_scores(content)
                updated += 1
            stored_file.quality_analyzed_at = datetime.now(UTC)
        if pending:
            db.commit()
        return updated

    def list_distinct_tags(self, db: Session, tenant_id: int, *, query: str | None = None, limit: int = MAX_TAG_SUGGESTIONS) -> list[str]:
        """Every tag currently in use by this tenant's files (custom + auto origin tags),
        deduped and sorted, for the tag-filter/editor autocomplete."""
        rows = self.stored_file_repository.list_tag_sources(db, tenant_id)
        seen: set[str] = set()
        needle = query.strip().lower() if query else None
        for row in rows:
            for tag in [*(row.tags or []), row.origin_tag]:
                if not tag or tag in seen:
                    continue
                if needle and needle not in tag.lower():
                    continue
                seen.add(tag)
        return sorted(seen, key=str.lower)[:limit]

    def update_stored_file_tags(self, db: Session, stored_file: StoredFile, tags: list[str]) -> list[str]:
        normalized = _normalize_tags(tags)
        self.stored_file_repository.update_tags(db, stored_file, normalized)
        return normalized

    def get_stored_file_metadata(self, db: Session, stored_file: StoredFile, storage_root: str, tenant_id: int) -> StoredFileMetadata | None:
        row = self.stored_file_repository.get_file_overview_row(db, tenant_id, stored_file.id)
        if row is None:
            return None
        width = height = None
        exif_taken_at = None
        exif_camera = None
        if stored_file.mime_type and stored_file.mime_type.startswith("image/"):
            file_path = _safe_storage_path(storage_root, stored_file.storage_path)
            if file_path.exists():
                width, height, exif_taken_at, exif_camera = _extract_image_metadata(file_path.read_bytes())
        # created_by is NULL for files this backend never attributed to a logged-in user -
        # notably abgabebox submission uploads (written by an anonymous public submitter
        # through a separate restricted DB role that never sets this column) and any file
        # uploaded before its upload path started passing created_by through.
        uploaded_by_name = None
        if stored_file.created_by is not None:
            uploader = db.get(AppUser, stored_file.created_by)
            if uploader is not None:
                uploaded_by_name = uploader.display_name
        return StoredFileMetadata(
            id=stored_file.public_id,
            original_name=stored_file.original_name,
            mime_type=stored_file.mime_type,
            file_size_bytes=stored_file.file_size_bytes,
            created_at=stored_file.created_at,
            checksum_sha256=stored_file.checksum_sha256,
            source=row.source,
            ref_label=row.ref_label,
            ref_date=row.ref_date,
            tags=list(stored_file.tags or []),
            origin_tag=row.origin_tag,
            width=width,
            height=height,
            exif_taken_at=exif_taken_at,
            exif_camera=exif_camera,
            uploaded_by_name=uploaded_by_name,
        )

    async def save_protocol_image(
        self,
        db: Session,
        *,
        protocol_element_block: ProtocolElementBlock,
        file: UploadFile,
        title: str | None = None,
        caption: str | None = None,
        created_by: int | None = None,
    ) -> ProtocolImageRead:
        self.ensure_storage()

        mime = (file.content_type or "").split(";")[0].strip().lower()
        if mime not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type '{mime}'. Allowed: JPEG, PNG, GIF, WebP, BMP, TIFF")

        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
        if not _content_matches_mime(content, mime):
            raise HTTPException(status_code=400, detail="Dateiinhalt passt nicht zum angegebenen Bildformat")

        checksum = hashlib.sha256(content).hexdigest()
        existing_block_images = self.protocol_image_repository.list_for_protocol_block(db, protocol_element_block.id)
        if any(row.StoredFile.checksum_sha256 == checksum for row in existing_block_images):
            raise HTTPException(status_code=409, detail="Dieses Bild wurde bereits in diesen Block hochgeladen")

        # Unlike word-import documents and abgabebox uploads, protocol images were never
        # scanned at all (audit finding, 2026-08-25) - scan_status defaulted to "clean" in
        # the DB, so the image was treated as already-verified even though it never was.
        # scan_many() (not scan_bytes()) even for this single file: this method runs on the
        # request's event loop, and a direct scan_bytes() call would block the whole uvicorn
        # worker for every tenant until ClamAV answers (up to 30s on timeout).
        scan_status = (await scanner.scan_many([content], host=settings.clamav_host, port=settings.clamav_port))[0]

        tenant_id = self._resolve_tenant_id(db, protocol_element_block.id)

        # No per-tenant total quota existed at all before this fix (audit finding,
        # 2026-08-25) - only the per-file MAX_UPLOAD_BYTES check above. Quota check and
        # the write that changes what the next check sees (the StoredFile insert, flushed
        # but not committed until the very end of this method) both happen inside a
        # per-tenant advisory lock so two near-simultaneous uploads can't both pass the
        # check before either has committed - see _tenant_protocol_image_upload_lock.
        quota_bytes = settings.protocol_image_storage_quota_mb * 1024 * 1024
        with _tenant_protocol_image_upload_lock(db, tenant_id):
            current_bytes = int(
                db.scalar(
                    select(func.coalesce(func.sum(StoredFile.file_size_bytes), 0))
                    .join(ProtocolImage, ProtocolImage.stored_file_id == StoredFile.id)
                    .where(StoredFile.tenant_id == tenant_id)
                )
                or 0
            )
            if current_bytes + len(content) > quota_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Speicherlimit für Protokollbilder erreicht (max. {settings.protocol_image_storage_quota_mb} MB pro Mandant)",
                )

            result = ingest_file(
                db,
                tenant_id=tenant_id,
                content=content,
                original_filename=file.filename or "bild",
                scan_status=scan_status,
                sniff=lambda c: mime if _content_matches_mime(c, mime) else None,
                max_bytes=MAX_UPLOAD_BYTES,
                storage_subdir_parts=(f"tenant-{tenant_id}", f"block-{protocol_element_block.id}"),
                enable_perceptual_dedupe=True,
                enable_thumbnail=True,
                capture_quality_scores=True,
                created_by=created_by,
                stored_file_repository=self.stored_file_repository,
            )
            stored_file = result.stored_file

            protocol_image = ProtocolImage(
                protocol_element_block_id=protocol_element_block.id,
                stored_file_id=stored_file.id,
                sort_index=self.protocol_image_repository.next_sort_index(db, protocol_element_block.id),
                title=title,
                caption=caption,
            )
            protocol_image = self.protocol_image_repository.create(db, protocol_image)
            db.commit()

        return ProtocolImageRead(
            id=protocol_image.public_id,
            protocol_element_block_id=protocol_element_block.public_id,
            stored_file_id=stored_file.public_id,
            sort_index=protocol_image.sort_index,
            title=protocol_image.title,
            caption=protocol_image.caption,
            original_name=stored_file.original_name,
            mime_type=stored_file.mime_type,
            file_size_bytes=stored_file.file_size_bytes,
            content_url=self.build_content_url(stored_file.public_id),
            duplicate_warning=result.duplicate_warning,
        )

    async def save_gallery_uploads(
        self,
        db: Session,
        *,
        tenant_id: int,
        files: list[tuple[str, bytes]],
        tags: list[str],
        created_by: int | None,
        upload_event_id: int | None = None,
        upload_assignment: SubmissionAssignment | None = None,
        upload_element_ref: str | None = None,
        upload_element_label: str | None = None,
        upload_cycle_config: CycleConfig | None = None,
    ) -> tuple[list[FileOverviewItem], list[str]]:
        """Persists a batch of already-decoded (filename, bytes) images for the "Dateien"/
        "Fotos" gallery upload window - only genuine images (magic bytes, not filename)
        should ever reach here; a .zip's entries are the caller's job to expand first (see
        process_pending_gallery_upload_jobs/iter_gallery_zip_entries, which calls this once per small
        batch of extracted entries rather than once for a whole ZIP - keeps this method
        itself simple/synchronous-shaped and reusable as the plain bytes-in/items-out
        fixture helper several other services' tests already use it as). Runs the same
        upload_pipeline.ingest_file() every internal upload path shares: magic-byte
        content verification (never the client-supplied filename/Content-Type), a size cap, a
        checksum + tenant-wide perceptual-hash duplicate check (same "sieht aus wie ein bereits
        hochgeladenes Bild" warning as protocol images), and thumbnail generation for the
        "Fotos" grid. Scans the whole batch concurrently up front via scanner.scan_many()
        rather than one blocking scan_bytes() call per file. One bad file never aborts the
        whole batch - problems are collected into `errors` and returned alongside whatever did
        succeed.

        The upload_* kwargs are the optional Termin/Abgabe-Element/Zyklus target picker on
        the upload window - at most one of upload_event_id, (upload_assignment +
        upload_element_ref) or upload_cycle_config is ever set by a caller (see
        upload_gallery_images), and files land in the matching auto-album(s) once the whole
        batch is saved (see the end of this method). upload_cycle_config resolves each
        file's own EXIF capture date to a period independently (see the loop below) since a
        multi-file batch can span more than one Periode; the other two targets apply to
        every file in the batch alike."""
        self.ensure_storage()
        normalized_tags = _normalize_tags(tags)
        upload_event = db.get(Event, upload_event_id) if upload_event_id is not None else None
        scan_statuses = await scanner.scan_many(
            [content for _filename, content in files], host=settings.clamav_host, port=settings.clamav_port
        )

        # Fetched once and passed into every ingest_file() call below instead of letting
        # each call re-query it (audit fix, 2026-09-17 - see ingest_file's tenant_hashes
        # docstring) - ingest_file appends each newly-hashed file to this same list, so a
        # duplicate within this batch (not just against pre-existing uploads) still gets
        # caught for whichever file in the batch comes after it.
        tenant_hashes = self.stored_file_repository.list_tenant_image_hashes(db, tenant_id)

        items: list[FileOverviewItem] = []
        item_taken_at: dict[uuid.UUID, datetime | None] = {}
        errors: list[str] = []
        for (filename, content), scan_status in zip(files, scan_statuses):
            label = filename or "Bild"
            try:
                result = ingest_file(
                    db,
                    tenant_id=tenant_id,
                    content=content,
                    original_filename=filename or "bild",
                    scan_status=scan_status,
                    sniff=_sniff_image_mime,
                    max_bytes=MAX_UPLOAD_BYTES,
                    storage_subdir_parts=(f"tenant-{tenant_id}", "gallery"),
                    enable_perceptual_dedupe=True,
                    enable_thumbnail=True,
                    capture_quality_scores=True,
                    created_by=created_by,
                    tags=normalized_tags,
                    too_large_message=f"zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)",
                    unsupported_format_message="kein unterstütztes Bildformat",
                    infected_message="wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert",
                    stored_file_repository=self.stored_file_repository,
                    tenant_hashes=tenant_hashes,
                )
            except HTTPException as exc:
                errors.append(f"{label}: {exc.detail}")
                continue

            stored_file = result.stored_file
            db.add(
                GalleryImage(
                    tenant_id=tenant_id, stored_file_id=stored_file.id, event_id=upload_event_id, created_by=created_by
                )
            )
            db.flush()

            if result.duplicate_warning is not None:
                errors.append(f"{label}: Hinweis - ähnelt einem bereits im Mandanten hochgeladenen Bild")

            if upload_cycle_config is not None:
                _, _, taken_at, _ = _extract_image_metadata(content)
                item_taken_at[stored_file.public_id] = taken_at

            items.append(
                FileOverviewItem(
                    id=stored_file.public_id,
                    original_name=stored_file.original_name,
                    mime_type=stored_file.mime_type,
                    file_size_bytes=stored_file.file_size_bytes,
                    created_at=stored_file.created_at,
                    source="gallery_upload",
                    is_image=True,
                    content_url=self.build_content_url(stored_file.public_id),
                    thumbnail_url=self.build_thumbnail_url(stored_file.public_id),
                    tags_url=self.build_tags_url(stored_file.public_id),
                    metadata_url=self.build_metadata_url(stored_file.public_id),
                    ref_label="",
                    ref_date=None,
                    ref_href=None,
                    tags=list(stored_file.tags or []),
                    origin_tag="Direkt hochgeladen",
                    sharpness_score=stored_file.sharpness_score,
                    exposure_score=stored_file.exposure_score,
                    face_quality_score=stored_file.face_quality_score,
                    face_analyzed_at=stored_file.face_analyzed_at,
                    width=stored_file.width,
                    height=stored_file.height,
                    group_date=upload_event.event_date if upload_event is not None else stored_file.created_at.date(),
                    context_label=upload_event.title if upload_event is not None else None,
                )
            )

        db.commit()

        if items:
            # Deferred import: photo_album_service reuses SubmissionService's element-ref
            # helpers, and importing it at module level here would form an import cycle
            # (file_service -> photo_album_service -> submission_service -> file_service,
            # for submission_service's own _safe_storage_path import).
            from app.services import photo_album_service

            if upload_cycle_config is not None:
                # Group by cycle_year (a multi-file batch can span more than one Periode -
                # see the docstring), keeping one representative on_date per group so each
                # group can route through assign_uploaded_files' cycle_config/fallback_date
                # branch below instead of hand-rolling the same
                # get_or_create_cycle_album/add_items/commit/recompute_best_of sequence
                # here a second time (audit fix, 2026-09-17 - that branch had no caller at
                # all before this, while this method reimplemented its exact logic inline).
                groups: dict[int, list[uuid.UUID]] = {}
                representative_date_by_year: dict[int, date] = {}
                for item in items:
                    taken_at = item_taken_at.get(item.id)
                    on_date = taken_at.date() if taken_at is not None else date.today()
                    cycle_year = get_cycle_year(on_date, upload_cycle_config.reset_month, upload_cycle_config.reset_day)
                    groups.setdefault(cycle_year, []).append(item.id)
                    representative_date_by_year.setdefault(cycle_year, on_date)
                for cycle_year, file_ids in groups.items():
                    photo_album_service.assign_uploaded_files(
                        db,
                        self,
                        tenant_id=tenant_id,
                        stored_file_public_ids=file_ids,
                        cycle_config=upload_cycle_config,
                        fallback_date=representative_date_by_year[cycle_year],
                    )
            elif upload_event_id is not None or (upload_assignment is not None and upload_element_ref is not None):
                photo_album_service.assign_uploaded_files(
                    db,
                    self,
                    tenant_id=tenant_id,
                    stored_file_public_ids=[item.id for item in items],
                    event_id=upload_event_id,
                    assignment=upload_assignment,
                    element_ref=upload_element_ref,
                    element_label=upload_element_label,
                )

        return items, errors

    # Images per save_gallery_uploads() call while working through a gallery_upload_job -
    # bounds peak memory to roughly this many decoded images at once (each up to
    # MAX_UPLOAD_BYTES), independent of the job's total size, instead of the old route's
    # "decode the whole batch, then ingest all of it" shape.
    GALLERY_INGEST_BATCH_SIZE = 20

    def process_pending_gallery_upload_jobs(self, db: Session) -> None:
        """Background-loop task (see app/main.py's gallery_upload_ingest_loop): works
        through every currently-queued gallery_upload_job, oldest first, one at a time -
        called under run_advisory_locked_loop's cluster-wide lock, which doubles as the
        concurrency guard against two huge batches (each already up to GALLERY_ZIP_MAX_BYTES)
        being processed at once. Runs plain synchronously since run_advisory_locked_loop
        already offloads task(db) to its own thread via asyncio.to_thread -
        _run_gallery_upload_job is async (it awaits save_gallery_uploads' scan_many), so
        each job gets its own asyncio.run() here rather than this whole method being async
        itself."""
        while True:
            job = db.scalars(
                select(GalleryUploadJob).where(GalleryUploadJob.status == "queued").order_by(GalleryUploadJob.created_at).limit(1)
            ).first()
            if job is None:
                return
            job.status = "running"
            job.started_at = datetime.now(UTC)
            db.commit()
            try:
                asyncio.run(self._run_gallery_upload_job(db, job))
            except Exception as exc:
                db.rollback()
                db.refresh(job)
                # _run_gallery_upload_job already cleans up each staged file as it finishes
                # with it, but an unexpected failure can abort partway through job.staged_paths
                # - sweep whatever's left so a persistently-failing job doesn't leak staged
                # files on disk forever (missing_ok since most will already be gone).
                for relative_path in job.staged_paths:
                    (Path(settings.storage_root) / relative_path).unlink(missing_ok=True)
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(UTC)
                db.commit()
            else:
                job.status = "done"
                job.finished_at = datetime.now(UTC)
                db.commit()

    async def _run_gallery_upload_job(self, db: Session, job: GalleryUploadJob) -> None:
        upload_assignment = db.get(SubmissionAssignment, job.upload_assignment_id) if job.upload_assignment_id else None
        upload_cycle_config = db.get(CycleConfig, job.upload_cycle_config_id) if job.upload_cycle_config_id else None

        # total_files is None exactly when the batch contains at least one ZIP (see
        # upload_gallery_images) - its matching entries aren't known until drained, so this
        # job counts every file (ZIP entries and any plain images alongside it alike)
        # incrementally instead of trusting the upfront count a pure-images batch gets.
        counting_incrementally = job.total_files is None
        if counting_incrementally:
            job.total_files = 0
            db.commit()

        for relative_path, original_filename in zip(job.staged_paths, job.original_filenames):
            staged_path = Path(settings.storage_root) / relative_path
            try:
                if staged_path.suffix.lower() == ".zip":
                    await self._ingest_gallery_zip(
                        db, job, staged_path, upload_assignment=upload_assignment, upload_cycle_config=upload_cycle_config
                    )
                else:
                    await self._ingest_gallery_batch(
                        db,
                        job,
                        [(original_filename, staged_path.read_bytes())],
                        upload_assignment=upload_assignment,
                        upload_cycle_config=upload_cycle_config,
                    )
                    if counting_incrementally:
                        db.refresh(job)
                        job.total_files += 1
                        db.commit()
            finally:
                staged_path.unlink(missing_ok=True)

    async def _ingest_gallery_zip(
        self,
        db: Session,
        job: GalleryUploadJob,
        staged_path: Path,
        *,
        upload_assignment: SubmissionAssignment | None,
        upload_cycle_config: CycleConfig | None,
    ) -> None:
        """Streams staged_path via iter_gallery_zip_entries and ingests it in bounded
        batches - see GALLERY_INGEST_BATCH_SIZE. A queued job's total_files starts at 0 (see
        _run_gallery_upload_job's counting_incrementally) and grows here as matching entries
        are discovered, one batch at a time, rather than only being known once the whole ZIP
        is drained - otherwise the status bar's "X von Y" denominator would stay blank for
        this job's entire (potentially long) run, exactly for the large-ZIP case this job
        exists to handle well. Unlike the old in-memory extract_image_files_from_zip, the
        streaming generator itself has no way to know upfront whether the ZIP will turn out
        to contain zero images - saw_anything tracks that here instead, so a ZIP with no
        images and no per-entry problems still gets one clear error rather than silently
        importing nothing."""
        batch: list[tuple[str, bytes]] = []
        saw_anything = False
        for item in iter_gallery_zip_entries(staged_path):
            saw_anything = True
            if isinstance(item, str):
                job.errors = [*job.errors, item]
                db.commit()
                continue
            batch.append(item)
            if len(batch) >= self.GALLERY_INGEST_BATCH_SIZE:
                db.refresh(job)
                job.total_files += len(batch)
                db.commit()
                await self._ingest_gallery_batch(
                    db, job, batch, upload_assignment=upload_assignment, upload_cycle_config=upload_cycle_config
                )
                batch = []
        if batch:
            db.refresh(job)
            job.total_files += len(batch)
            db.commit()
            await self._ingest_gallery_batch(db, job, batch, upload_assignment=upload_assignment, upload_cycle_config=upload_cycle_config)
        if not saw_anything:
            db.refresh(job)
            job.errors = [*job.errors, "ZIP enthält keine Bilddateien"]
            db.commit()

    async def _ingest_gallery_batch(
        self,
        db: Session,
        job: GalleryUploadJob,
        batch: list[tuple[str, bytes]],
        *,
        upload_assignment: SubmissionAssignment | None,
        upload_cycle_config: CycleConfig | None,
    ) -> None:
        items, errors = await self.save_gallery_uploads(
            db,
            tenant_id=job.tenant_id,
            files=batch,
            tags=list(job.tags),
            created_by=job.requested_by,
            upload_event_id=job.upload_event_id,
            upload_assignment=upload_assignment,
            upload_element_ref=job.upload_element_ref,
            upload_element_label=job.upload_element_label,
            upload_cycle_config=upload_cycle_config,
        )
        db.refresh(job)
        job.imported_file_ids = [*job.imported_file_ids, *(str(item.id) for item in items)]
        job.errors = [*job.errors, *errors]
        job.processed_files += len(batch)
        db.commit()

    def save_word_import_document(
        self,
        db: Session,
        *,
        tenant_id: int,
        filename: str,
        content: bytes,
        created_by: int | None = None,
    ) -> StoredFile:
        """Stays a plain synchronous method (unlike save_protocol_image/save_gallery_uploads):
        its caller, WordImportQueueService.ingest(), itself runs inside run_in_threadpool()
        (see routes/word_import.py) because analyze() is a long, synchronous parse - there is
        no event loop to block here in the first place, so the plain blocking scanner.scan_bytes()
        is the right tool, not scan_many()."""
        self.ensure_storage()

        # SECURITY: scan before anything ever touches disk - an uploaded .docx/.pdf is
        # opened later by every writer/admin of the tenant via "Original-Dokument öffnen"
        # (GET /stored-files/{id}/content), so this is the point where malware smuggled
        # in a structurally-valid document must be caught. 'infected' is rejected outright
        # (nothing is written, no StoredFile row created). 'pending' (ClamAV unreachable)
        # still gets stored - fail-open, same convention as the abgabebox scanner - but is
        # blocked from download until the periodic rescan sweep resolves it, see
        # get_stored_file_content() in routes/files.py and rescan_pending_internal_files()
        # below.
        scan_status = scanner.scan_bytes(content, host=settings.clamav_host, port=settings.clamav_port)

        result = ingest_file(
            db,
            tenant_id=tenant_id,
            content=content,
            original_filename=filename,
            scan_status=scan_status,
            sniff=_sniff_word_import_mime,
            max_bytes=MAX_UPLOAD_BYTES,
            storage_subdir_parts=("word-imports", f"tenant-{tenant_id}"),
            enable_perceptual_dedupe=False,
            enable_thumbnail=False,
            created_by=created_by,
            too_large_message=f"Datei zu gross. Maximum {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
            unsupported_format_message="Datei ist keine gültige .docx- oder .pdf-Datei",
            infected_message=f"Datei '{filename}' wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert",
            stored_file_repository=self.stored_file_repository,
        )
        return result.stored_file

    def rescan_pending_internal_files(self, db: Session) -> dict:
        """Periodic sweep (see main.py's upload_pipeline_rescan_loop) for the three internal
        upload paths' StoredFile rows still marked 'pending' because ClamAV was unreachable at
        upload time - fail-open + rescan convention shared with the abgabebox scanner
        (submission_service.py's rescan_all_pending, handled by its own, separate
        abgabebox_rescan_loop since it also has to move files out of quarantine). None of the
        three internal paths ever quarantine into a separate directory (they're written to
        their final path directly), so a clean/infected verdict here is just a status flip, no
        file move needed."""
        pending = self.stored_file_repository.list_pending_internal_files(db)
        results = {"scanned": len(pending), "clean": 0, "infected": 0, "still_pending": 0}
        for stored_file in pending:
            file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
            result = scanner.scan_file(file_path, host=settings.clamav_host, port=settings.clamav_port)
            if result == "pending":
                results["still_pending"] += 1
                continue
            self.stored_file_repository.update_scan_status(db, stored_file, scan_status=result)
            results["clean" if result == "clean" else "infected"] += 1
        db.commit()
        return results

    def read_stored_file_bytes(self, stored_file: StoredFile) -> bytes:
        file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Datei fehlt im Speicher")
        return file_path.read_bytes()

    def delete_stored_file(self, db: Session, stored_file: StoredFile) -> None:
        # DB delete (flushed, so a constraint violation surfaces here) before the
        # irreversible filesystem unlink, not after - the previous order meant a failure
        # in the caller's own later commit left a DB row referencing an already-deleted
        # file (audit finding, 2026-08-25). stored_file_repository.delete() doesn't commit
        # itself (the caller controls that transaction boundary), so this can't guarantee
        # against a caller-side rollback recreating the opposite inconsistency (row
        # survives, file gone) - but flush() catches the far more common failure mode.
        file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        self.stored_file_repository.delete(db, stored_file)
        db.flush()
        if file_path.exists():
            file_path.unlink()
        if stored_file.thumbnail_path:
            thumbnail_path = _safe_storage_path(settings.thumbnail_root, stored_file.thumbnail_path)
            if thumbnail_path.exists():
                thumbnail_path.unlink()

    def delete_gallery_images(
        self, db: Session, tenant_id: int, file_ids: list[uuid.UUID]
    ) -> tuple[list[uuid.UUID], list[str]]:
        """Bulk hard-delete for the Fotos page's multi-select "Löschen" action and the
        "Ähnliche" tab's "Nur beste behalten" - gallery uploads only. Protocol images,
        word-import source documents and submission uploads each have their own deletion
        semantics this must not bypass (a dedicated permission-checked route, or a soft-
        delete owned by the abgabebox sync), so any id resolving to one of those sources is
        reported back as an error instead of deleted - same partial-success shape as
        save_gallery_uploads' (items, errors) return. Caller commits; PhotoAlbumItem rows
        for the deleted files must already be gone (see photo_album_service.
        drop_items_for_files) before this runs, since GalleryImage.stored_file_id is
        ON DELETE RESTRICT and photo_album_item.file_id has no FK at all to catch it."""
        rows = self.stored_file_repository.list_tenant_files(db, tenant_id, file_ids=file_ids, limit=max(len(file_ids), 1))
        rows_by_public_id = {row.public_id: row for row in rows}
        deleted: list[uuid.UUID] = []
        errors: list[str] = []
        for file_id in file_ids:
            row = rows_by_public_id.get(file_id)
            if row is None:
                errors.append(f"{file_id}: nicht gefunden")
                continue
            if row.source != "gallery_upload":
                errors.append(f"{row.original_name}: kann von hier aus nicht gelöscht werden (Quelle: {row.origin_tag})")
                continue
            stored_file = self.stored_file_repository.get(db, row.id)
            if stored_file is None:
                errors.append(f"{row.original_name}: nicht gefunden")
                continue
            db.execute(delete(GalleryImage).where(GalleryImage.stored_file_id == stored_file.id))
            self.delete_stored_file(db, stored_file)
            deleted.append(file_id)
        return deleted, errors

    def bulk_update_tags(
        self, db: Session, tenant_id: int, file_ids: list[uuid.UUID], add_tags: list[str], remove_tags: list[str]
    ) -> int:
        """Backs the Fotos page's multi-select "Tags hinzufügen" bulk action. Returns the
        number of files actually changed (a file already carrying every add_tag and none of
        remove_tags is left untouched)."""
        rows = self.stored_file_repository.list_tenant_files(db, tenant_id, file_ids=file_ids, limit=max(len(file_ids), 1))
        add = set(_normalize_tags(add_tags))
        remove = set(_normalize_tags(remove_tags))
        updated = 0
        for row in rows:
            stored_file = self.stored_file_repository.get(db, row.id)
            if stored_file is None:
                continue
            next_tags = _normalize_tags(list((set(stored_file.tags or []) | add) - remove))
            if next_tags != list(stored_file.tags or []):
                stored_file.tags = next_tags
                db.add(stored_file)
                updated += 1
        db.commit()
        return updated

    def get_stored_file(self, db: Session, stored_file_id: int, *, tenant_id: int | None = None) -> StoredFile | None:
        # tenant_id is optional only for callers that already did their own equivalent
        # check upstream (e.g. files.py's ensure_can_read_stored_file) - every other
        # caller should pass it. A bare PK lookup with no tenant filter at all was a
        # latent IDOR trap for any future caller that reused this without adding its own
        # check (audit finding, 2026-08-25); not currently reachable cross-tenant since
        # every existing caller already reaches this via a separately tenant-checked path.
        if tenant_id is not None:
            return self.stored_file_repository.get_for_tenant(db, stored_file_id, tenant_id)
        return self.stored_file_repository.get(db, stored_file_id)

    def delete_protocol_image(self, db: Session, image_id: int) -> bool:
        protocol_image = self.protocol_image_repository.get(db, image_id)
        if protocol_image is None:
            return False

        stored_file = self.stored_file_repository.get(db, protocol_image.stored_file_id)
        self.protocol_image_repository.delete(db, protocol_image)
        if stored_file is not None:
            file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
            if file_path.exists():
                file_path.unlink()
            self.stored_file_repository.delete(db, stored_file)
        db.commit()
        return True

    def _resolve_tenant_id(self, db: Session, protocol_element_block_id: int) -> int:
        protocol_element_block = db.get(ProtocolElementBlock, protocol_element_block_id)
        if protocol_element_block is None:
            raise ValueError("Protocol element block not found")
        protocol_element = db.get(ProtocolElement, protocol_element_block.protocol_element_id)
        if protocol_element is None:
            raise ValueError("Protocol element not found")
        protocol = db.get(Protocol, protocol_element.protocol_id)
        if protocol is None:
            raise ValueError("Protocol not found")
        return protocol.tenant_id
