"""Shared core of every internal (non-abgabebox) upload path: protocol images, gallery
uploads, word-import documents. Each of the three FileService.save_* methods differs only in
where it decides to write the file, whether it wants perceptual-hash dedupe/a thumbnail, and
what its own caller-specific pre-checks are (protocol images check an exact per-block
duplicate before scanning; nothing else does) - everything past "I have validated,
already-scanned bytes and know where they go" is identical, and lives here as ingest_file().

Deliberately NOT shared with abgabebox-backend (see the upload-pipeline unification plan) -
that service stays fully isolated behind its own restricted Postgres role and never imports
main-backend code, so this module has no dependents there.

scan_status is always passed in by the caller rather than computed here: save_protocol_image
and save_gallery_uploads run on the request's event loop and need the non-blocking
scanner.scan_many() (awaited before calling ingest_file); save_word_import_document runs
inside a run_in_threadpool() worker thread with no event loop of its own and calls the plain
blocking scanner.scan_bytes() directly. Keeping the scan itself out of ingest_file lets it stay
a plain synchronous function usable from both contexts, instead of forcing a sync/async bridge
(e.g. asyncio.run()) onto the already-threadpooled word-import path for no benefit."""

from __future__ import annotations

import hashlib
import io
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import imagehash
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageChops, ImageOps
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import StoredFile, Tenant
from app.repositories.file_repository import StoredFileRepository
from app.services.photo_quality import compute_quality_scores

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

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# ZIP-Uploads (Galerie/Word-Import): Einträge werden nur im Arbeitsspeicher entpackt (nie auf
# Platte geschrieben) und einzeln per Magic-Bytes geprüft - Limits gegen Zip-Bomben.
MAX_ZIP_ENTRIES = 300
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB kombinierte entpackte Grösse

# Galerie-ZIPs laufen (anders als Word-Import) nicht mehr inline im Request, sondern als
# gallery_upload_job im Hintergrund (siehe FileService.process_pending_gallery_upload_jobs) und
# werden Eintrag fuer Eintrag von der bereits auf Platte gestagten ZIP-Datei gelesen (siehe
# iter_gallery_zip_entries unten) statt komplett im Arbeitsspeicher zu liegen - deshalb
# koennen diese beiden Limits deutlich grosszuegiger sein als MAX_ZIP_TOTAL_BYTES/
# MAX_ZIP_ENTRIES oben, ohne den frueheren In-Memory-Speicherdruck zurueckzubringen.
GALLERY_ZIP_MAX_BYTES = 5 * 1024**3  # 5 GiB kombinierte entpackte Grösse
GALLERY_ZIP_MAX_ENTRIES = 5000

# Hamming-Distanz (von 64 Bit) zweier pHashes, ab der zwei Bilder als "wahrscheinlich
# dasselbe Motiv" gelten - empirischer Richtwert, bei Bedarf anhand echter Fehlalarme
# nachjustieren.
PERCEPTUAL_DUPLICATE_THRESHOLD = 5

# Vorschaubilder fuer die "Dateien"-Uebersicht: klein genug, dass ein Grid mit vielen
# Kacheln fluessig laedt, aber noch erkennbar - die Originaldatei wird nur beim Klick
# ins Lightbox (volle Aufloesung) nachgeladen.
THUMBNAIL_MAX_DIMENSION = 480
THUMBNAIL_JPEG_QUALITY = 78


# SECURITY: the client-sent Content-Type header is fully attacker-controlled and must never be
# trusted on its own - a file with a forged image mime type could smuggle arbitrary content
# into storage. Check the actual file signature (magic bytes) against the claimed mime type
# before persisting anything.
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


# "Dateien"-Seite (POST /files/document-uploads): allow-list of document formats by extension.
# The extension only picks *which* signature check applies and what mime type gets stored -
# the content itself must still match it (see _sniff_document_mime), so a renamed .exe never
# gets through as .pdf. Images are deliberately absent (they belong on the "Fotos" page).
_OOXML_ODF_ZIP_MIMES = {
    ".docx": WORD_IMPORT_MIME_TYPE,
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".zip": "application/zip",
}
_LEGACY_OFFICE_MIMES = {
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
}
_PLAIN_TEXT_MIMES = {".txt": "text/plain", ".csv": "text/csv", ".md": "text/markdown"}
DOCUMENT_UPLOAD_EXTENSIONS = tuple(
    sorted({".pdf", ".rtf", *_OOXML_ODF_ZIP_MIMES, *_LEGACY_OFFICE_MIMES, *_PLAIN_TEXT_MIMES})
)


def _sniff_document_mime(content: bytes, filename: str) -> str | None:
    """Same idea as _sniff_image_mime, for the "Dateien" upload window - returns None unless
    the filename's extension is on the document allow-list *and* the content's own magic
    bytes agree with it (plain-text formats have no signature: they just must not look
    binary)."""
    extension = Path(filename).suffix.lower()
    head = content[:8]
    if extension == ".pdf":
        return PDF_MIME_TYPE if _content_matches_mime(content, PDF_MIME_TYPE) else None
    if extension in _OOXML_ODF_ZIP_MIMES:
        return _OOXML_ODF_ZIP_MIMES[extension] if head.startswith(b"PK\x03\x04") else None
    if extension in _LEGACY_OFFICE_MIMES:
        return _LEGACY_OFFICE_MIMES[extension] if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") else None
    if extension == ".rtf":
        return "application/rtf" if head.startswith(b"{\\rtf") else None
    if extension in _PLAIN_TEXT_MIMES:
        return _PLAIN_TEXT_MIMES[extension] if b"\x00" not in content[:8192] else None
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
    an anonymous endpoint). Used by extract_word_import_files_from_zip below - the gallery
    upload window's own ZIP handling instead streams off disk, see iter_gallery_zip_entries."""
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
        try:
            entry_bytes = archive.read(info)
        except (zipfile.BadZipFile, zlib.error, OSError):
            # A single corrupt entry (CRC mismatch, truncated data) previously aborted
            # the whole upload with an unhandled 500 instead of a clean partial-success
            # response, unlike every other per-entry issue here (oversized, wrong mime),
            # which is skipped with a note (audit finding, 2026-08-25).
            notes.append(f"{name}: beschädigter ZIP-Eintrag, übersprungen")
            continue
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


def iter_gallery_zip_entries(path: Path) -> Iterator[tuple[str, bytes] | str]:
    """ZIP upload for the gallery upload window (see FileService.process_pending_gallery_upload_jobs):
    reads a ZIP already staged on disk and yields one matching (filename, content) image at
    a time, or a plain str note for a skipped/oversized/corrupt entry (only genuine images,
    by magic bytes not filename, ever match - folders/junk/wrong-type entries are silently
    skipped, same as _extract_matching_files_from_zip's word-import counterpart). Callers
    tell a match from a note with isinstance(item, tuple).

    Deliberately not built on _extract_matching_files_from_zip: that helper takes the whole
    ZIP as one `content: bytes` and returns one fully-materialized `matched` list, which is
    exactly the "hold the whole batch in memory at once" cost this job exists to avoid.
    zipfile.ZipFile(path) instead seeks/reads each entry from the file handle on demand, so
    only one entry's decompressed bytes are ever live at a time - bounded by MAX_UPLOAD_BYTES
    regardless of how large the ZIP itself is. Uses the much larger GALLERY_ZIP_MAX_BYTES/
    GALLERY_ZIP_MAX_ENTRIES caps since there's no more per-request memory cost to guard
    against, only a sane upper bound against zip bombs."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        yield "ZIP-Datei ist beschädigt oder ungültig"
        return

    entries = [info for info in archive.infolist() if not info.is_dir()]
    total_bytes = 0
    for info in entries[:GALLERY_ZIP_MAX_ENTRIES]:
        name = Path(info.filename).name
        if not name or name.startswith("."):
            continue
        if info.file_size > MAX_UPLOAD_BYTES:
            yield f"{name}: zu gross, übersprungen"
            continue
        total_bytes += info.file_size
        if total_bytes > GALLERY_ZIP_MAX_BYTES:
            yield "ZIP-Inhalt zu gross - restliche Dateien wurden ignoriert"
            return
        try:
            entry_bytes = archive.read(info)
        except (zipfile.BadZipFile, zlib.error, OSError):
            yield f"{name}: beschädigter ZIP-Eintrag, übersprungen"
            continue
        if _sniff_image_mime(entry_bytes) is None:
            continue
        yield (name, entry_bytes)

    if len(entries) > GALLERY_ZIP_MAX_ENTRIES:
        yield f"ZIP enthält mehr als {GALLERY_ZIP_MAX_ENTRIES} Dateien - restliche wurden ignoriert"


STAGE_CHUNK_BYTES = 4 * 1024 * 1024  # 4 MB


async def stage_upload_to_disk(file: UploadFile, *, target_dir: Path, max_bytes: int, suffix: str) -> Path:
    """Streams an UploadFile straight to `target_dir` in fixed-size chunks instead of the
    `content = await file.read()` every other upload path in this codebase uses - the one
    thing that actually keeps a multi-GB gallery ZIP upload (see GALLERY_ZIP_MAX_BYTES)
    from being held in a single in-memory `bytes` object. Aborts (deletes the partial file,
    raises 413) as soon as the running byte count crosses max_bytes, rather than only
    checking after the whole transfer finished.

    target_dir must be a real, disk-backed directory (a subdirectory of settings.upload_root
    - see FileService.ensure_storage), never the process's default tempfile location: the
    release deployment mounts /tmp as RAM-backed tmpfs, which would silently turn this
    streaming write back into an in-memory buffer."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex}{suffix}"
    written = 0
    with target_path.open("wb") as handle:
        while chunk := await file.read(STAGE_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"{file.filename or 'Datei'}: zu gross (maximal {max_bytes // 1024 // 1024} MB)",
                )
            handle.write(chunk)
    return target_path


def _compute_perceptual_hash(content: bytes, mime: str) -> str | None:
    """DCT-based perceptual hash (pHash) for the tenant-wide "sieht aus wie ein bereits
    hochgeladenes Bild"-Warnung. Returns None for non-image mime types or content PIL can't
    decode (e.g. a truncated file that still happened to pass the magic-byte check)."""
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            return str(perceptual_hash_of_image(image))
    except Exception:
        return None


# Ein Rand gilt nur als "Letterbox", wenn er (fast) schwarz oder (fast) weiss ist - ein
# dunkler Himmel in der Bildecke darf nicht als Rand weggeschnitten werden.
_BORDER_COLOR_TOLERANCE = 24
_BORDER_MIN_CONTENT_FRACTION = 0.4


def _crop_uniform_border(image: Image.Image) -> Image.Image:
    """Schneidet einen einfarbigen schwarzen/weissen Rand ab (Screenshots, Story-/Letterbox-
    Exporte). Ohne das hasht ein und dasselbe Foto mit Rahmen voellig anders als das
    Original (Hamming-Distanz ~20 statt <5), weil der pHash das Gesamtbild auf 32x32
    herunterrechnet und der Rand einen grossen Teil davon einnimmt. Schneidet nichts ab,
    wenn die vier Ecken nicht dieselbe Randfarbe haben oder weniger als
    _BORDER_MIN_CONTENT_FRACTION der Flaeche als Inhalt uebrig bliebe."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    corners = [rgb.getpixel(xy) for xy in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
    background = corners[0]
    if any(max(abs(a - b) for a, b in zip(corner, background)) > _BORDER_COLOR_TOLERANCE for corner in corners):
        return rgb
    if not (max(background) <= _BORDER_COLOR_TOLERANCE or min(background) >= 255 - _BORDER_COLOR_TOLERANCE):
        return rgb
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background)).convert("L")
    box = diff.point(lambda value: 255 if value > _BORDER_COLOR_TOLERANCE else 0).getbbox()
    if box is None:
        return rgb
    if (box[2] - box[0]) * (box[3] - box[1]) < _BORDER_MIN_CONTENT_FRACTION * width * height:
        return rgb
    return rgb.crop(box)


def perceptual_hash_of_image(image: Image.Image) -> imagehash.ImageHash:
    """pHash of what the user actually sees: EXIF rotation applied (a phone photo's pixels
    are stored sideways with an orientation tag - hashing them raw made the same photo
    differ from its already-rotated PNG/screenshot copy by ~26 bits) and a uniform border
    cropped off (see _crop_uniform_border). The single hash definition for both the upload
    duplicate warning and the "Aehnliche" series grouping."""
    return imagehash.phash(_crop_uniform_border(ImageOps.exif_transpose(image)))


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


def generate_thumbnail_bytes(content: bytes) -> tuple[bytes, int, int] | None:
    """Downscaled JPEG preview for the "Dateien" grid, plus the original's (width, height) -
    read here for free since exif_transpose() already decodes the full image, sparing
    callers a second PIL decode just to learn the dimensions (see StoredFile.width/height).
    Dimensions are taken post-transpose so they match what's actually rendered (a portrait
    phone photo with a rotation EXIF tag reports portrait, not its sensor's landscape byte
    layout). Returns None for content PIL can't decode (e.g. a truncated file that still
    passed the magic-byte check) - callers fall back to serving/linking the original then."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)  # respect camera rotation metadata
            width, height = image.size
            image.thumbnail((THUMBNAIL_MAX_DIMENSION, THUMBNAIL_MAX_DIMENSION))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
            return buffer.getvalue(), width, height
    except Exception:
        return None


# Distinct namespace (paired with tenant_id as the two int32 advisory-lock keys) from
# file_service.py's _PROTOCOL_IMAGE_QUOTA_LOCK_NAMESPACE and the background loops' fixed
# single-bigint ids (202600xxx range) - guards the tenant-wide storage-quota check/write
# race below.
_TENANT_STORAGE_QUOTA_LOCK_NAMESPACE = 909100002


def _enforce_tenant_storage_quota(db: Session, *, tenant_id: int, repo: StoredFileRepository, incoming_bytes: int) -> None:
    """Rejects an upload that would push the tenant over its admin-configured
    Tenant.storage_quota_bytes limit. Audit fix, 2026-09-17: this quota is computed and
    displayed everywhere (storage_service.py, the Speicher admin page shows "Kontingent
    überschritten") but was never actually enforced by any upload path - an admin's
    configured limit had zero effect on whether uploads kept succeeding. A tenant with no
    quota configured (quota_bytes is None, the default/common case) skips the check and
    the lock below entirely, since there's nothing to enforce.

    Guarded by a transaction-scoped Postgres advisory lock (pg_advisory_xact_lock) so two
    near-simultaneous uploads for the same tenant can't both observe "under quota" before
    either has actually written its bytes - the same TOCTOU class file_service.py's older,
    narrower protocol_image_storage_quota_mb check already guards against. Transaction-
    scoped rather than session-scoped: Postgres releases it automatically at this
    Session's next commit or rollback, so unlike a session-scoped lock there is no manual
    unlock call that could silently run on a different pooled connection than the one that
    acquired it (see file_service.py's _tenant_protocol_image_upload_lock, fixed the same
    way in this same audit round)."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.storage_quota_bytes is None:
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :tenant_id)"),
        {"ns": _TENANT_STORAGE_QUOTA_LOCK_NAMESPACE, "tenant_id": tenant_id},
    )
    current_bytes = repo.total_bytes_for_tenant(db, tenant_id)
    if current_bytes + incoming_bytes > tenant.storage_quota_bytes:
        raise HTTPException(
            status_code=400,
            detail="Speicherkontingent des Mandanten erreicht - Datei wurde nicht gespeichert.",
        )


@dataclass(frozen=True)
class UploadPipelineResult:
    stored_file: StoredFile
    duplicate_warning: str | None


def ingest_file(
    db: Session,
    *,
    tenant_id: int,
    content: bytes,
    original_filename: str,
    scan_status: str,
    sniff: Callable[[bytes], str | None],
    max_bytes: int,
    storage_subdir_parts: tuple[str, ...],
    enable_perceptual_dedupe: bool,
    enable_thumbnail: bool,
    created_by: int | None,
    capture_quality_scores: bool = False,
    tags: list[str] | None = None,
    too_large_message: str | None = None,
    unsupported_format_message: str = "Dateiformat wird nicht unterstützt",
    infected_message: str = "Datei wurde von der Virenprüfung als infiziert erkannt und wurde nicht gespeichert",
    stored_file_repository: StoredFileRepository | None = None,
    tenant_hashes: list[tuple[int, str]] | None = None,
) -> UploadPipelineResult:
    """Validate -> (caller already scanned; here we only act on the verdict) -> write under
    upload_root/storage_subdir_parts/<uuid4><suffix> -> checksum -> optional pHash dedupe
    warning -> optional thumbnail -> StoredFile row. Flushes but does not commit - the caller
    attaches its own origin row (ProtocolImage/GalleryImage/WordImportDocument) in the same
    transaction and commits once, together.

    Every check here re-validates from scratch even when a caller (e.g. save_protocol_image's
    own pre-read Content-Type check) has already ruled out the same failure by a different
    route - harmless redundancy, not a behavior change, and it's what lets every upload path
    share this one function instead of trusting caller-specific bookkeeping.

    tenant_hashes lets a caller ingesting a whole batch in a loop (save_gallery_uploads)
    fetch the tenant's existing perceptual-hash list once up front and pass the same list
    into every call, instead of this function re-querying it per file (audit fix,
    2026-09-17: a 300-image ZIP into a tenant with 20k already-hashed images used to
    re-fetch and re-scan that ~20k-row list 300 times). This function appends each newly
    computed hash to the list it's given, so later files in the same batch still catch
    duplicates of earlier files in that same batch, not just pre-existing ones. A caller
    that ingests one file at a time (save_protocol_image, save_word_import_document)
    leaves this None and gets the previous per-call query behavior."""
    repo = stored_file_repository or StoredFileRepository()

    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=too_large_message or f"Datei zu gross. Maximum {max_bytes // 1024 // 1024} MB",
        )
    mime = sniff(content)
    if mime is None:
        raise HTTPException(status_code=400, detail=unsupported_format_message)
    if scan_status == "infected":
        raise HTTPException(status_code=400, detail=infected_message)

    _enforce_tenant_storage_quota(db, tenant_id=tenant_id, repo=repo, incoming_bytes=len(content))

    suffix = Path(original_filename).suffix.lower() or ".bin"
    storage_dir = Path(settings.upload_root).joinpath(*storage_subdir_parts)
    storage_dir.mkdir(parents=True, exist_ok=True)
    target_path = storage_dir / f"{uuid4().hex}{suffix}"
    target_path.write_bytes(content)
    relative_path = target_path.relative_to(settings.storage_root)

    checksum = hashlib.sha256(content).hexdigest()
    perceptual_hash: str | None = None
    duplicate_warning: str | None = None
    if enable_perceptual_dedupe:
        perceptual_hash = _compute_perceptual_hash(content, mime)
        if perceptual_hash is not None:
            candidates = tenant_hashes if tenant_hashes is not None else repo.list_tenant_image_hashes(db, tenant_id)
            if _closest_perceptual_match(perceptual_hash, candidates) is not None:
                duplicate_warning = "Hinweis: Dieses Bild ähnelt einem bereits im Mandanten hochgeladenen Bild."

    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name=original_filename,
        mime_type=mime,
        storage_path=str(relative_path),
        file_size_bytes=len(content),
        checksum_sha256=checksum,
        perceptual_hash=perceptual_hash,
        tags=tags or [],
        created_by=created_by,
        scan_status=scan_status,
    )
    stored_file = repo.create(db, stored_file)  # add + flush, caller commits

    if tenant_hashes is not None and perceptual_hash is not None:
        tenant_hashes.append((stored_file.id, perceptual_hash))

    if capture_quality_scores:
        stored_file.sharpness_score, stored_file.exposure_score = compute_quality_scores(content)

    if enable_thumbnail:
        generated = generate_thumbnail_bytes(content)
        if generated is not None:
            thumbnail_bytes, width, height = generated
            thumbnail_root = Path(settings.thumbnail_root)
            thumbnail_root.mkdir(parents=True, exist_ok=True)
            thumbnail_target_path = thumbnail_root.resolve() / f"{stored_file.id}.jpg"
            thumbnail_target_path.write_bytes(thumbnail_bytes)
            stored_file.thumbnail_path = thumbnail_target_path.name
            stored_file.width = width
            stored_file.height = height

    return UploadPipelineResult(stored_file=stored_file, duplicate_warning=duplicate_warning)
