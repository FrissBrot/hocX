from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Protocol


class ProtocolRepository:
    def list(
        self,
        db: Session,
        *,
        tenant_id: int,
        query: str | None = None,
        status: str | None = None,
        protocol_ids: list[int] | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Protocol]:
        statement = select(Protocol).where(Protocol.tenant_id == tenant_id)
        if protocol_ids is not None:
            if not protocol_ids:
                return []
            statement = statement.where(Protocol.id.in_(protocol_ids))
        if query:
            statement = statement.where(
                Protocol.protocol_number.ilike(f"%{query}%") | Protocol.title.ilike(f"%{query}%")
            )
        if status:
            statement = statement.where(Protocol.status == status)
        statement = statement.order_by(Protocol.id.desc()).offset(skip).limit(limit)
        return list(db.scalars(statement))

    def get(self, db: Session, protocol_id: int) -> Protocol | None:
        return db.get(Protocol, protocol_id)

    def next_open(self, db: Session, *, tenant_id: int) -> Protocol | None:
        """The soonest-dated protocol that isn't finalized yet - the tenant's 'next session'."""
        statement = (
            select(Protocol)
            .where(Protocol.tenant_id == tenant_id, Protocol.status != "abgeschlossen")
            .order_by(Protocol.protocol_date.asc(), Protocol.id.asc())
            .limit(1)
        )
        return db.scalar(statement)

    def next_template_sequence(self, db: Session, *, tenant_id: int, template_id: int) -> int:
        statement = select(func.count(Protocol.id)).where(
            Protocol.tenant_id == tenant_id,
            Protocol.template_id == template_id,
        )
        return int(db.scalar(statement) or 0) + 1

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
