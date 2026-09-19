from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Role, Tenant
from app.services import public_id_service


class UserRepository:
    def list(self, db: Session) -> list[AppUser]:
        return list(db.scalars(select(AppUser).order_by(AppUser.name.asc(), AppUser.id.asc())))

    def get(self, db: Session, user_id: int) -> AppUser | None:
        return db.get(AppUser, user_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID) -> AppUser | None:
        # Not tenant-scoped - callers must check the result's tenant_id against the acting
        # user's tenant themselves, same as for the numeric-id path this replaces.
        return public_id_service.get_by_public_id(db, AppUser, public_id)

    def list_by_tenant(self, db: Session, tenant_id: int) -> list[AppUser]:
        return list(
            db.scalars(select(AppUser).where(AppUser.tenant_id == tenant_id).order_by(AppUser.name.asc(), AppUser.id.asc()))
        )

    def count_active_admins(self, db: Session, tenant_id: int, *, excluding_user_id: int | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(AppUser)
            .join(Role, Role.id == AppUser.role_id)
            .where(AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True), Role.code == "admin")
        )
        if excluding_user_id is not None:
            statement = statement.where(AppUser.id != excluding_user_id)
        return int(db.scalar(statement) or 0)

    def get_by_email(self, db: Session, email: str) -> AppUser | None:
        statement = select(AppUser).where(AppUser.email == email)
        return db.scalar(statement)

    def create(self, db: Session, user: AppUser) -> AppUser:
        db.add(user)
        db.flush()
        db.refresh(user)
        return user

    def update(self, db: Session, user: AppUser, values: dict) -> AppUser:
        for key, value in values.items():
            setattr(user, key, value)
        db.add(user)
        db.flush()
        db.refresh(user)
        return user

    def delete(self, db: Session, user: AppUser) -> None:
        db.delete(user)
        db.flush()

    def list_roles(self, db: Session) -> list[Role]:
        return list(db.scalars(select(Role).order_by(Role.id.asc())))

    def list_tenants(self, db: Session) -> list[Tenant]:
        return list(db.scalars(select(Tenant).order_by(Tenant.name.asc(), Tenant.id.asc())))
