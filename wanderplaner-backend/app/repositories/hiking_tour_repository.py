from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HikingTour, HikingTourWaypoint


class HikingTourRepository:
    def list(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[HikingTour]:
        statement = (
            select(HikingTour)
            .where(HikingTour.tenant_id == tenant_id)
            .order_by(HikingTour.tour_date.desc().nullslast(), HikingTour.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(db.scalars(statement))

    def get(self, db: Session, tour_id: int) -> HikingTour | None:
        return db.get(HikingTour, tour_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> HikingTour | None:
        # Immer auf den Mandanten des Aufrufers einschraenken - eine gueltige UUID eines anderen
        # Mandanten ist keine Berechtigung.
        statement = select(HikingTour).where(HikingTour.public_id == public_id, HikingTour.tenant_id == tenant_id)
        return db.scalars(statement).first()

    def create(self, db: Session, tour: HikingTour, *, commit: bool = True) -> HikingTour:
        db.add(tour)
        db.flush()
        if commit:
            db.commit()
            db.refresh(tour)
        return tour

    def update(self, db: Session, tour: HikingTour, values: dict, *, commit: bool = True) -> HikingTour:
        for key, value in values.items():
            setattr(tour, key, value)
        db.add(tour)
        db.flush()
        if commit:
            db.commit()
            db.refresh(tour)
        return tour

    def delete(self, db: Session, tour: HikingTour) -> None:
        db.delete(tour)
        db.commit()

    def get_waypoint_by_public_id(self, db: Session, tour: HikingTour, public_id: uuid.UUID) -> HikingTourWaypoint | None:
        """Looks up a waypoint by public_id, scoped to an already tenant-verified tour -
        hiking_tour_waypoint has no tenant_id of its own (transitively scoped through the
        tour), so the caller must have resolved/verified `tour`
        for the current tenant first."""
        statement = select(HikingTourWaypoint).where(
            HikingTourWaypoint.public_id == public_id, HikingTourWaypoint.hiking_tour_id == tour.id
        )
        return db.scalars(statement).first()

    def add_waypoint(self, db: Session, waypoint: HikingTourWaypoint, *, commit: bool = True) -> HikingTourWaypoint:
        db.add(waypoint)
        db.flush()
        if commit:
            db.commit()
            db.refresh(waypoint)
        return waypoint

    def update_waypoint(self, db: Session, waypoint: HikingTourWaypoint, values: dict, *, commit: bool = True) -> HikingTourWaypoint:
        for key, value in values.items():
            setattr(waypoint, key, value)
        db.add(waypoint)
        db.flush()
        if commit:
            db.commit()
            db.refresh(waypoint)
        return waypoint

    def delete_waypoint(self, db: Session, waypoint: HikingTourWaypoint) -> None:
        db.delete(waypoint)
        db.commit()
