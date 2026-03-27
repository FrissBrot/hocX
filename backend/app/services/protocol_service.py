from sqlalchemy.orm import Session

from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolUpdate


class ProtocolService:
    def __init__(self, repository: ProtocolRepository | None = None) -> None:
        self.repository = repository or ProtocolRepository()

    def list_protocols(self, db: Session, *, query: str | None = None, status: str | None = None):
        return self.repository.list(db, query=query, status=status)

    def get_protocol(self, db: Session, protocol_id: int):
        return self.repository.get(db, protocol_id)

    def create_from_template(self, db: Session, payload: ProtocolCreateFromTemplate) -> int:
        return self.repository.create_from_template(
            db,
            tenant_id=payload.tenant_id,
            template_id=payload.template_id,
            protocol_number=payload.protocol_number,
            protocol_date=payload.protocol_date,
            created_by=payload.created_by,
            title=payload.title,
            event_id=payload.event_id,
        )

    def update_protocol(self, db: Session, protocol_id: int, payload: ProtocolUpdate):
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return protocol
        return self.repository.update(db, protocol, values)

    def delete_protocol(self, db: Session, protocol_id: int) -> bool:
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return False
        self.repository.delete(db, protocol)
        return True
