from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ElementType, ProtocolDisplaySnapshot, ProtocolElement, ProtocolText, RenderType


class ProtocolElementRepository:
    def list_for_protocol(self, db: Session, protocol_id: int):
        query = (
            select(
                ProtocolElement,
                ElementType.code.label("element_type_code"),
                RenderType.code.label("render_type_code"),
                ProtocolText.content.label("text_content"),
                ProtocolDisplaySnapshot.compiled_text.label("display_compiled_text"),
                ProtocolDisplaySnapshot.snapshot_json.label("display_snapshot_json"),
            )
            .join(ElementType, ElementType.id == ProtocolElement.element_type_id)
            .join(RenderType, RenderType.id == ProtocolElement.render_type_id)
            .outerjoin(ProtocolText, ProtocolText.protocol_element_id == ProtocolElement.id)
            .outerjoin(ProtocolDisplaySnapshot, ProtocolDisplaySnapshot.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElement.protocol_id == protocol_id)
            .order_by(ProtocolElement.sort_index.asc())
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


class ProtocolTextRepository:
    def get_by_protocol_element_id(self, db: Session, protocol_element_id: int) -> ProtocolText | None:
        return db.scalar(
            select(ProtocolText).where(ProtocolText.protocol_element_id == protocol_element_id)
        )

    def save(self, db: Session, protocol_text: ProtocolText) -> ProtocolText:
        db.add(protocol_text)
        db.commit()
        db.refresh(protocol_text)
        return protocol_text
