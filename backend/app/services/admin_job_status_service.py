from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.job_registry import JOB_DEFINITIONS, JOBS_BY_NAME, JobDefinition
from app.models import SystemJobRun, SystemJobStatus
from app.schemas.admin import JobRunPage, JobRunRead, JobState, JobStatusOverview, JobStatusRead


def _job_state(definition: JobDefinition | None, row: SystemJobStatus | None, now: datetime) -> JobState:
    if row is None:
        return "never_run"
    if row.consecutive_failures > 0:
        return "failing"
    if definition is not None:
        # Lebenszeichen = letzter abgeschlossener Lauf oder Heartbeat; ein laufender Job zählt
        # ab seinem Start, damit ein langer, aber gesunder Lauf nicht als überfällig erscheint.
        activity = [row.last_finished_at, row.last_heartbeat_at]
        if row.last_status == "running":
            activity.append(row.last_started_at)
        last_activity = max((value for value in activity if value is not None), default=None)
        if last_activity is None or now - last_activity > timedelta(seconds=definition.max_silence_seconds):
            return "overdue"
    if row.last_status == "running":
        return "running"
    return "ok"


class AdminJobStatusService:
    """Lesezugriff für /admin/jobs: Soll-Zustand aus job_registry.py, Ist-Zustand aus
    system_job_status (geschrieben über die SQL-Funktionen aus Migration 0105)."""

    def get_overview(self, db: Session, *, now: datetime | None = None) -> JobStatusOverview:
        now = now or datetime.now(timezone.utc)
        rows = {row.job_name: row for row in db.scalars(select(SystemJobStatus))}

        items = [self._to_read(definition.name, definition, rows.get(definition.name), now) for definition in JOB_DEFINITIONS]
        # Meldende, aber nicht registrierte Jobs (z. B. ein neuer Host-Cronjob) trotzdem zeigen.
        items.extend(
            self._to_read(name, None, rows[name], now) for name in sorted(rows) if name not in JOBS_BY_NAME
        )
        return JobStatusOverview(items=items, generated_at=now)

    def list_runs(self, db: Session, *, job_name: str, limit: int, offset: int) -> JobRunPage:
        total = db.scalar(select(func.count()).select_from(SystemJobRun).where(SystemJobRun.job_name == job_name)) or 0
        runs = db.scalars(
            select(SystemJobRun)
            .where(SystemJobRun.job_name == job_name)
            .order_by(SystemJobRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return JobRunPage(
            items=[
                JobRunRead(
                    id=run.id,
                    status=run.status,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    duration_ms=run.duration_ms,
                    error=run.error,
                )
                for run in runs
            ],
            total=total,
        )

    def cleanup_old_runs(self, db: Session, *, retention_days: int) -> dict:
        """Retention für den Verlauf (siehe main.py's log_cleanup_loop)."""
        cutoff = func.now() - timedelta(days=retention_days)
        deleted = db.query(SystemJobRun).filter(SystemJobRun.finished_at < cutoff).delete(synchronize_session=False)
        db.commit()
        return {"deleted": deleted}

    def _to_read(self, name: str, definition: JobDefinition | None, row: SystemJobStatus | None, now: datetime) -> JobStatusRead:
        return JobStatusRead(
            name=name,
            registered=definition is not None,
            kind=definition.kind if definition else None,
            service=definition.service if definition else None,
            category=definition.category if definition else None,
            interval_seconds=definition.interval_seconds if definition else None,
            max_silence_seconds=definition.max_silence_seconds if definition else None,
            state=_job_state(definition, row, now),
            last_status=row.last_status if row else None,
            last_started_at=row.last_started_at if row else None,
            last_finished_at=row.last_finished_at if row else None,
            last_success_at=row.last_success_at if row else None,
            last_failure_at=row.last_failure_at if row else None,
            last_heartbeat_at=row.last_heartbeat_at if row else None,
            last_duration_ms=row.last_duration_ms if row else None,
            last_error=row.last_error if row else None,
            consecutive_failures=row.consecutive_failures if row else 0,
            run_count=row.run_count if row else 0,
            failure_count=row.failure_count if row else 0,
        )
