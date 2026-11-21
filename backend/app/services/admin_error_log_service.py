from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sqlalchemy.orm import aliased

from app.models import AppUser, PlatformAdmin, SystemErrorLog, Tenant
from app.schemas.admin import SystemErrorLogFilterOptions, SystemErrorLogGroup, SystemErrorLogPage, SystemErrorLogRead
from app.services import public_id_service

DEFAULT_PAGE_SIZE = 50
_TZ = ZoneInfo("Europe/Zurich")


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_TZ)


def _apply_filters(query, *, tenant_id, error_type, source, date_from: date | None, date_to: date | None):
    """Gemeinsame Filter für Liste und Gruppenansicht. Zeitraum in Schweizer Kalendertagen,
    ``date_to`` inklusive (Index idx_system_error_log_created)."""
    if tenant_id is not None:
        query = query.filter(SystemErrorLog.tenant_id == tenant_id)
    if error_type is not None:
        query = query.filter(SystemErrorLog.error_type == error_type)
    if source is not None:
        query = query.filter(SystemErrorLog.source == source)
    if date_from is not None:
        query = query.filter(SystemErrorLog.created_at >= _day_start(date_from))
    if date_to is not None:
        query = query.filter(SystemErrorLog.created_at < _day_start(date_to + timedelta(days=1)))
    return query


class AdminErrorLogService:
    """Read access to system_error_log for the platform-admin panel - unscoped by design."""

    def list_errors(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        error_type: str | None = None,
        source: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> SystemErrorLogPage:
        # Akteur über die ID auflösen (0139, PRIV-002): ist das Konto gelöscht, bleibt das Feld leer.
        actor_user = aliased(AppUser)
        actor_admin = aliased(PlatformAdmin)
        query = (
            db.query(SystemErrorLog, Tenant.name, actor_user.email, actor_admin.email)
            .outerjoin(Tenant, SystemErrorLog.tenant_id == Tenant.id)
            .outerjoin(actor_user, SystemErrorLog.actor_user_id == actor_user.id)
            .outerjoin(actor_admin, SystemErrorLog.actor_admin_id == actor_admin.id)
        )
        query = _apply_filters(query, tenant_id=tenant_id, error_type=error_type, source=source, date_from=date_from, date_to=date_to)

        total = query.count()
        rows = query.order_by(SystemErrorLog.created_at.desc()).limit(limit).offset(offset).all()
        items = [
            SystemErrorLogRead(
                id=entry.public_id,
                source=entry.source,
                tenant_id=public_id_service.resolve_public_id(db, Tenant, entry.tenant_id) if entry.tenant_id is not None else None,
                tenant_name=tenant_name,
                actor_email=user_email or admin_email or entry.actor_email,
                request_method=entry.request_method,
                request_path=entry.request_path,
                status_code=entry.status_code,
                error_type=entry.error_type,
                error_message=entry.error_message,
                traceback=entry.traceback,
                created_at=entry.created_at,
            )
            for entry, tenant_name, user_email, admin_email in rows
        ]
        return SystemErrorLogPage(items=items, total=total)

    def group_errors(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        source: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> list[SystemErrorLogGroup]:
        """Gruppenansicht: Fehlertyp × Anzahl × betroffene Mandanten × zuletzt - nur Zählwerte,
        keine Meldungen/Tracebacks."""
        query = db.query(
            SystemErrorLog.error_type,
            func.count(SystemErrorLog.id),
            func.count(func.distinct(SystemErrorLog.tenant_id)),
            func.min(SystemErrorLog.created_at),
            func.max(SystemErrorLog.created_at),
        )
        query = _apply_filters(query, tenant_id=tenant_id, error_type=None, source=source, date_from=date_from, date_to=date_to)
        rows = query.group_by(SystemErrorLog.error_type).order_by(func.count(SystemErrorLog.id).desc(), SystemErrorLog.error_type).limit(limit).all()
        return [
            SystemErrorLogGroup(error_type=error_type, count=count, tenants=tenants, first_at=first_at, last_at=last_at)
            for error_type, count, tenants, first_at, last_at in rows
        ]

    def filter_options(self, db: Session) -> SystemErrorLogFilterOptions:
        error_types = [row[0] for row in db.execute(select(SystemErrorLog.error_type).distinct().order_by(SystemErrorLog.error_type)).all()]
        sources = [row[0] for row in db.execute(select(SystemErrorLog.source).distinct().order_by(SystemErrorLog.source)).all()]
        return SystemErrorLogFilterOptions(error_types=error_types, sources=sources)

    def cleanup_old_entries(self, db: Session, *, retention_days: int) -> dict:
        """Periodic retention sweep (see main.py's log_cleanup_loop) - system_error_log had
        no cleanup at all before this (audit finding, 2026-08-26), so it grew unbounded
        forever."""
        cutoff = func.now() - timedelta(days=retention_days)
        deleted = db.query(SystemErrorLog).filter(SystemErrorLog.created_at < cutoff).delete(synchronize_session=False)
        db.commit()
        return {"deleted": deleted}
