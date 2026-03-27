from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DocumentTemplate,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolExportCache,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoredFile,
    TodoStatus,
)


class ExportRepository:
    def get_protocol(self, db: Session, protocol_id: int) -> Protocol | None:
        return db.get(Protocol, protocol_id)

    def get_document_template(self, db: Session, document_template_id: int | None) -> DocumentTemplate | None:
        if document_template_id is None:
            return None
        return db.get(DocumentTemplate, document_template_id)

    def list_protocol_elements(self, db: Session, protocol_id: int) -> list[ProtocolElement]:
        return list(
            db.scalars(
                select(ProtocolElement)
                .where(ProtocolElement.protocol_id == protocol_id)
                .order_by(ProtocolElement.sort_index.asc())
            )
        )

    def list_protocol_element_blocks(self, db: Session, protocol_element_id: int) -> list[ProtocolElementBlock]:
        return list(
            db.scalars(
                select(ProtocolElementBlock)
                .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
                .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
            )
        )

    def get_protocol_text(self, db: Session, protocol_element_block_id: int) -> ProtocolText | None:
        return db.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == protocol_element_block_id))

    def list_protocol_todos(self, db: Session, protocol_element_block_id: int):
        query = (
            select(ProtocolTodo, TodoStatus.code.label("todo_status_code"))
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .where(ProtocolTodo.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolTodo.sort_index.asc())
        )
        return db.execute(query).all()

    def list_protocol_images(self, db: Session, protocol_element_block_id: int):
        query = (
            select(ProtocolImage, StoredFile)
            .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
            .where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolImage.sort_index.asc())
        )
        return db.execute(query).all()

    def create_stored_file(self, db: Session, stored_file: StoredFile) -> StoredFile:
        db.add(stored_file)
        db.flush()
        return stored_file

    def create_export_cache(self, db: Session, cache: ProtocolExportCache) -> ProtocolExportCache:
        db.add(cache)
        db.flush()
        return cache

    def latest_export_cache(self, db: Session, protocol_id: int) -> ProtocolExportCache | None:
        return db.scalar(
            select(ProtocolExportCache)
            .where(ProtocolExportCache.protocol_id == protocol_id)
            .order_by(ProtocolExportCache.created_at.desc(), ProtocolExportCache.id.desc())
        )

    def get_stored_file(self, db: Session, stored_file_id: int | None) -> StoredFile | None:
        if stored_file_id is None:
            return None
        return db.get(StoredFile, stored_file_id)
