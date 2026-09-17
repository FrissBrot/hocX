import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api.routes import admin, admin_auth, auth, collaboration_ws, cycle_configs, document_templates, events, exports, files, finance, fines, lists, participants, protocol_elements, protocols, statistics, storage, submission_assignments, table_snapshots, tag_config, templates, tenants, todos, users, word_import
from app.core.background_loops import BACKGROUND_LOCK_IDS, run_advisory_locked_loop
from app.core.db import SessionLocal
from app.core.config import settings
from app.core.error_log import best_effort_actor_from_request, record_system_error
from app.core.redis_client import close_redis_pool
from app.core.security import hash_password
from app.models import AppUser, ElementType, PlatformAdmin, Role, Tenant
from app.services import domain_health_check_service, traefik_config_service
from app.services.admin_error_log_service import AdminErrorLogService
from app.services.audit_service import AuditService
from app.services.submission_service import SubmissionService
from app.services.document_template_service import DocumentTemplateService
from app.services.export_service import ExportService
from app.services.file_service import FileService
from app.services.isolated_parse import warm_up_pool as warm_up_word_import_parse_pool
from app.services import photo_album_service
from app.services.table_snapshot_service import TableSnapshotService, run_due_cycle_snapshots


def ensure_roles() -> None:
    with SessionLocal() as db:
        existing = set(db.scalars(select(Role.code)))
        desired = [
            (2, "admin", "Tenant administrator"),
            (3, "writer", "Workspace write access"),
            (4, "reader", "Read-only access to finalized protocols and own todos/fines"),
            (5, "kassier", "Reader access plus full finance and fines management"),
        ]
        changed = False
        for role_id, code, description in desired:
            if code in existing:
                continue
            db.add(Role(id=role_id, code=code, description=description))
            changed = True
        if changed:
            db.commit()


def ensure_platform_admin_bootstrap() -> None:
    """Creates the first platform-admin account from env vars if the table is still empty.

    Deliberate one-time bootstrap instead of a hardcoded seed password: operators set
    INITIAL_ADMIN_EMAIL/INITIAL_ADMIN_PASSWORD before the first deploy, then manage
    further admins through the panel itself.
    """
    if not settings.initial_admin_email or not settings.initial_admin_password:
        return
    with SessionLocal() as db:
        if db.query(PlatformAdmin).first() is not None:
            return
        db.add(
            PlatformAdmin(
                email=settings.initial_admin_email,
                password_hash=hash_password(settings.initial_admin_password),
                display_name="Admin",
                is_active=True,
            )
        )
        db.commit()


def ensure_no_production_demo_data() -> None:
    """Fail closed if legacy/accidentally seeded demo identities remain in production."""
    if not settings.is_production:
        return
    demo_emails = {
        "superadmin@hocx.local",
        "admin@hocx.local",
        "writer@hocx.local",
        "reader@hocx.local",
    }
    with SessionLocal() as db:
        active = set(
            db.scalars(
                select(AppUser.email).where(
                    AppUser.is_active.is_(True),
                    AppUser.email.in_(demo_emails),
                )
            )
        )
        demo_tenants = set(
            db.scalars(
                select(Tenant.name).where(
                    Tenant.name.in_({"hocX Workspace", "Regional Workspace"})
                )
            )
        )
    if active or demo_tenants:
        raise RuntimeError(
            "Production startup blocked: local demo identities exist: accounts="
            + ",".join(sorted(active))
            + "; tenants="
            + ",".join(sorted(demo_tenants))
        )


def ensure_startup_seed_data() -> None:
    """Runs the idempotent startup seed functions under an advisory lock so that a
    fresh database being seeded by multiple concurrent uvicorn workers (--workers 2)
    can't race on the same check-then-insert (e.g. two workers both seeing an empty
    platform_admin table and both trying to insert the bootstrap admin)."""
    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_lock(202600004)"))
        try:
            ensure_roles()
            ensure_platform_admin_bootstrap()
            ensure_lookup_values()
        finally:
            db.execute(text("SELECT pg_advisory_unlock(202600004)"))


def ensure_lookup_values() -> None:
    with SessionLocal() as db:
        existing_codes = set(db.scalars(select(ElementType.code)))
        desired = [
            ("text", "Editable text"),
            ("todo", "Todo element"),
            ("image", "Image element"),
            ("display", "Read-only display element"),
            ("static_text", "Static text element"),
            ("form", "Structured form block"),
            ("event_list", "Filtered event list"),
            ("bullet_list", "Bullet point list"),
            ("attendance", "Attendance control block"),
            ("session_date", "Next session date block"),
            ("matrix", "Responsive matrix block"),
            ("finance_balance", "Finance account balance"),
            ("finance_transactions", "Finance transaction table"),
            ("fine_list", "Attendance fine list"),
            ("chart", "Statistics chart block"),
        ]
        changed = False
        next_id = int(max(db.scalars(select(ElementType.id)).all() or [0]))
        for code, description in desired:
            if code in existing_codes:
                continue
            next_id += 1
            db.add(ElementType(id=next_id, code=code, description=description))
            changed = True
        if changed:
            db.commit()


def ensure_runtime_columns() -> None:
    # All schema changes are now managed via Alembic (alembic upgrade head runs before uvicorn).
    # This function is kept as a no-op for backwards compatibility.
    pass


def ensure_default_document_templates() -> None:
    service = DocumentTemplateService()
    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_lock(202600002)"))
        try:
            tenants = list(db.scalars(select(Tenant).order_by(Tenant.id.asc())))
            for tenant in tenants:
                service.ensure_default_template_for_tenant(db, tenant.id, tenant.name)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(202600002)"))


def ensure_traefik_dynamic_config() -> None:
    with SessionLocal() as db:
        traefik_config_service.regenerate(db)


async def domain_health_check_loop() -> None:
    """Re-checks active custom domains on an interval. Runs in every uvicorn worker (there's no
    single-instance process in this deployment), so each tick is guarded by a Postgres advisory
    lock - only the worker that acquires it does the check, the other(s) skip that tick."""
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["domain_health_check"],
        interval_seconds=settings.domain_health_check_interval_minutes * 60,
        task=domain_health_check_service.run_health_check,
    )


async def abgabebox_rescan_loop() -> None:
    """Periodic sweep for submission_upload files stuck in scan_status='pending' (ClamAV was
    unreachable at upload time - see abgabebox-backend/app/scanner.py's fail-open comment).
    Same every-worker-but-advisory-locked pattern as domain_health_check_loop above. Stays
    separate from upload_pipeline_rescan_loop below - unlike the three internal upload paths,
    abgabebox files that are still pending sit in a quarantine directory the restricted
    abgabebox DB role can't itself move them out of, so this needs SubmissionService's own
    move-from-quarantine logic, not FileService's."""
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["abgabebox_rescan"],
        interval_seconds=settings.abgabebox_rescan_interval_minutes * 60,
        task=SubmissionService().rescan_all_pending,
    )


async def upload_pipeline_rescan_loop() -> None:
    """Periodic sweep for the three internal upload paths' (protocol image, gallery upload,
    word import) StoredFile rows stuck in scan_status='pending' (ClamAV was unreachable at
    upload time). One consolidated loop instead of three near-identical ones - see
    FileService.rescan_pending_internal_files and the upload-pipeline unification plan."""
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["upload_pipeline_rescan"],
        interval_seconds=settings.upload_pipeline_rescan_interval_minutes * 60,
        task=FileService().rescan_pending_internal_files,
    )


async def export_cleanup_loop() -> None:
    """Periodic retention sweep for old generated export files under EXPORT_ROOT/generated
    (see export_service.py's cleanup_old_generated_exports). Unlike the rescan loops above
    this isn't a stuck/pending-state repair, just age-based deletion - every export run
    writes a brand-new uuid-suffixed file and never reuses an old one, so without this the
    directory grows unbounded on repeated re-exports. Same every-worker-but-advisory-locked
    pattern as the loops above."""
    export_service = ExportService()
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["export_cleanup"],
        interval_seconds=settings.export_cleanup_interval_minutes * 60,
        task=lambda _db: export_service.cleanup_old_generated_exports(),
    )


async def log_cleanup_loop() -> None:
    """Periodic retention sweep for audit_log/system_error_log (audit finding, 2026-08-26:
    neither table had any cleanup, both grew unbounded forever - unlike the export cleanup
    loop above, which already existed). Same every-worker-but-advisory-locked pattern."""
    audit_service = AuditService()
    error_log_service = AdminErrorLogService()

    def _cleanup(db) -> None:
        audit_service.cleanup_old_entries(db, retention_days=settings.audit_log_retention_days)
        error_log_service.cleanup_old_entries(db, retention_days=settings.error_log_retention_days)

    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["log_cleanup"],
        interval_seconds=settings.log_cleanup_interval_minutes * 60,
        task=_cleanup,
    )


async def cycle_snapshot_loop() -> None:
    """Daily check (see settings.cycle_snapshot_check_interval_minutes): for every
    CycleConfig, creates a table_snapshot for the most recently completed cycle if one
    doesn't exist yet (see table_snapshot_service.run_due_cycle_snapshots for the
    idempotent/self-healing boundary-crossing logic). Same every-worker-but-advisory-
    locked pattern as the loops above - lock id comes from the shared BACKGROUND_LOCK_IDS
    ledger (see app.core.background_loops), which is exactly what a 2026-09-10 incident
    (this loop's lock id copy-pasted from protocol_image_rescan_loop, never changed,
    silently starving one of the two loops every tick) argued for."""
    snapshot_service = TableSnapshotService()
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["cycle_snapshot"],
        interval_seconds=settings.cycle_snapshot_check_interval_minutes * 60,
        task=lambda db: run_due_cycle_snapshots(db, snapshot_service),
    )


def _photo_analysis_auto_queue_window_is_open() -> bool:
    hour = datetime.now(timezone.utc).hour
    start, end = settings.photo_analysis_auto_queue_start_hour, settings.photo_analysis_auto_queue_end_hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps past midnight, e.g. 22..5


def _host_load_is_low() -> bool:
    try:
        load_1min, _, _ = os.getloadavg()
    except OSError:
        # Not available on this platform (e.g. Windows) - don't block automatic queuing on
        # a check that can't run; the request-path/worker resource limits are the actual
        # backstop against overload either way.
        return True
    cpu_count = os.cpu_count() or 1
    return load_1min <= cpu_count * settings.photo_analysis_auto_queue_max_load_factor


async def photo_analysis_auto_queue_loop() -> None:
    """Automatically queues Phase 3 (face-quality) analysis for images nobody has manually
    requested it for yet (see FileService.create_pending_analysis_jobs), but only during a
    configured low-traffic UTC hour window and only when the host doesn't already look
    busy - this work competes with live request traffic and the dedicated worker container
    for the same constrained host (see photo-analysis-worker/README.md), so it must never
    fire just because it's due. Routes through run_advisory_locked_loop's should_run gate
    (2026-09-17 audit fix) instead of hand-rolling its own lock/sleep loop - previously this
    was the one loop that reimplemented that skeleton itself, which is exactly how it ended
    up missing the to_thread offload and exception isolation every other loop has."""
    file_service = FileService()
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["photo_analysis_auto_queue"],
        interval_seconds=settings.photo_analysis_auto_queue_interval_minutes * 60,
        task=file_service.create_pending_analysis_jobs,
        should_run=lambda: _photo_analysis_auto_queue_window_is_open() and _host_load_is_low(),
    )


async def photo_quality_backfill_loop() -> None:
    """Fills in sharpness_score/exposure_score for images the abgabebox submission-upload
    path never computes them for (see FileService.backfill_missing_quality_scores) - cheap
    enough per image that this runs continuously, not just in an off-peak window like
    photo_analysis_auto_queue_loop. Same every-worker-but-advisory-locked pattern."""
    file_service = FileService()
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["photo_quality_backfill"],
        interval_seconds=settings.photo_quality_backfill_interval_minutes * 60,
        task=file_service.backfill_missing_quality_scores,
    )


async def photo_album_sync_loop() -> None:
    """Folds newly-submitted (and newly removed) abgabebox submission files into their
    Zyklus/Abgabe/Abgabe-Element albums - see photo_album_service.sync_submission_uploads
    for why this can't happen inline in that public upload request. Same every-worker-but-
    advisory-locked pattern as the loops above."""
    file_service = FileService()
    await run_advisory_locked_loop(
        lock_id=BACKGROUND_LOCK_IDS["photo_album_sync"],
        interval_seconds=settings.photo_album_sync_interval_minutes * 60,
        task=lambda db: photo_album_service.sync_submission_uploads(db, file_service),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    FileService().ensure_storage()
    warm_up_word_import_parse_pool()
    ensure_runtime_columns()
    ensure_no_production_demo_data()
    ensure_startup_seed_data()
    ensure_default_document_templates()
    ensure_traefik_dynamic_config()
    health_check_task = asyncio.create_task(domain_health_check_loop())
    rescan_task = asyncio.create_task(abgabebox_rescan_loop())
    upload_pipeline_rescan_task = asyncio.create_task(upload_pipeline_rescan_loop())
    export_cleanup_task = asyncio.create_task(export_cleanup_loop())
    log_cleanup_task = asyncio.create_task(log_cleanup_loop())
    cycle_snapshot_task = asyncio.create_task(cycle_snapshot_loop())
    photo_analysis_auto_queue_task = asyncio.create_task(photo_analysis_auto_queue_loop())
    photo_quality_backfill_task = asyncio.create_task(photo_quality_backfill_loop())
    photo_album_sync_task = asyncio.create_task(photo_album_sync_loop())
    yield
    health_check_task.cancel()
    photo_analysis_auto_queue_task.cancel()
    photo_quality_backfill_task.cancel()
    photo_album_sync_task.cancel()
    rescan_task.cancel()
    upload_pipeline_rescan_task.cancel()
    export_cleanup_task.cancel()
    log_cleanup_task.cancel()
    cycle_snapshot_task.cancel()
    await close_redis_pool()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        f"https://{settings.traefik_domain}" if settings.traefik_domain else None,
    ] if o],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Cookie", "Authorization"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net for every exception a route didn't already catch itself - guarantees no
    raw error text (SQL, stack traces, internal paths) ever reaches a customer response.
    FastAPI's own HTTPException/RequestValidationError handlers are more specific and take
    precedence, so normal curated 4xx responses are unaffected by this."""
    db = SessionLocal()
    try:
        tenant_id, actor_email = best_effort_actor_from_request(db, request)
        record_system_error(db, exc=exc, request=request, tenant_id=tenant_id, actor_email=actor_email, status_code=500)
    finally:
        db.close()
    return JSONResponse(status_code=500, content={"detail": "Ein interner Fehler ist aufgetreten."})


@app.exception_handler(HTTPException)
async def logged_http_exception_handler(request: Request, exc: HTTPException):
    """Every route in this codebase follows the same convention: catch an unexpected
    exception, `raise HTTPException(..., detail="<curated message>") from exc`. That already
    keeps raw error text out of the response - but none of those ~80 call sites persist the
    original exception anywhere. Rather than threading `record_system_error` through each of
    them individually, this hooks the one place they all funnel through: if an HTTPException
    carries a chained cause that isn't a ValueError (this codebase's convention for expected,
    already-safe-to-show validation messages), it's an unexpected error worth recording. The
    response itself is untouched - delegates to FastAPI's default handler unchanged."""
    if exc.status_code >= 400 and exc.__cause__ is not None and not isinstance(exc.__cause__, ValueError):
        db = SessionLocal()
        try:
            tenant_id, actor_email = best_effort_actor_from_request(db, request)
            record_system_error(db, exc=exc.__cause__, request=request, tenant_id=tenant_id, actor_email=actor_email, status_code=exc.status_code)
        finally:
            db.close()
    return await http_exception_handler(request, exc)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_auth.router, prefix="/api/admin/auth", tags=["admin-auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(tenants.router, prefix="/api", tags=["tenants"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(document_templates.router, prefix="/api", tags=["document-templates"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(cycle_configs.router, prefix="/api", tags=["cycle-configs"])
app.include_router(table_snapshots.router, prefix="/api", tags=["table-snapshots"])
app.include_router(participants.router, prefix="/api", tags=["participants"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(tag_config.router, prefix="/api", tags=["tag-config"])
app.include_router(lists.router, prefix="/api", tags=["lists"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(storage.router, prefix="/api", tags=["storage"])
app.include_router(exports.router, prefix="/api", tags=["exports"])
app.include_router(finance.router, prefix="/api", tags=["finance"])
app.include_router(fines.router, prefix="/api", tags=["fines"])
app.include_router(statistics.router, prefix="/api", tags=["statistics"])
app.include_router(submission_assignments.router, prefix="/api", tags=["submission-assignments"])
app.include_router(word_import.router, prefix="/api", tags=["word-import"])
app.include_router(collaboration_ws.router, tags=["collaboration"])
