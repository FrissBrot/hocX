"""Serialize upload decisions through commit, across services and worker processes.

The namespace is shared with abgabebox-backend/app/db.py and the existing internal
quota lock.

Gewartet wird blockierend, aber begrenzt (Concurrency-Audit CONC-008): vorher pollten die
async-Aufrufer alle 50 ms ohne Obergrenze im Event-Loop. Alle Aufrufer laufen heute in einem
Worker-Thread (core/offload.py, Galerie-Ingest, Word-Import). Interaktive Uploads warten höchstens
INTERACTIVE_TIMEOUT_SECONDS und bekommen danach 503 mit Retry-After (main.py,
upload_lock_busy_handler); Hintergrundjobs warten länger.
"""
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

UPLOAD_LOCK_NAMESPACE = 909100001
INTERACTIVE_TIMEOUT_SECONDS = 30
BACKGROUND_TIMEOUT_SECONDS = 600


class UploadLockBusy(Exception):
    """Der Upload-Lock des Mandanten war nicht rechtzeitig frei (erwartet, kein Fehlerprotokoll)."""

    retry_after_seconds = 10


def acquire_upload_lock_sync(db: Session, tenant_id: int, *, timeout_seconds: int = INTERACTIVE_TIMEOUT_SECONDS) -> None:
    """Released by the caller's commit/rollback (transaction-scoped)."""
    previous = db.scalar(text("SELECT current_setting('lock_timeout')"))
    db.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": f"{timeout_seconds}s"})
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :tenant_id)"),
            {"ns": UPLOAD_LOCK_NAMESPACE, "tenant_id": tenant_id},
        )
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03":  # lock_not_available
            db.rollback()
            raise UploadLockBusy() from exc
        raise
    # Die Obergrenze gilt nur für das Warten auf diesen Lock, nicht für die übrige Transaktion.
    db.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": previous})


async def acquire_upload_lock(db: Session, tenant_id: int, *, timeout_seconds: int = INTERACTIVE_TIMEOUT_SECONDS) -> None:  # loop-ok: nur im Worker-Thread (core/offload.run_coroutine_in_thread bzw. Galerie-Ingest)
    acquire_upload_lock_sync(db, tenant_id, timeout_seconds=timeout_seconds)
