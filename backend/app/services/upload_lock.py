"""Serialize upload decisions through commit, across services and worker processes.

The namespace is shared with abgabebox-backend/app/db.py and the existing internal
quota lock. Async callers poll a nonblocking Postgres lock so the first uploader can
keep running on the same event loop while a second request waits.
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.orm import Session

UPLOAD_LOCK_NAMESPACE = 909100001


async def acquire_upload_lock(db: Session, tenant_id: int) -> None:
    while not db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:ns, :tenant_id)"),
        {"ns": UPLOAD_LOCK_NAMESPACE, "tenant_id": tenant_id},
    ):
        await asyncio.sleep(0.05)


def acquire_upload_lock_sync(db: Session, tenant_id: int) -> None:
    """For the Word-import worker thread; released by its caller's commit/rollback."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :tenant_id)"),
        {"ns": UPLOAD_LOCK_NAMESPACE, "tenant_id": tenant_id},
    )
