"""PDF-Export als Auftrag (Concurrency-Audit CONC-003/-004/-019/-020, Migration 0150).

POST /documents/render legt einen Auftrag an und antwortet sofort (202); der job-worker rendert
ihn, das Frontend fragt GET /documents/render-jobs/{id} ab und meldet "PDF bereit". Vorteile
gegenüber dem Rendern im Request:

- keine DB-Verbindung über Warteschlange und Compile in den uvicorn-Workern,
- die Typst-Compile-Slots der Backend-Worker bleiben für die interaktive Vorschau frei,
- Fairness: wartende Aufträge werden reihum je Mandant vergeben (Mandanten mit laufenden
  Aufträgen hinten an), je Protokoll höchstens ein laufender Auftrag (keine doppelten
  Versionsnummern, CONC-019),
- dauerhaft: das Auto-PDF nach dem Abschliessen überlebt Neustarts und wird bei vorübergehenden
  Fehlern (Compile-Platz belegt, Timeout, Speicher) wiederholt.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import CurrentUser, build_current_user
from app.core.tenant_scope import bind_tenant_scope

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Ein Auftrag, der so lange "running" bleibt, ist mit seinem Prozess gestorben (Neustart, OOM).
STALE_RUNNING = timedelta(minutes=15)
POLL_SECONDS = 1.0
# Vorübergehende Renderfehler: erneut versuchen statt den Auftrag aufzugeben.
_RETRYABLE_RENDER_KEYS = {"error.busy", "error.timeout", "error.render"}


def _model():
    from app.models.document_entities import DocumentRenderJob

    return DocumentRenderJob


def enqueue(db: Session, *, tenant_id: int, user_id: int | None, request_json: dict[str, Any], protocol_id: int | None):
    """Neuen Auftrag anlegen. Ein gleicher offener Auftrag desselben Nutzers (Doppelklick, zwei
    Tabs) wird wiederverwendet statt ein zweites PDF zu erzeugen."""
    job_model = _model()
    existing = db.scalars(
        select(job_model).where(
            job_model.tenant_id == tenant_id,
            job_model.requested_by.is_(None) if user_id is None else job_model.requested_by == user_id,
            job_model.status.in_(("queued", "running")),
            job_model.request_json == request_json,
        )
    ).first()
    if existing is not None:
        return existing
    job = job_model(tenant_id=tenant_id, requested_by=user_id, protocol_id=protocol_id, request_json=request_json)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_protocol_pdf(db: Session, *, protocol) -> None:
    """Auto-PDF nach dem Abschliessen (vorher BackgroundTask im Request-Prozess)."""
    enqueue(
        db,
        tenant_id=protocol.tenant_id,
        user_id=None,
        request_json={"protocol_id": str(protocol.public_id), "document_type": "protocol"},
        protocol_id=protocol.id,
    )


def get_job(db: Session, job_id: uuid.UUID, *, tenant_id: int, user_id: int):
    """Nur eigene Aufträge im eigenen Mandanten (gleiche Antwort für fremde und fehlende)."""
    job_model = _model()
    return db.scalars(
        select(job_model).where(job_model.id == job_id, job_model.tenant_id == tenant_id, job_model.requested_by == user_id)
    ).first()


# ── Verarbeitung (job-worker) ──────────────────────────────────────────────────────────────


def _recover_stale(db: Session) -> None:
    db.execute(
        text("""
            UPDATE document_render_job SET status = 'queued', started_at = NULL
            WHERE status = 'running' AND started_at < :cutoff AND attempts < :max_attempts
        """),
        {"cutoff": datetime.now(UTC) - STALE_RUNNING, "max_attempts": MAX_ATTEMPTS},
    )
    db.execute(
        text("""
            UPDATE document_render_job SET status = 'failed', finished_at = NOW(), error_status = 503,
                   error = to_jsonb('timeout'::text)
            WHERE status = 'running' AND started_at < :cutoff AND attempts >= :max_attempts
        """),
        {"cutoff": datetime.now(UTC) - STALE_RUNNING, "max_attempts": MAX_ATTEMPTS},
    )
    db.commit()


def claim_next(db: Session) -> uuid.UUID | None:
    """Nächster Auftrag: Mandanten ohne laufende Aufträge zuerst, dann der älteste; nie ein
    zweiter laufender Auftrag für dasselbe Protokoll. SKIP LOCKED: mehrere job-worker-Prozesse
    können parallel ziehen."""
    row = db.execute(
        text("""
            SELECT j.id FROM document_render_job j
            WHERE j.status = 'queued'
              AND (j.protocol_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM document_render_job r WHERE r.status = 'running' AND r.protocol_id = j.protocol_id))
            ORDER BY (SELECT count(*) FROM document_render_job r WHERE r.status = 'running' AND r.tenant_id = j.tenant_id),
                     j.created_at
            LIMIT 1
            FOR UPDATE OF j SKIP LOCKED
        """)
    ).first()
    if row is None:
        db.commit()  # nur Lesezugriff - Transaktion beenden
        return None
    db.execute(
        text("UPDATE document_render_job SET status = 'running', started_at = NOW(), attempts = attempts + 1 WHERE id = :id"),
        {"id": row.id},
    )
    db.commit()
    return row.id


def _load(db: Session, job_id: uuid.UUID):
    from app.models import AppUser

    job = db.get(_model(), job_id)
    if job is None:
        return None, None
    user: CurrentUser | None = None
    if job.requested_by is not None:
        account = db.get(AppUser, job.requested_by)
        # Wie get_optional_current_user: gesperrtes Konto oder nach dem Auftrag beendete Sitzungen
        # (Passwortwechsel, Deaktivierung, MFA-Reset) -> nicht mehr in seinem Namen rendern.
        if (
            account is None
            or not account.is_active
            or not account.login_enabled
            or (account.session_revoke_at is not None and account.session_revoke_at > job.created_at)
        ):
            return job, False
        user = build_current_user(db, account, mfa_verified=True)
    # Wie ein Request des Nutzers: RLS auf den Mandanten des Auftrags (tenant_scope.py).
    bind_tenant_scope(db, job.tenant_id)
    return job, user


def _finish(db: Session, job_id: uuid.UUID, *, status: str, export_id: int | None = None, error_status: int | None = None, error: Any = None, rollback: bool = True) -> None:
    if rollback:
        db.rollback()
    db.execute(
        text("""
            UPDATE document_render_job SET status = :status, finished_at = CASE WHEN :status IN ('done', 'failed') THEN NOW() END,
                   started_at = CASE WHEN :status = 'queued' THEN NULL ELSE started_at END,
                   export_id = COALESCE(:export_id, export_id), error_status = :error_status, error = CAST(:error AS jsonb)
            WHERE id = :id
        """),
        {"status": status, "export_id": export_id, "error_status": error_status, "error": None if error is None else _json(error), "id": job_id},
    )
    db.commit()


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


async def run_job(job_id: uuid.UUID, *, db: Session | None = None) -> None:
    """Einen Auftrag rendern. Fehler werden wie bisher von der Route übersetzt (render_error,
    http_error) und am Auftrag gespeichert; vorübergehende Fehler kommen zurück in die Warteschlange.
    db: nur für Tests (gemeinsame Session mit der Test-Fixture, ohne eigenen Rollback)."""
    from app.api.routes.documents import http_error, render_error
    from app.core.error_log import record_system_error
    from app.documents import service as document_service
    from app.documents.context import DocumentNotFoundError, DocumentPermissionError
    from app.documents.renderer import DocumentRenderError

    own_session = db is None
    db = db if db is not None else SessionLocal()

    def finish(**kwargs) -> Any:
        return run_in_threadpool(lambda: _finish(db, job_id, rollback=own_session, **kwargs))

    try:
        job, user = await run_in_threadpool(_load, db, job_id)
        if job is None:
            return
        if user is False:
            await finish(status="failed", error_status=403, error="account_inactive")
            return
        attempts = job.attempts
        try:
            request = document_service.DocumentRequest.model_validate(job.request_json)
            result = await document_service.render(db, user, job.tenant_id, request)
        except DocumentRenderError as exc:
            if exc.key in _RETRYABLE_RENDER_KEYS and attempts < MAX_ATTEMPTS:
                await finish(status="queued")
                return
            failure = render_error(user, exc) if user is not None else None
            await finish(status="failed", error_status=failure.status_code if failure else 500, error=failure.detail if failure else exc.key)
            if exc.key not in ("error.block",):
                await run_in_threadpool(lambda: record_system_error(db, exc=exc, tenant_id=job.tenant_id))
            return
        except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
            failure = http_error(user, exc) if user is not None else None
            await finish(status="failed", error_status=failure.status_code if failure else 422, error=failure.detail if failure else str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - Auftrag nicht verlieren, Fehler protokollieren
            _logger.exception("PDF-Auftrag %s fehlgeschlagen", job_id)
            await run_in_threadpool(lambda: (db.rollback() if own_session else None, record_system_error(db, exc=exc, tenant_id=job.tenant_id)))
            await finish(status="queued" if attempts < MAX_ATTEMPTS else "failed", error_status=500, error="render_failed")
            return
        def audit_done() -> None:
            from app.services.audit_service import AuditService

            export = result.export
            AuditService().log(
                db,
                action="document.render",
                actor=user if user else None,
                tenant_id=job.tenant_id,
                entity_type="document_export",
                entity_id=export.id,
                details={
                    "document_type": export.document_type,
                    "version": export.version_label,
                    "protocol_id": job.request_json.get("protocol_id"),
                    "template_id": job.request_json.get("template_id"),
                },
            )

        await finish(status="done", export_id=result.export.id)
        await run_in_threadpool(audit_done)
    finally:
        if own_session:
            await run_in_threadpool(db.close)


async def document_render_loop() -> None:
    """Läuft im job-worker: zieht Aufträge, höchstens document_render_concurrency gleichzeitig."""
    concurrency = max(1, settings.document_render_concurrency)
    running: set[asyncio.Task] = set()
    last_recovery = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            if loop.time() - last_recovery > 60:
                await run_in_threadpool(_with_session, _recover_stale)
                last_recovery = loop.time()
            while len(running) < concurrency:
                job_id = await run_in_threadpool(_with_session, claim_next)
                if job_id is None:
                    break
                task = asyncio.create_task(run_job(job_id))
                running.add(task)
                task.add_done_callback(running.discard)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("PDF-Auftragsschleife: Durchlauf fehlgeschlagen")
        await asyncio.sleep(POLL_SECONDS)


def _with_session(fn):
    with SessionLocal() as db:
        return fn(db)
