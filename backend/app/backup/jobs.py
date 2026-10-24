"""Persistente Aufträge des Backup-Workers: Lease mit Fencing-Token, Heartbeat, Zustände,
Ereignisse - gleiches Muster wie der Storage-Migrations-Worker (storage_worker.py).

Jede Änderung eines Auftrags durch den Worker prüft das Fencing-Token; wer seine Lease verloren
hat (zweiter Worker, Admin-Abbruch nach Lease-Ablauf), schreibt nichts mehr (LeaseLost)."""

from __future__ import annotations

import logging
import random
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import BackupEvent, BackupJob, BackupRestoreJob

_logger = logging.getLogger("hocx.backup.jobs")

LEASE_SECONDS = 90
WAIT_OWNER = "wait"
MAX_ATTEMPTS = 6
TERMINAL_JOB_STATES = ("completed", "partial", "failed", "cancelled", "interrupted")
OPEN_JOB_STATES = ("queued", "preparing", "running", "verifying")
TERMINAL_RESTORE_STATES = ("completed", "failed", "cancelled", "interrupted", "rolled_back")
OPEN_RESTORE_STATES = ("queued", "preparing", "running", "verifying", "cutover")
# Zustände, in denen ein Abbruch keinen inkonsistenten Zustand hinterlässt.
RESTORE_CANCELLABLE = ("queued", "preparing", "running", "verifying")


class LeaseLost(Exception):
    pass


class JobCancelled(Exception):
    pass


class JobWait(Exception):
    """Der Auftrag wartet auf etwas Externes (Fence, Migration) - später erneut."""

    def __init__(self, seconds: float, reason: str) -> None:
        super().__init__(reason)
        self.seconds = seconds
        self.reason = reason


class JobFailure(Exception):
    """Kuratierter Fehler mit stabilem Code (Anzeige, ntfy, Übersetzung im Frontend)."""

    def __init__(self, code: str, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient


def backoff_seconds(attempt: int, *, base: float = 60.0, cap: float = 3600.0) -> float:
    return random.uniform(base / 2, min(cap, base * (2 ** max(0, attempt - 1))))


@dataclass
class JobCtx:
    model: type
    job_id: uuid.UUID
    token: int
    owner: str
    resumed: bool
    lost: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    cancel: threading.Event = field(default_factory=threading.Event)
    engine: Any = None

    def check(self) -> None:
        if self.lost.is_set():
            raise LeaseLost()
        if self.cancel.is_set():
            raise JobCancelled()


def claim(engine: Any, model: type, owner: str) -> JobCtx | None:
    """Übernimmt höchstens einen Auftrag: neu (queued, fällig) oder unterbrochen (offen mit
    abgelaufener Lease - Worker-Absturz/Neustart). SKIP LOCKED: zwei Worker nie gleichzeitig."""
    open_states = OPEN_RESTORE_STATES if model is BackupRestoreJob else OPEN_JOB_STATES
    running = [state for state in open_states if state != "queued"]
    order = [model.created_at] if model is BackupRestoreJob else [
        case((model.kind == "backup", 0), (model.kind == "retention", 1), else_=2), model.created_at,
    ]
    now = func.now()
    candidate = (
        select(model.id, model.lease_owner.label("previous_owner"))
        .where(or_(
            and_(model.state == "queued", or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now)),
            and_(model.state.in_(running), or_(model.lease_expires_at.is_(None), model.lease_expires_at < now)),
        ))
        .order_by(*order)
        .limit(1)
        .with_for_update(skip_locked=True)
        .cte("candidate")
    )
    statement = (
        update(model)
        .where(model.id == candidate.c.id)
        .values(
            lease_owner=owner, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            fencing_token=model.fencing_token + 1, heartbeat_at=now, updated_at=now,
            started_at=func.coalesce(model.started_at, now),
        )
        .returning(model.id, model.fencing_token, model.state, candidate.c.previous_owner)
    )
    with engine.begin() as conn:
        row = conn.execute(statement).first()
    if row is None:
        return None
    # Ein offener Auftrag ohne gültige Lease wurde unterbrochen (Absturz/Neustart) - ausser er hat
    # bewusst gewartet (wait_later setzt den Marker WAIT_OWNER).
    resumed = row.state != "queued" and row.previous_owner != WAIT_OWNER
    return JobCtx(model=model, job_id=row.id, token=row.fencing_token, owner=owner, resumed=resumed, engine=engine)


def wait_later(db: Session, ctx: JobCtx, *, seconds: float, reason: str) -> None:
    """Gibt den Auftrag für eine Weile ab, ohne seinen Zustand zu ändern."""
    guarded(db, ctx, lease_owner=WAIT_OWNER, lease_expires_at=datetime.now(UTC) + timedelta(seconds=seconds))
    job = load(db, ctx)
    progress_values = {**(job.progress or {}), "waiting_for": reason}
    guarded(db, ctx, progress=progress_values)
    db.commit()


def renew(ctx: JobCtx) -> bool:
    model = ctx.model
    statement = (
        update(model)
        .where(model.id == ctx.job_id, model.fencing_token == ctx.token, model.lease_owner == ctx.owner)
        .values(lease_expires_at=func.now() + timedelta(seconds=LEASE_SECONDS), heartbeat_at=func.now())
        .returning(model.cancel_requested)
    )
    with ctx.engine.begin() as conn:
        row = conn.execute(statement).first()
    if row is None:
        return False
    if row.cancel_requested:
        ctx.cancel.set()
    return True


def release(ctx: JobCtx) -> None:
    model = ctx.model
    with ctx.engine.begin() as conn:
        conn.execute(
            update(model)
            .where(model.id == ctx.job_id, model.fencing_token == ctx.token)
            .values(lease_owner=None, lease_expires_at=None)
        )


def heartbeat_loop(ctx: JobCtx, extra: Callable[[], None] | None = None) -> None:
    while not ctx.stop.wait(LEASE_SECONDS / 4):
        try:
            if not renew(ctx):
                ctx.lost.set()
                return
            if extra is not None:
                extra()
        except Exception:  # DB kurz weg: Lease läuft notfalls ab, das Fencing schützt die Daten
            _logger.warning("Lease-Verlängerung fehlgeschlagen", exc_info=True)


def guarded(db: Session, ctx: JobCtx, **values: Any) -> None:
    values["updated_at"] = datetime.now(UTC)
    result = db.execute(update(ctx.model).where(ctx.model.id == ctx.job_id, ctx.model.fencing_token == ctx.token).values(**values))
    if not result.rowcount:
        db.rollback()
        raise LeaseLost()


def load(db: Session, ctx: JobCtx) -> Any:
    job = db.get(ctx.model, ctx.job_id, populate_existing=True)
    if job is None or job.fencing_token != ctx.token:
        raise LeaseLost()
    return job


def event(db: Session, ctx_or_job: Any, kind: str, message: str | None = None, *, level: str = "info",
          actor_email: str | None = None, **details: Any) -> None:
    model = ctx_or_job.model if isinstance(ctx_or_job, JobCtx) else type(ctx_or_job)
    job_id = ctx_or_job.job_id if isinstance(ctx_or_job, JobCtx) else ctx_or_job.id
    db.add(BackupEvent(
        job_id=job_id if model is BackupJob else None,
        restore_job_id=job_id if model is BackupRestoreJob else None,
        level=level, kind=kind, message=(message or "")[:2000] or None, actor_email=actor_email,
        details={k: (str(v) if isinstance(v, (uuid.UUID, datetime)) else v) for k, v in details.items()},
    ))


def set_state(db: Session, ctx: JobCtx, state: str, *, message: str | None = None, level: str = "info", **values: Any) -> None:
    terminal = state in (TERMINAL_RESTORE_STATES if ctx.model is BackupRestoreJob else TERMINAL_JOB_STATES)
    if terminal:
        values.setdefault("finished_at", datetime.now(UTC))
        values.setdefault("lease_owner", None)
        values.setdefault("lease_expires_at", None)
    guarded(db, ctx, state=state, **values)
    event(db, ctx, "state", message, level=level, state=state)
    db.commit()


def progress(db: Session, ctx: JobCtx, **values: Any) -> None:
    job = load(db, ctx)
    guarded(db, ctx, progress={**(job.progress or {}), **values, "updated_at": datetime.now(UTC).isoformat()})
    db.commit()


def checkpoint(db: Session, ctx: JobCtx, **values: Any) -> dict[str, Any]:
    job = load(db, ctx)
    merged = {**(job.checkpoint or {}), **values}
    guarded(db, ctx, checkpoint=merged)
    db.commit()
    return merged


def retry_later(db: Session, ctx: JobCtx, *, seconds: float, code: str, message: str) -> None:
    guarded(db, ctx, state="queued", next_attempt_at=datetime.now(UTC) + timedelta(seconds=seconds),
            error_code=code, error_message=message[:2000], lease_owner=None, lease_expires_at=None)
    event(db, ctx, "retry", message, level="warning", code=code, delay_seconds=int(seconds))
    db.commit()
