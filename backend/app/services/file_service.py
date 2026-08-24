from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import imagehash
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.models import AppUser, GalleryImage, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolImage, StoredFile
from app.repositories.file_repository import ProtocolImageRepository, StoredFileRepository
from app.schemas.files import FileOverviewItem, StoredFileMetadata
from app.schemas.protocol import ProtocolImageRead

# Max number of tags a suggestion query returns to the frontend's autocomplete dropdown.
MAX_TAG_SUGGESTIONS = 50
# Hard cap on tags per file and on each tag's length - guards against a pathological client
# sending an unbounded array/strings into a jsonb column with a GIN index.
MAX_TAGS_PER_FILE = 30
MAX_TAG_LENGTH = 60

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}
WORD_IMPORT_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME_TYPE = "application/pdf"
WORD_IMPORT_ALLOWED_MIME_TYPES = {WORD_IMPORT_MIME_TYPE, PDF_MIME_TYPE}
# ZIP-Uploads für den Import: Einträge werden nur im Arbeitsspeicher entpackt (nie auf
# Platte geschrieben) und einzeln per Magic-Bytes geprüft - Limits gegen Zip-Bomben.
MAX_ZIP_ENTRIES = 300
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB kombinierte entpackte Grösse
# Hamming-Distanz (von 64 Bit) zweier pHashes, ab der zwei Bilder als "wahrscheinlich
# dasselbe Motiv" gelten - empirischer Richtwert, bei Bedarf anhand echter Fehlalarme
# nachjustieren.
PERCEPTUAL_DUPLICATE_THRESHOLD = 5

# Vorschaubilder fuer die "Dateien"-Uebersicht: klein genug, dass ein Grid mit vielen
# Kacheln fluessig laedt, aber noch erkennbar - die Originaldatei wird nur beim Klick
# ins Lightbox (volle Aufloesung) nachgeladen.
THUMBNAIL_MAX_DIMENSION = 480
THUMBNAIL_JPEG_QUALITY = 78


# SECURITY: the client-sent Content-Type header (file.content_type) is fully attacker
# controlled and must never be trusted on its own - a file with a forged image mime type
# could smuggle arbitrary content into storage. Check the actual file signature (magic
# bytes) against the claimed mime type before persisting anything.
def _content_matches_mime(content: bytes, mime: str) -> bool:
    head = content[:16]
    if mime == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return head.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if mime == "image/bmp":
        return head.startswith(b"BM")
    if mime == "image/tiff":
        return head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")
    if mime == WORD_IMPORT_MIME_TYPE:
        return head.startswith(b"PK\x03\x04")  # .docx is a ZIP archive
    if mime == PDF_MIME_TYPE:
        return head.startswith(b"%PDF-")
    return False


def _sniff_word_import_mime(content: bytes) -> str | None:
    """Determines the real file type from content bytes alone (never the client-supplied
    filename/Content-Type, see _content_matches_mime above) - returns None for anything
    that isn't one of the two formats the word-import tool understands."""
    for mime in WORD_IMPORT_ALLOWED_MIME_TYPES:
        if _content_matches_mime(content, mime):
            return mime
    return None


def _sniff_image_mime(content: bytes) -> str | None:
    """Same idea as _sniff_word_import_mime, for the gallery upload window - returns None
    for anything whose magic bytes don't match one of ALLOWED_IMAGE_MIME_TYPES."""
    for mime in ALLOWED_IMAGE_MIME_TYPES:
        if _content_matches_mime(content, mime):
            return mime
    return None


def _extract_matching_files_from_zip(
    content: bytes, *, sniff: Callable[[bytes], str | None], empty_message: str
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Unpacks a ZIP upload entirely in memory: only entries `sniff` recognizes by magic
    bytes (never the entry name) are kept and returned. Everything else (folders, junk like
    __MACOSX/.DS_Store, files of the wrong type) is silently skipped - nothing from the
    archive other than the matched entries ever touches disk, so there is nothing left to
    clean up afterwards. Entry count/size are capped to guard against zip bombs (declared,
    not actual, size - sufficient here since uploads require an authenticated writer, not
    an anonymous endpoint). Shared by extract_word_import_files_from_zip and
    extract_image_files_from_zip below - only what counts as a match differs."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return [], ["ZIP-Datei ist beschädigt oder ungültig"]

    entries = [info for info in archive.infolist() if not info.is_dir()]
    matched: list[tuple[str, bytes]] = []
    notes: list[str] = []
    total_bytes = 0
    for info in entries[:MAX_ZIP_ENTRIES]:
        name = Path(info.filename).name
        if not name or name.startswith("."):
            continue
        if info.file_size > MAX_UPLOAD_BYTES:
            notes.append(f"{name}: zu gross, übersprungen")
            continue
        total_bytes += info.file_size
        if total_bytes > MAX_ZIP_TOTAL_BYTES:
            notes.append("ZIP-Inhalt zu gross - restliche Dateien wurden ignoriert")
            break
        entry_bytes = archive.read(info)
        if sniff(entry_bytes) is None:
            continue
        matched.append((name, entry_bytes))

    if len(entries) > MAX_ZIP_ENTRIES:
        notes.append(f"ZIP enthält mehr als {MAX_ZIP_ENTRIES} Dateien - restliche wurden ignoriert")
    if not matched and not notes:
        notes.append(empty_message)
    return matched, notes


def extract_word_import_files_from_zip(content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """ZIP upload for the word-import queue - keeps only entries that are genuinely a .docx
    or .pdf, see _extract_matching_files_from_zip above."""
    return _extract_matching_files_from_zip(
        content, sniff=_sniff_word_import_mime, empty_message="ZIP enthält keine Word- oder PDF-Dateien"
    )


def extract_image_files_from_zip(content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """ZIP upload for the gallery upload window - keeps only entries that are genuinely an
    image, see _extract_matching_files_from_zip above."""
    return _extract_matching_files_from_zip(
        content, sniff=_sniff_image_mime, empty_message="ZIP enthält keine Bilddateien"
    )


def _compute_perceptual_hash(content: bytes, mime: str) -> str | None:
    """DCT-based perceptual hash (pHash) for the tenant-wide "sieht aus wie ein bereits
    hochgeladenes Bild"-Warnung. Returns None for non-image mime types or content PIL can't
    decode (e.g. a truncated file that still happened to pass the magic-byte check)."""
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            return str(imagehash.phash(image))
    except Exception:
        return None


def _generate_thumbnail_bytes(content: bytes) -> bytes | None:
    """Downscaled JPEG preview for the "Dateien" grid. Returns None for content PIL can't
    decode (e.g. a truncated file that still passed the magic-byte check) - callers fall
    back to serving/linking the original in that case."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)  # respect camera rotation metadata
            image.thumbnail((THUMBNAIL_MAX_DIMENSION, THUMBNAIL_MAX_DIMENSION))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
            return buffer.getvalue()
    except Exception:
        return None


def _extract_image_metadata(content: bytes) -> tuple[int | None, int | None, datetime | None, str | None]:
    """(width, height, exif_taken_at, exif_camera) for the file-detail metadata panel.
    Deliberately does not read/return GPS EXIF data (present on some phone photos) - that's
    location data about where a user was, not something this feature needs to expose.
    Returns all-None for non-images or content PIL can't decode."""
    try:
        with Image.open(io.BytesIO(content)) as image:
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


def _closest_perceptual_match(perceptual_hash: str | None, candidates: list[tuple[int, str]]) -> int | None:
    """Returns the stored_file_id of the closest candidate within PERCEPTUAL_DUPLICATE_THRESHOLD,
    or None if there's no hash to compare or nothing close enough."""
    if perceptual_hash is None:
        return None
    this_hash = imagehash.hex_to_hash(perceptual_hash)
    best_id: int | None = None
    best_distance = PERCEPTUAL_DUPLICATE_THRESHOLD + 1
    for candidate_id, candidate_hash in candidates:
        distance = this_hash - imagehash.hex_to_hash(candidate_hash)
        if distance <= PERCEPTUAL_DUPLICATE_THRESHOLD and distance < best_distance:
            best_id, best_distance = candidate_id, distance
    return best_id


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

    def build_content_url(self, stored_file_id: int) -> str:
        return f"/api/stored-files/{stored_file_id}/content"

    def build_thumbnail_url(self, stored_file_id: int) -> str:
        return f"/api/stored-files/{stored_file_id}/thumbnail"

    def build_tags_url(self, stored_file_id: int) -> str:
        return f"/api/stored-files/{stored_file_id}/tags"

    def build_metadata_url(self, stored_file_id: int) -> str:
        return f"/api/stored-files/{stored_file_id}/metadata"

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
        thumbnail_bytes = _generate_thumbnail_bytes(original_path.read_bytes())
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
        return [
            ProtocolImageRead(
                id=row.ProtocolImage.id,
                protocol_element_block_id=row.ProtocolImage.protocol_element_block_id,
                stored_file_id=row.ProtocolImage.stored_file_id,
                sort_index=row.ProtocolImage.sort_index,
                title=row.ProtocolImage.title,
                caption=row.ProtocolImage.caption,
                original_name=row.StoredFile.original_name,
                mime_type=row.StoredFile.mime_type,
                file_size_bytes=row.StoredFile.file_size_bytes,
                content_url=self.build_content_url(row.StoredFile.id),
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
        search: str | None = None,
        tags: list[str] | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> list[FileOverviewItem]:
        rows = self.stored_file_repository.list_tenant_files(
            db,
            tenant_id,
            skip=skip,
            limit=limit,
            source=source,
            only_images=only_images,
            search=search,
            tags=tags,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        items: list[FileOverviewItem] = []
        for row in rows:
            is_image = bool(row.mime_type and row.mime_type.startswith("image/"))
            if row.source == "submission_upload":
                content_url = f"/api/submission-uploads/{row.upload_id}/files/{row.id}/content"
                thumbnail_url = f"/api/submission-uploads/{row.upload_id}/files/{row.id}/thumbnail" if is_image else None
                tags_url = f"/api/submission-uploads/{row.upload_id}/files/{row.id}/tags"
                metadata_url = f"/api/submission-uploads/{row.upload_id}/files/{row.id}/metadata"
                ref_href = f"/submission-assignments/{row.ref_id}" if row.ref_id is not None else None
            elif row.source == "protocol_image":
                content_url = self.build_content_url(row.id)
                thumbnail_url = self.build_thumbnail_url(row.id) if is_image else None
                tags_url = self.build_tags_url(row.id)
                metadata_url = self.build_metadata_url(row.id)
                ref_href = f"/protocols/{row.ref_id}" if row.ref_id is not None else None
            else:  # word_import / gallery_upload - no dedicated per-document frontend route to link to
                content_url = self.build_content_url(row.id)
                thumbnail_url = self.build_thumbnail_url(row.id) if is_image else None
                tags_url = self.build_tags_url(row.id)
                metadata_url = self.build_metadata_url(row.id)
                ref_href = None
            items.append(
                FileOverviewItem(
                    id=row.id,
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
            id=stored_file.id,
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

        suffix = Path(file.filename or "").suffix.lower() or ".bin"
        tenant_id = self._resolve_tenant_id(db, protocol_element_block.id)
        storage_dir = Path(settings.upload_root) / f"tenant-{tenant_id}" / f"block-{protocol_element_block.id}"
        storage_dir.mkdir(parents=True, exist_ok=True)
        generated_name = f"{uuid4().hex}{suffix}"
        target_path = storage_dir / generated_name

        perceptual_hash = _compute_perceptual_hash(content, mime)
        duplicate_warning: str | None = None
        if perceptual_hash is not None:
            tenant_hashes = self.stored_file_repository.list_tenant_image_hashes(db, tenant_id)
            if _closest_perceptual_match(perceptual_hash, tenant_hashes) is not None:
                duplicate_warning = "Hinweis: Dieses Bild ähnelt einem bereits im Mandanten hochgeladenen Bild."

        target_path.write_bytes(content)

        relative_path = target_path.relative_to(settings.storage_root)
        stored_file = StoredFile(
            tenant_id=tenant_id,
            original_name=file.filename or generated_name,
            mime_type=mime,
            storage_path=str(relative_path),
            latex_path=None,
            file_size_bytes=len(content),
            checksum_sha256=checksum,
            perceptual_hash=perceptual_hash,
            thumbnail_path=None,
            created_by=created_by,
        )
        stored_file = self.stored_file_repository.create(db, stored_file)

        # Thumbnail is keyed by stored_file.id (see ensure_thumbnail), so it's generated after
        # the insert/flush above instead of before it.
        thumbnail_bytes = _generate_thumbnail_bytes(content)
        if thumbnail_bytes is not None:
            thumbnail_root = Path(settings.thumbnail_root)
            thumbnail_root.mkdir(parents=True, exist_ok=True)
            thumbnail_target_path = thumbnail_root.resolve() / f"{stored_file.id}.jpg"
            thumbnail_target_path.write_bytes(thumbnail_bytes)
            stored_file.thumbnail_path = thumbnail_target_path.name

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
            id=protocol_image.id,
            protocol_element_block_id=protocol_image.protocol_element_block_id,
            stored_file_id=protocol_image.stored_file_id,
            sort_index=protocol_image.sort_index,
            title=protocol_image.title,
            caption=protocol_image.caption,
            original_name=stored_file.original_name,
            mime_type=stored_file.mime_type,
            file_size_bytes=stored_file.file_size_bytes,
            content_url=self.build_content_url(stored_file.id),
            duplicate_warning=duplicate_warning,
        )

    def save_gallery_uploads(
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
        the same pipeline as every other upload path in this file: magic-byte content
        verification (never the client-supplied filename/Content-Type), a size cap, a ClamAV
        scan before anything is written to disk (see save_word_import_document's SECURITY
        comment - same reasoning applies here, these files are served back to every
        writer/admin of the tenant), a checksum + tenant-wide perceptual-hash duplicate check
        (same "sieht aus wie ein bereits hochgeladenes Bild" warning as protocol images), and
        thumbnail generation for the "Fotos" grid. One bad file never aborts the whole batch -
        problems are collected into `errors` and returned alongside whatever did succeed."""
        self.ensure_storage()
        normalized_tags = _normalize_tags(tags)
        storage_dir = Path(settings.upload_root) / f"tenant-{tenant_id}" / "gallery"
        storage_dir.mkdir(parents=True, exist_ok=True)
        tenant_hashes = self.stored_file_repository.list_tenant_image_hashes(db, tenant_id)

        items: list[FileOverviewItem] = []
        errors: list[str] = []
        for filename, content in files:
            label = filename or "Bild"
            if len(content) > MAX_UPLOAD_BYTES:
                errors.append(f"{label}: zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
                continue
            mime = _sniff_image_mime(content)
            if mime is None:
                errors.append(f"{label}: kein unterstütztes Bildformat")
                continue

            scan_status = scanner.scan_bytes(content, host=settings.clamav_host, port=settings.clamav_port)
            if scan_status == "infected":
                errors.append(f"{label}: wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert")
                continue

            checksum = hashlib.sha256(content).hexdigest()
            perceptual_hash = _compute_perceptual_hash(content, mime)
            duplicate_id = _closest_perceptual_match(perceptual_hash, tenant_hashes)

            suffix = Path(filename).suffix.lower() or ".bin"
            target_path = storage_dir / f"{uuid4().hex}{suffix}"
            target_path.write_bytes(content)
            relative_path = target_path.relative_to(settings.storage_root)

            stored_file = StoredFile(
                tenant_id=tenant_id,
                original_name=filename or target_path.name,
                mime_type=mime,
                storage_path=str(relative_path),
                file_size_bytes=len(content),
                checksum_sha256=checksum,
                perceptual_hash=perceptual_hash,
                tags=normalized_tags,
                created_by=created_by,
                scan_status=scan_status,
            )
            stored_file = self.stored_file_repository.create(db, stored_file)

            thumbnail_bytes = _generate_thumbnail_bytes(content)
            if thumbnail_bytes is not None:
                thumbnail_root = Path(settings.thumbnail_root)
                thumbnail_root.mkdir(parents=True, exist_ok=True)
                thumbnail_target_path = thumbnail_root.resolve() / f"{stored_file.id}.jpg"
                thumbnail_target_path.write_bytes(thumbnail_bytes)
                stored_file.thumbnail_path = thumbnail_target_path.name

            db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id, created_by=created_by))
            db.flush()

            if perceptual_hash is not None:
                tenant_hashes.append((stored_file.id, perceptual_hash))
            if duplicate_id is not None:
                errors.append(f"{label}: Hinweis - ähnelt einem bereits im Mandanten hochgeladenen Bild")

            items.append(
                FileOverviewItem(
                    id=stored_file.id,
                    original_name=stored_file.original_name,
                    mime_type=stored_file.mime_type,
                    file_size_bytes=stored_file.file_size_bytes,
                    created_at=stored_file.created_at,
                    source="gallery_upload",
                    is_image=True,
                    content_url=self.build_content_url(stored_file.id),
                    thumbnail_url=self.build_thumbnail_url(stored_file.id),
                    tags_url=self.build_tags_url(stored_file.id),
                    metadata_url=self.build_metadata_url(stored_file.id),
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
        self.ensure_storage()

        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
        mime = _sniff_word_import_mime(content)
        if mime is None:
            raise HTTPException(status_code=400, detail="Datei ist keine gültige .docx- oder .pdf-Datei")

        # SECURITY: scan before anything ever touches disk - an uploaded .docx/.pdf is
        # opened later by every writer/admin of the tenant via "Original-Dokument öffnen"
        # (GET /stored-files/{id}/content), so this is the point where malware smuggled
        # in a structurally-valid document must be caught. 'infected' is rejected outright
        # (nothing is written, no StoredFile row created). 'pending' (ClamAV unreachable)
        # still gets stored - fail-open, same convention as the abgabebox scanner - but is
        # blocked from download until the periodic rescan sweep resolves it, see
        # get_stored_file_content() in routes/files.py and rescan_pending_word_import_files()
        # below.
        scan_status = scanner.scan_bytes(content, host=settings.clamav_host, port=settings.clamav_port)
        if scan_status == "infected":
            raise HTTPException(status_code=400, detail=f"Datei '{filename}' wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert")

        suffix = ".pdf" if mime == PDF_MIME_TYPE else ".docx"
        storage_dir = Path(settings.upload_root) / "word-imports" / f"tenant-{tenant_id}"
        storage_dir.mkdir(parents=True, exist_ok=True)
        target_path = storage_dir / f"{uuid4().hex}{suffix}"

        checksum = hashlib.sha256(content).hexdigest()
        target_path.write_bytes(content)

        relative_path = target_path.relative_to(settings.storage_root)
        stored_file = StoredFile(
            tenant_id=tenant_id,
            original_name=filename,
            mime_type=mime,
            storage_path=str(relative_path),
            latex_path=None,
            file_size_bytes=len(content),
            checksum_sha256=checksum,
            created_by=created_by,
            scan_status=scan_status,
        )
        return self.stored_file_repository.create(db, stored_file)

    def rescan_pending_word_import_files(self, db: Session) -> dict:
        """Periodic sweep (see main.py's word_import_rescan_loop) for word-import
        StoredFile rows still marked 'pending' because ClamAV was unreachable at upload
        time - same fail-open + rescan convention as the abgabebox scanner
        (submission_service.py's rescan_all_pending), but simpler here: word-import files
        are never quarantined into a separate directory (they're written to their final
        path directly, see save_word_import_document), so a clean/infected verdict is
        just a status flip, no file move needed."""
        pending = self.stored_file_repository.list_pending_word_import_files(db)
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

    def rescan_pending_gallery_uploads(self, db: Session) -> dict:
        """Periodic sweep (see main.py's gallery_upload_rescan_loop) for gallery-upload
        StoredFile rows still marked 'pending' because ClamAV was unreachable at upload
        time - same convention as rescan_pending_word_import_files above."""
        pending = self.stored_file_repository.list_pending_gallery_upload_files(db)
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
        file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        if file_path.exists():
            file_path.unlink()
        if stored_file.thumbnail_path:
            thumbnail_path = _safe_storage_path(settings.thumbnail_root, stored_file.thumbnail_path)
            if thumbnail_path.exists():
                thumbnail_path.unlink()
        self.stored_file_repository.delete(db, stored_file)

    def get_stored_file(self, db: Session, stored_file_id: int) -> StoredFile | None:
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
