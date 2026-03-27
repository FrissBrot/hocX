from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, Role, Tenant, UserRole, UserTenantRole


class UserRepository:
    def list(self, db: Session) -> list[AppUser]:
        return list(db.scalars(select(AppUser).order_by(AppUser.name.asc(), AppUser.id.asc())))

    def get(self, db: Session, user_id: int) -> AppUser | None:
        return db.get(AppUser, user_id)

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

    def list_memberships(self, db: Session, *, user_id: int | None = None, tenant_id: int | None = None) -> list[UserTenantRole]:
        statement = select(UserTenantRole)
        if user_id is not None:
            statement = statement.where(UserTenantRole.user_id == user_id)
        if tenant_id is not None:
            statement = statement.where(UserTenantRole.tenant_id == tenant_id)
        statement = statement.order_by(UserTenantRole.tenant_id.asc(), UserTenantRole.user_id.asc())
        return list(db.scalars(statement))

    def replace_memberships(self, db: Session, *, user_id: int, memberships: list[UserTenantRole]) -> None:
        existing = self.list_memberships(db, user_id=user_id)
        for membership in existing:
            db.delete(membership)
        db.flush()
        for membership in memberships:
            db.add(membership)
        db.flush()

    def list_global_roles(self, db: Session, *, user_id: int) -> list[str]:
        statement = (
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code.asc())
        )
        return list(db.scalars(statement))

    def set_global_superadmin(self, db: Session, *, user_id: int, enabled: bool, superadmin_role_id: int) -> None:
        existing = db.scalar(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == superadmin_role_id)
        )
        if enabled and existing is None:
            db.add(UserRole(user_id=user_id, role_id=superadmin_role_id))
        if not enabled and existing is not None:
            db.delete(existing)
        db.flush()
