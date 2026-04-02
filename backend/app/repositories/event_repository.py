from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventCategory


class EventRepository:
    def list(self, db: Session, *, tenant_id: int) -> list[Event]:
        statement = select(Event).where(Event.tenant_id == tenant_id).order_by(Event.event_date.desc(), Event.event_end_date.desc(), Event.id.desc())
        return list(db.scalars(statement))

    def get(self, db: Session, event_id: int) -> Event | None:
        return db.get(Event, event_id)

    def create(self, db: Session, event: Event) -> Event:
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    def update(self, db: Session, event: Event, values: dict) -> Event:
        for key, value in values.items():
            setattr(event, key, value)
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    def delete(self, db: Session, event: Event) -> None:
        db.delete(event)
        db.commit()

    def category_id_by_code(self, db: Session, code: str) -> int | None:
        return db.scalar(select(EventCategory.id).where(EventCategory.code == code))
