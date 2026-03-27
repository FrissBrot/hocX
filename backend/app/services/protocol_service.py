from sqlalchemy.orm import Session

from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.protocol import ProtocolCreateFromTemplate


class ProtocolService:
    def __init__(self, repository: ProtocolRepository | None = None) -> None:
        self.repository = repository or ProtocolRepository()

    def list_protocols(self, db: Session):
        return self.repository.list(db)

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

