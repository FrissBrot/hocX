import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProtocolImage, StoredFile
from app.services import public_id_service


class StoredFileRepository:
    def create(self, db: Session, stored_file: StoredFile) -> StoredFile:
        db.add(stored_file)
        db.flush()
        return stored_file

    def get_for_tenant(self, db: Session, stored_file_id: int, tenant_id: int) -> StoredFile | None:
        stored_file = db.get(StoredFile, stored_file_id)
        return stored_file if stored_file is not None and stored_file.tenant_id == tenant_id else None

    def get(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return db.get(StoredFile, stored_file_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> StoredFile | None:
        return public_id_service.get_by_public_id(db, StoredFile, public_id, tenant_id=tenant_id)

    def delete(self, db: Session, stored_file: StoredFile) -> None:
        db.delete(stored_file)

    def list_pending_word_import_files(self, db: Session) -> list[StoredFile]:
        """Word-import documents are stored under a fixed 'word-imports/' path prefix
        (see FileService.save_word_import_document) - that's used here instead of a join
        to WordImportDocument so a file still mid-analyze (not yet turned into a
        WordImportDocument row) is picked up too."""
        return list(
            db.execute(
                select(StoredFile).where(
                    StoredFile.scan_status == "pending",
                    StoredFile.storage_path.like("uploads/word-imports/%"),
                )
            ).scalars()
        )

    def update_scan_status(self, db: Session, stored_file: StoredFile, *, scan_status: str) -> None:
        stored_file.scan_status = scan_status
        db.add(stored_file)

    def list_pending_protocol_images(self, db: Session) -> list[StoredFile]:
        # Joined through ProtocolImage rather than a path prefix (unlike
        # list_pending_word_import_files) - a protocol image's StoredFile and its
        # ProtocolImage row are always created together in the same call
        # (FileService.save_protocol_image), so there's no "not yet linked" gap to worry
        # about here.
        return list(
            db.execute(
                select(StoredFile)
                .join(ProtocolImage, ProtocolImage.stored_file_id == StoredFile.id)
                .where(StoredFile.scan_status == "pending")
            ).scalars()
        )


class ProtocolImageRepository:
    def list_for_protocol_block(self, db: Session, protocol_element_block_id: int):
        query = (
            select(ProtocolImage, StoredFile)
            .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
            .where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolImage.sort_index.asc(), ProtocolImage.id.asc())
        )
        return db.execute(query).all()

    def next_sort_index(self, db: Session, protocol_element_block_id: int) -> int:
        current = db.scalar(
            select(func.max(ProtocolImage.sort_index)).where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
        )
        return 0 if current is None else int(current) + 1

    def create(self, db: Session, protocol_image: ProtocolImage) -> ProtocolImage:
        db.add(protocol_image)
        db.flush()
        return protocol_image

    def get(self, db: Session, image_id: int) -> ProtocolImage | None:
        return db.get(ProtocolImage, image_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID) -> ProtocolImage | None:
        # ProtocolImage has no tenant_id column of its own (scoped transitively via
        # protocol_element_block -> protocol_element -> protocol) - callers must verify
        # tenant/access via access_repository on the resolved row, same as for the
        # numeric-id path this replaces.
        return public_id_service.get_by_public_id(db, ProtocolImage, public_id)

    def delete(self, db: Session, protocol_image: ProtocolImage) -> None:
        db.delete(protocol_image)
