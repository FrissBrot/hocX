from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SystemErrorLog, Tenant
from app.schemas.admin import SystemErrorLogFilterOptions, SystemErrorLogPage, SystemErrorLogRead
from app.services import public_id_service

DEFAULT_PAGE_SIZE = 50


class AdminErrorLogService:
    """Read access to system_error_log for the platform-admin panel - unscoped by design."""

    def list_errors(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        error_type: str | None = None,
        source: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> SystemErrorLogPage:
        query = db.query(SystemErrorLog, Tenant.name).outerjoin(Tenant, SystemErrorLog.tenant_id == Tenant.id)
        if tenant_id is not None:
            query = query.filter(SystemErrorLog.tenant_id == tenant_id)
        if error_type is not None:
            query = query.filter(SystemErrorLog.error_type == error_type)
        if source is not None:
            query = query.filter(SystemErrorLog.source == source)

        total = query.count()
        rows = query.order_by(SystemErrorLog.created_at.desc()).limit(limit).offset(offset).all()
        items = [
            SystemErrorLogRead(
                id=entry.public_id,
                source=entry.source,
                tenant_id=public_id_service.resolve_public_id(db, Tenant, entry.tenant_id) if entry.tenant_id is not None else None,
                tenant_name=tenant_name,
                actor_email=entry.actor_email,
                request_method=entry.request_method,
                request_path=entry.request_path,
                status_code=entry.status_code,
                error_type=entry.error_type,
                error_message=entry.error_message,
                traceback=entry.traceback,
                created_at=entry.created_at,
            )
            for entry, tenant_name in rows
        ]
        return SystemErrorLogPage(items=items, total=total)

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
