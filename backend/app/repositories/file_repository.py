from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProtocolImage, StoredFile


class StoredFileRepository:
    def create(self, db: Session, stored_file: StoredFile) -> StoredFile:
        db.add(stored_file)
        db.flush()
        return stored_file

    def get(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return db.get(StoredFile, stored_file_id)

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

    def delete(self, db: Session, protocol_image: ProtocolImage) -> None:
        db.delete(protocol_image)
