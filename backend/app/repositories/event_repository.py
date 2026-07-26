from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Event, EventCategory


class EventRepository:
    def list(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Event]:
        statement = select(Event).where(Event.tenant_id == tenant_id).order_by(Event.event_date.desc(), Event.event_end_date.desc(), Event.id.desc()).offset(skip).limit(limit)
        return list(db.scalars(statement))

    def list_filtered(
        self,
        db: Session,
        *,
        tenant_id: int,
        event_ids: set[int] | None = None,
        search: str = "",
        skip: int = 0,
        limit: int = 200,
    ) -> tuple[list[Event], int]:
        """List events for a tenant, optionally restricted to a set of ids and/or a
        title/tag search. Returns (items, total) with total counted before pagination."""
        statement = select(Event).where(Event.tenant_id == tenant_id)
        if event_ids is not None:
            statement = statement.where(Event.id.in_(event_ids))
        if search:
            pattern = f"%{search}%"
            statement = statement.where(or_(Event.title.ilike(pattern), Event.tag.ilike(pattern)))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        statement = statement.order_by(Event.event_date.desc(), Event.event_end_date.desc(), Event.id.desc()).offset(skip).limit(limit)
        return list(db.scalars(statement)), int(total)

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
