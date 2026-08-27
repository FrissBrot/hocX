from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, Role, Tenant, UserTenantRole
from app.services import public_id_service


class UserRepository:
    def list(self, db: Session) -> list[AppUser]:
        return list(db.scalars(select(AppUser).order_by(AppUser.name.asc(), AppUser.id.asc())))

    def get(self, db: Session, user_id: int) -> AppUser | None:
        return db.get(AppUser, user_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID) -> AppUser | None:
        # AppUser has no tenant_id column (a user can belong to several tenants via
        # UserTenantRole) - callers must verify tenant membership separately, e.g. via
        # list_memberships(), same as for the numeric-id path this replaces.
        return public_id_service.get_by_public_id(db, AppUser, public_id)

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

    def replace_memberships(
        self,
        db: Session,
        *,
        user_id: int,
        memberships: list[UserTenantRole],
        scope_tenant_ids: set[int] | None = None,
    ) -> None:
        """Replaces user_id's memberships with `memberships`. When scope_tenant_ids is given,
        only existing rows whose tenant_id is in that set are deleted before re-inserting -
        rows for tenants outside the scope are left completely untouched, both by the delete
        and by the re-insert (`memberships` must itself already be pre-filtered to the same
        scope by the caller). scope_tenant_ids=None (platform-admin/merge callers) keeps the
        original full-replace behaviour: every existing row for the user is deleted first.

        Audit finding, 2026-08-27: the previous unconditional "delete everything, then
        re-insert" here is what the tenant-admin-scoped caller (_apply_memberships) actually
        needs to *avoid* for out-of-scope memberships - passing those already-fetched ORM
        rows back in to be "kept" doesn't work anyway, since this method had already deleted
        them (same identity-mapped objects) before the re-insert loop tried to db.add() them,
        raising InvalidRequestError. Scoping the delete itself is what makes leaving
        out-of-scope memberships untouched actually work, instead of relying on a caller
        round-tripping rows through delete+re-add.
        """
        existing = self.list_memberships(db, user_id=user_id)
        for membership in existing:
            if scope_tenant_ids is not None and membership.tenant_id not in scope_tenant_ids:
                continue
            db.delete(membership)
        db.flush()
        for membership in memberships:
            db.add(membership)
        db.flush()

    def list_memberships_batch(self, db: Session, *, user_ids: list[int]) -> list[UserTenantRole]:
        if not user_ids:
            return []
        statement = (
            select(UserTenantRole)
            .where(UserTenantRole.user_id.in_(user_ids))
            .order_by(UserTenantRole.tenant_id.asc(), UserTenantRole.user_id.asc())
        )
        return list(db.scalars(statement))

