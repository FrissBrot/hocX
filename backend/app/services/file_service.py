from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

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
            mime_type=file.content_type,
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

    def get_stored_file(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return self.stored_file_repository.get(db, stored_file_id)

    def delete_protocol_image(self, db: Session, image_id: int) -> bool:
        protocol_image = self.protocol_image_repository.get(db, image_id)
        if protocol_image is None:
            return False

        stored_file = self.stored_file_repository.get(db, protocol_image.stored_file_id)
        self.protocol_image_repository.delete(db, protocol_image)
        if stored_file is not None:
            file_path = Path(settings.storage_root) / stored_file.storage_path
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
