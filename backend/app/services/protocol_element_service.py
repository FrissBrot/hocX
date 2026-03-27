from sqlalchemy.orm import Session

from app.repositories.protocol_element_repository import ProtocolElementRepository
from app.schemas.protocol import ProtocolElementRead, ProtocolElementUpdate


class ProtocolElementService:
    def __init__(self, repository: ProtocolElementRepository | None = None) -> None:
        self.repository = repository or ProtocolElementRepository()

    def list_protocol_elements(self, db: Session, protocol_id: int) -> list[ProtocolElementRead]:
        rows = self.repository.list_for_protocol(db, protocol_id)
        return [
            ProtocolElementRead(
                **row.ProtocolElement.__dict__,
                element_type_code=row.element_type_code,
                render_type_code=row.render_type_code,
                text_content=row.text_content,
                display_compiled_text=row.display_compiled_text,
                display_snapshot_json=row.display_snapshot_json or {},
            )
            for row in rows
        ]

    def update_protocol_element(self, db: Session, protocol_element_id: int, payload: ProtocolElementUpdate):
        protocol_element = self.repository.get(db, protocol_element_id)
        if protocol_element is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return protocol_element
        return self.repository.update(db, protocol_element, values)
