from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.models import Protocol, ProtocolElement, ProtocolElementBlock, ProtocolImage, StoredFile
from app.repositories.file_repository import ProtocolImageRepository, StoredFileRepository
from app.schemas.protocol import ProtocolImageRead

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


def extract_word_import_files_from_zip(content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Unpacks a ZIP upload for the word-import queue entirely in memory: only entries
    that are genuinely a .docx or .pdf (verified via magic bytes, never the entry name -
    same principle as _sniff_word_import_mime above) are kept and returned. Everything
    else (folders, images, __MACOSX/.DS_Store junk, ...) is silently skipped - nothing
    from the archive other than the matched entries ever touches disk, so there is
    nothing left to clean up afterwards. Entry count/size are capped to guard against
    zip bombs (declared, not actual, size - sufficient here since uploads require an
    authenticated writer, not an anonymous endpoint)."""
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
        if _sniff_word_import_mime(entry_bytes) is None:
            continue  # weder .docx noch .pdf - wird bewusst ignoriert, nie gespeichert
        matched.append((name, entry_bytes))

    if len(entries) > MAX_ZIP_ENTRIES:
        notes.append(f"ZIP enthält mehr als {MAX_ZIP_ENTRIES} Dateien - restliche wurden ignoriert")
    if not matched and not notes:
        notes.append("ZIP enthält keine Word- oder PDF-Dateien")
    return matched, notes


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
        for path in [settings.storage_root, settings.export_root, settings.upload_root, settings.latex_template_root]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def build_content_url(self, stored_file_id: int) -> str:
        return f"/api/stored-files/{stored_file_id}/content"

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

        suffix = Path(file.filename or "").suffix.lower() or ".bin"
        tenant_id = self._resolve_tenant_id(db, protocol_element_block.id)
        storage_dir = Path(settings.upload_root) / f"tenant-{tenant_id}" / f"block-{protocol_element_block.id}"
        storage_dir.mkdir(parents=True, exist_ok=True)
        generated_name = f"{uuid4().hex}{suffix}"
        target_path = storage_dir / generated_name

        checksum = hashlib.sha256(content).hexdigest()
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
            created_by=created_by,
        )
        stored_file = self.stored_file_repository.create(db, stored_file)

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
        )

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

    def read_stored_file_bytes(self, stored_file: StoredFile) -> bytes:
        file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Datei fehlt im Speicher")
        return file_path.read_bytes()

    def delete_stored_file(self, db: Session, stored_file: StoredFile) -> None:
        file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        if file_path.exists():
            file_path.unlink()
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
