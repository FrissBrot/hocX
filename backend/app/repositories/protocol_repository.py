from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Protocol


class ProtocolRepository:
    def list(self, db: Session, *, tenant_id: int, query: str | None = None, status: str | None = None) -> list[Protocol]:
        statement = select(Protocol).where(Protocol.tenant_id == tenant_id)
        if query:
            statement = statement.where(
                Protocol.protocol_number.ilike(f"%{query}%") | Protocol.title.ilike(f"%{query}%")
            )
        if status:
            statement = statement.where(Protocol.status == status)
        statement = statement.order_by(Protocol.id.desc())
        return list(db.scalars(statement))

    def get(self, db: Session, protocol_id: int) -> Protocol | None:
        return db.get(Protocol, protocol_id)

    def update(self, db: Session, protocol: Protocol, values: dict) -> Protocol:
        for key, value in values.items():
            setattr(protocol, key, value)
        db.add(protocol)
        db.commit()
        db.refresh(protocol)
        return protocol

    def delete(self, db: Session, protocol: Protocol) -> None:
        db.delete(protocol)
        db.commit()

    def create_from_template(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_number: str,
        protocol_date,
        created_by: int | None,
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
