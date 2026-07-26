import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api.routes import admin, admin_auth, auth, collaboration_ws, cycle_configs, document_templates, events, exports, files, finance, fines, lists, participants, protocol_elements, protocols, statistics, submission_assignments, tag_config, templates, tenants, todos, users
from app.core.db import SessionLocal
from app.core.config import settings
from app.core.error_log import best_effort_actor_from_request, record_system_error
from app.core.redis_client import close_redis_pool
from app.core.security import hash_password
from app.models import ElementType, PlatformAdmin, Role, Tenant
from app.services import domain_health_check_service, traefik_config_service
from app.services.submission_service import SubmissionService
from app.services.document_template_service import DocumentTemplateService
from app.services.file_service import FileService


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
    interval_seconds = settings.domain_health_check_interval_minutes * 60
    while True:
        with SessionLocal() as db:
            acquired = db.execute(text("SELECT pg_try_advisory_lock(202600003)")).scalar()
            if acquired:
                try:
                    domain_health_check_service.run_health_check(db)
                finally:
                    db.execute(text("SELECT pg_advisory_unlock(202600003)"))
        await asyncio.sleep(interval_seconds)


async def abgabebox_rescan_loop() -> None:
    """Periodic sweep for submission_upload files stuck in scan_status='pending' (ClamAV was
    unreachable at upload time - see abgabebox-backend/app/scanner.py's fail-open comment).
    Same every-worker-but-advisory-locked pattern as domain_health_check_loop above."""
    interval_seconds = settings.abgabebox_rescan_interval_minutes * 60
    submission_service = SubmissionService()
    while True:
        with SessionLocal() as db:
            acquired = db.execute(text("SELECT pg_try_advisory_lock(202600005)")).scalar()
            if acquired:
                try:
                    submission_service.rescan_all_pending(db)
                finally:
                    db.execute(text("SELECT pg_advisory_unlock(202600005)"))
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    FileService().ensure_storage()
    ensure_runtime_columns()
    ensure_startup_seed_data()
    ensure_default_document_templates()
    ensure_traefik_dynamic_config()
    health_check_task = asyncio.create_task(domain_health_check_loop())
    rescan_task = asyncio.create_task(abgabebox_rescan_loop())
    yield
    health_check_task.cancel()
    rescan_task.cancel()
    await close_redis_pool()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

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
app.include_router(participants.router, prefix="/api", tags=["participants"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(tag_config.router, prefix="/api", tags=["tag-config"])
app.include_router(lists.router, prefix="/api", tags=["lists"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(exports.router, prefix="/api", tags=["exports"])
app.include_router(finance.router, prefix="/api", tags=["finance"])
app.include_router(fines.router, prefix="/api", tags=["fines"])
app.include_router(statistics.router, prefix="/api", tags=["statistics"])
app.include_router(submission_assignments.router, prefix="/api", tags=["submission-assignments"])
app.include_router(collaboration_ws.router, tags=["collaboration"])
