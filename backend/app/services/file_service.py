from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.models import AppUser, GalleryImage, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolImage, StoredFile
from app.repositories.file_repository import ProtocolImageRepository, StoredFileRepository
from app.schemas.files import FileOverviewItem, StoredFileMetadata
from app.schemas.protocol import ProtocolImageRead
from app.services import public_id_service
from app.services.upload_pipeline import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_TOTAL_BYTES,
    PDF_MIME_TYPE,
    WORD_IMPORT_ALLOWED_MIME_TYPES,
    WORD_IMPORT_MIME_TYPE,
    _content_matches_mime,
    _sniff_image_mime,
    _sniff_word_import_mime,
    extract_image_files_from_zip,
    extract_word_import_files_from_zip,
    generate_thumbnail_bytes,
    ingest_file,
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
    Postgres is the one piece of state they all already share."""
    db.execute(text("SELECT pg_advisory_lock(:ns, :tenant_id)"), {"ns": _PROTOCOL_IMAGE_QUOTA_LOCK_NAMESPACE, "tenant_id": tenant_id})
    try:
        yield
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:ns, :tenant_id)"), {"ns": _PROTOCOL_IMAGE_QUOTA_LOCK_NAMESPACE, "tenant_id": tenant_id})


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
        thumbnail_bytes = generate_thumbnail_bytes(original_path.read_bytes())
        if thumbnail_bytes is None:
            return None

        Path(thumbnail_root).mkdir(parents=True, exist_ok=True)
        thumbnail_path = Path(thumbnail_root).resolve() / f"{stored_file.id}.jpg"
        thumbnail_path.write_bytes(thumbnail_bytes)
        stored_file.thumbnail_path = thumbnail_path.name
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
        )
        items: list[FileOverviewItem] = []
        for row in rows:
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
            items.append(
                FileOverviewItem(
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
                )
            )
        return items

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
    ) -> tuple[list[FileOverviewItem], list[str]]:
        """Persists a batch of images uploaded directly through the "Dateien"/"Fotos" gallery
        upload window (route already expanded any .zip into individual (filename, bytes)
        entries via extract_image_files_from_zip - only genuine images ever reach here). Runs
        the same upload_pipeline.ingest_file() every internal upload path shares: magic-byte
        content verification (never the client-supplied filename/Content-Type), a size cap, a
        checksum + tenant-wide perceptual-hash duplicate check (same "sieht aus wie ein bereits
        hochgeladenes Bild" warning as protocol images), and thumbnail generation for the
        "Fotos" grid. Scans the whole batch concurrently up front via scanner.scan_many()
        rather than one blocking scan_bytes() call per file. One bad file never aborts the
        whole batch - problems are collected into `errors` and returned alongside whatever did
        succeed."""
        self.ensure_storage()
        normalized_tags = _normalize_tags(tags)
        scan_statuses = await scanner.scan_many(
            [content for _filename, content in files], host=settings.clamav_host, port=settings.clamav_port
        )

        items: list[FileOverviewItem] = []
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
                    created_by=created_by,
                    tags=normalized_tags,
                    too_large_message=f"zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)",
                    unsupported_format_message="kein unterstütztes Bildformat",
                    infected_message="wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert",
                    stored_file_repository=self.stored_file_repository,
                )
            except HTTPException as exc:
                errors.append(f"{label}: {exc.detail}")
                continue

            stored_file = result.stored_file
            db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id, created_by=created_by))
            db.flush()

            if result.duplicate_warning is not None:
                errors.append(f"{label}: Hinweis - ähnelt einem bereits im Mandanten hochgeladenen Bild")

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
                )
            )

        db.commit()
        return items, errors

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
