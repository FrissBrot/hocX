from __future__ import annotations

import uuid

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Event, EventCategory, Protocol
from app.services import public_id_service


class EventRepository:
    def list(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Event]:
        # is_session_marker events are auto-generated "next session" placeholders from a
        # protocol's session-date block - they shouldn't clutter the Termine overview.
        # Once a Protocol actually gets held against one (event_id points at it), it's a
        # real session and belongs in the list like any other event.
        has_protocol = exists().where(Protocol.event_id == Event.id)
        statement = (
            select(Event)
            .where(
                Event.tenant_id == tenant_id,
                or_(Event.is_session_marker.is_(False), has_protocol),
            )
            .order_by(Event.event_date.desc(), Event.event_end_date.desc(), Event.id.desc())
            .offset(skip)
            .limit(limit)
        )
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

    def get_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> Event | None:
        return public_id_service.get_by_public_id(db, Event, public_id, tenant_id=tenant_id)

    def create(self, db: Session, event: Event, *, commit: bool = True) -> Event:
        db.add(event)
        db.flush()
        if commit:
            db.commit()
            db.refresh(event)
        return event

    def update(self, db: Session, event: Event, values: dict, *, commit: bool = True) -> Event:
        for key, value in values.items():
            setattr(event, key, value)
        db.add(event)
        db.flush()
        if commit:
            db.commit()
            db.refresh(event)
        return event

    def delete(self, db: Session, event: Event) -> None:
        db.delete(event)
        db.commit()

    def category_id_by_code(self, db: Session, code: str) -> int | None:
        return db.scalar(select(EventCategory.id).where(EventCategory.code == code))
