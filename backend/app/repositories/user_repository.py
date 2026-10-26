from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Tenant


class UserRepository:
    def list(self, db: Session) -> list[AppUser]:
        return list(db.scalars(select(AppUser).order_by(AppUser.name.asc(), AppUser.id.asc())))

    def get(self, db: Session, user_id: int) -> AppUser | None:
        return db.get(AppUser, user_id)

    def list_by_tenant(self, db: Session, tenant_id: int) -> list[AppUser]:
        return list(
            db.scalars(select(AppUser).where(AppUser.tenant_id == tenant_id).order_by(AppUser.name.asc(), AppUser.id.asc()))
        )

    def get_by_email(self, db: Session, email: str) -> AppUser | None:
        statement = select(AppUser).where(AppUser.email == email.strip().lower(), AppUser.login_enabled.is_(True))
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

    def list_tenants(self, db: Session) -> list[Tenant]:
        return list(db.scalars(select(Tenant).order_by(Tenant.name.asc(), Tenant.id.asc())))
