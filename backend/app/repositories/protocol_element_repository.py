from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ElementType,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    RenderType,
)


class ProtocolElementRepository:
    def list_for_protocol(self, db: Session, protocol_id: int) -> list[ProtocolElement]:
        return list(
            db.scalars(
                select(ProtocolElement)
                .where(ProtocolElement.protocol_id == protocol_id)
                .order_by(ProtocolElement.sort_index.asc(), ProtocolElement.id.asc())
            )
        )

    def list_blocks_for_elements(self, db: Session, protocol_element_ids: list[int]):
        if not protocol_element_ids:
            return []
        query = (
            select(
                ProtocolElementBlock,
                ElementType.code.label("element_type_code"),
                RenderType.code.label("render_type_code"),
                ProtocolText.content.label("text_content"),
                ProtocolDisplaySnapshot.compiled_text.label("display_compiled_text"),
                ProtocolDisplaySnapshot.snapshot_json.label("display_snapshot_json"),
            )
            .join(ElementType, ElementType.id == ProtocolElementBlock.element_type_id)
            .join(RenderType, RenderType.id == ProtocolElementBlock.render_type_id)
            .outerjoin(ProtocolText, ProtocolText.protocol_element_block_id == ProtocolElementBlock.id)
            .outerjoin(ProtocolDisplaySnapshot, ProtocolDisplaySnapshot.protocol_element_block_id == ProtocolElementBlock.id)
            .where(ProtocolElementBlock.protocol_element_id.in_(protocol_element_ids))
            .order_by(ProtocolElementBlock.protocol_element_id.asc(), ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, protocol_element_id: int) -> ProtocolElement | None:
        return db.get(ProtocolElement, protocol_element_id)

    def update(self, db: Session, protocol_element: ProtocolElement, values: dict) -> ProtocolElement:
        for key, value in values.items():
            setattr(protocol_element, key, value)
        db.add(protocol_element)
        db.commit()
        db.refresh(protocol_element)
        return protocol_element


class ProtocolElementBlockRepository:
    def get(self, db: Session, protocol_element_block_id: int) -> ProtocolElementBlock | None:
        return db.get(ProtocolElementBlock, protocol_element_block_id)

    def update(self, db: Session, protocol_element_block: ProtocolElementBlock, values: dict) -> ProtocolElementBlock:
        for key, value in values.items():
            setattr(protocol_element_block, key, value)
        db.add(protocol_element_block)
        db.commit()
        db.refresh(protocol_element_block)
        return protocol_element_block


class ProtocolTextRepository:
    def get_by_protocol_element_block_id(self, db: Session, protocol_element_block_id: int) -> ProtocolText | None:
        return db.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == protocol_element_block_id))

    def save(self, db: Session, protocol_text: ProtocolText) -> ProtocolText:
        db.add(protocol_text)
        db.commit()
        db.refresh(protocol_text)
        return protocol_text
