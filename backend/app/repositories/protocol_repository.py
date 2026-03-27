from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Protocol


class ProtocolRepository:
    def list(self, db: Session) -> list[Protocol]:
        return list(db.scalars(select(Protocol).order_by(Protocol.id.desc())))

    def get(self, db: Session, protocol_id: int) -> Protocol | None:
        return db.get(Protocol, protocol_id)

    def create_from_template(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_number: str,
        protocol_date,
        created_by: int,
        title: str | None,
        event_id: int | None,
    ) -> int:
        result = db.execute(
            text(
                """
                SELECT create_protocol_from_template(
                    :tenant_id,
                    :template_id,
                    :protocol_number,
                    :protocol_date,
                    :created_by,
                    :title,
                    :event_id
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "template_id": template_id,
                "protocol_number": protocol_number,
                "protocol_date": protocol_date,
                "created_by": created_by,
                "title": title,
                "event_id": event_id,
            },
        )
        protocol_id = result.scalar_one()
        db.commit()
        return int(protocol_id)

