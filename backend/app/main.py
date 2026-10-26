import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool
from starlette.requests import cookie_parser
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.api.routes import activity, admin, agenda_items, admin_auth, admin_backups, admin_cashflow, admin_document_templates, admin_identity_verification, admin_maintenance, admin_storage, maintenance_public, auth, calendar_feeds, collaboration_ws, cycle_configs, document_studio, document_verification, documents, events, files, managed_documents, finance, fines, lists, participants, privacy_settings, protocol_elements, protocols, public_catalog, public_share, retention, roles, share_links, statistics, storage, submission_assignments, system_status, table_snapshots, tag_config, task_packages, templates, tenant_data_export, tenants, todos, users, word_import
from app.core import runtime_metrics
from app.core.loops import BACKEND_LOOPS
from app.core.db import SessionLocal, engine
from app.core.config import settings
from app.core.objstore_client import StorageUnavailable, StorageWriteFenced
from app.core.admin_security import parse_admin_session_token
from app.core.audit_context import AuditContextMiddleware
from app.core.db_admission import (
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    ActiveUsers,
    DbAdmissionMiddleware,
    OverloadGuard,
    PriorityDirectory,
    RejectionLog,
    run_overload_upkeep,
)
from app.core.error_log import record_request_error
from app.core.redis_client import close_redis_pool, get_redis
from app.core.security import hash_password, parse_session_token
from app.models import AppUser, ElementType, PlatformAdmin, Tenant
from app.services import traefik_config_service
from app.services.file_service import FileService, ThumbnailBusy
from app.services.upload_lock import UploadLockBusy
from app.services.isolated_parse import shutdown_pool as shutdown_word_import_parse_pool
from app.services.isolated_parse import warm_up_pool as warm_up_word_import_parse_pool
from app.services import storage_profile_service


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


def ensure_local_storage_profile() -> None:
    """Legt das Profil für das lokale Garage-S3 an bzw. hält es aktuell, solange LOCAL_S3_* in
    der Umgebung steht (docker-compose stellt den Dienst beim ersten Deployment bereit). Unter
    einem Advisory-Lock, weil mehrere uvicorn-Worker gleichzeitig starten."""
    if not settings.local_s3_access_key:
        return
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(202600021)"))
        with SessionLocal() as db:
            storage_profile_service.ensure_local_profile(db)


def ensure_startup_seed_data() -> None:
    """Runs the idempotent startup seed functions under an advisory lock so that a
    fresh database being seeded by multiple concurrent uvicorn workers (--workers 2)
    can't race on the same check-then-insert (e.g. two workers both seeing an empty
    platform_admin table and both trying to insert the bootstrap admin)."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(202600004)"))
        ensure_platform_admin_bootstrap()
        ensure_lookup_values()


def ensure_lookup_values() -> None:
    with SessionLocal() as db:
        existing_codes = set(db.scalars(select(ElementType.code)))
        # Feste ids: das Frontend (lib/constants/element-types.ts, Vorlagen-Editor) adressiert
        # Blocktypen per id. Ein max(id)+1-Anhaengen hatte auf frischen Installationen die
        # Finanz-/Chart-Typen verschoben (siehe Migration 0098_canonical_element_type_ids).
        desired = [
            (1, "text", "Editable text"),
            (2, "todo", "Todo element"),
            (3, "image", "Image element"),
            (4, "display", "Read-only display element"),
            (5, "static_text", "Static text element"),
            (6, "form", "Structured form block"),
            (7, "event_list", "Filtered event list"),
            (8, "bullet_list", "Bullet point list"),
            (9, "attendance", "Attendance control block"),
            (10, "session_date", "Next session date block"),
            (11, "matrix", "Responsive matrix block"),
            (12, "finance_balance", "Finance account balance"),
            (13, "finance_transactions", "Finance transaction table"),
            (14, "fine_list", "Attendance fine list"),
            (15, "chart", "Statistics chart block"),
            (16, "entry_exit", "Participant entry/exit block"),
            (17, "session_notes", "Session notes block"),
        ]
        changed = False
        existing_ids = set(db.scalars(select(ElementType.id)))
        for element_type_id, code, description in desired:
            if code in existing_codes:
                continue
            if element_type_id in existing_ids:
                logging.getLogger(__name__).error("element_type id %s ist belegt, Code %s fehlt - Typen manuell pruefen", element_type_id, code)
                continue
            db.add(ElementType(id=element_type_id, code=code, description=description))
            changed = True
        if changed:
            db.commit()


def ensure_runtime_columns() -> None:
    # All schema changes are now managed via Alembic (alembic upgrade head runs before uvicorn).
    # This function is kept as a no-op for backwards compatibility.
    pass


def ensure_document_studio() -> None:
    """Systemvorlagen synchronisieren und jedem Mandanten ein Standard-Brand-Profil geben
    (Document Studio). Advisory-Lock: mehrere Worker starten gleichzeitig."""
    from app.documents import brand_service
    from app.documents.system_templates import sync_system_templates

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(202600002)"))
        with SessionLocal() as db:
            result = sync_system_templates(db)
            for tenant in db.scalars(select(Tenant).order_by(Tenant.id.asc())):
                brand_service.ensure_default_brand(db, tenant.id)
            db.commit()
            if result["created"] or result["updated"]:
                logging.getLogger(__name__).info("Systemvorlagen synchronisiert: %s", result)


def ensure_traefik_dynamic_config() -> None:
    with SessionLocal() as db:
        traefik_config_service.regenerate(db)


def _scope_cookie(scope, name: str) -> str | None:
    raw = "; ".join(value.decode("latin-1") for key, value in scope.get("headers", ()) if key == b"cookie")
    return cookie_parser(raw).get(name) if raw else None


def _session_user_id(scope) -> int | None:
    """Nutzer aus dem signierten Session-Cookie, ohne Datenbank (nur für die Priorität bei
    Überlast - die eigentliche Prüfung samt Sperre/Widerruf macht get_current_user)."""
    data = parse_session_token(_scope_cookie(scope, settings.auth_session_cookie))
    try:
        return int(data["user_id"]) if data else None
    except (KeyError, TypeError, ValueError):
        return None


OVERLOAD_GUARD = OverloadGuard(
    directory=PriorityDirectory(),
    active_users=ActiveUsers(settings.overload_active_minutes * 60, get_redis),
    rejections=RejectionLog(),
    thresholds={PRIORITY_LOW: settings.overload_threshold_low, PRIORITY_NORMAL: settings.overload_threshold_normal},
    identify=_session_user_id,
    is_admin=lambda scope: parse_admin_session_token(_scope_cookie(scope, settings.admin_session_cookie)) is not None,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.documents.renderer import shutdown_renderer

    FileService().ensure_storage()
    warm_up_word_import_parse_pool()
    try:
        ensure_runtime_columns()
        ensure_no_production_demo_data()
        ensure_startup_seed_data()
        ensure_document_studio()
        ensure_traefik_dynamic_config()
        ensure_local_storage_profile()
        # Leichte Loops im Backend; die schweren laufen im job-worker (core/loops.py, Paket 10).
        loop_tasks = [asyncio.create_task(factory()) for factory in BACKEND_LOOPS]
        runtime_metrics_task = asyncio.create_task(
            runtime_metrics.run_monitor(
                runtime_metrics.RuntimeReporter(settings.app_database_url or settings.database_url, settings.process_kind), engine
            )
        )
        overload_task = asyncio.create_task(
            run_overload_upkeep(
                OVERLOAD_GUARD,
                create_engine(
                    settings.app_database_url or settings.database_url,
                    poolclass=NullPool,
                    hide_parameters=True,
                    connect_args={"connect_timeout": 3, "application_name": f"hocx-{settings.process_kind}-overload"},
                ),
                runtime_metrics.instance_name(settings.process_kind),
            )
        )
        yield
        overload_task.cancel()
        runtime_metrics_task.cancel()
        for task in loop_tasks:
            task.cancel()
        await close_redis_pool()
    finally:
        shutdown_word_import_parse_pool()
        shutdown_renderer()


app = FastAPI(
    title=settings.app_name,
    version="1.2.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

from app.upload_admission import UploadAdmissionMiddleware
from app.services.upload_pipeline import GALLERY_REQUEST_MAX_BYTES
app.add_middleware(
    UploadAdmissionMiddleware,
    path="/api/files/gallery-uploads",
    max_bytes=GALLERY_REQUEST_MAX_BYTES,
    storage_dir=settings.upload_root,
    max_active=settings.gallery_upload_concurrency,
    wait_seconds=settings.gallery_upload_slot_wait_seconds,
)

# Audit MAIN-SEC-004: Multipart nur mit signierter Session und mit Grössenlimit, bevor
# Starlette den Body auf die Platte spoolt (Galerie hat oben ihre eigene Admission).
from app.multipart_guard import MultipartGuardMiddleware
from app.services.upload_pipeline import MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES
_MULTIPART_OVERHEAD_BYTES = 5 * 1024 * 1024
app.add_middleware(
    MultipartGuardMiddleware,
    default_max_bytes=_MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD_BYTES,
    path_limits=(
        ("/api/files/document-uploads", files.MAX_DOCUMENT_UPLOAD_BATCH_BYTES + _MULTIPART_OVERHEAD_BYTES),
        ("/api/tools/word-import/", word_import.MAX_WORD_IMPORT_BATCH_BYTES + _MULTIPART_OVERHEAD_BYTES),
        ("/api/admin/tenants/import", admin.MAX_TENANT_IMPORT_UPLOAD_BYTES + _MULTIPART_OVERHEAD_BYTES),
    ),
    skip_prefixes=("/api/files/gallery-uploads",),
)

# MAIN-OPS-013: übrige Bodies (JSON etc.) begrenzen; Multipart deckt der Guard oben ab.
from app.request_body_limit import RequestBodyLimitMiddleware
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.max_request_body_bytes,
    skip_prefixes=("/api/files/gallery-uploads",),
)

# Requests je Worker an den DB-Pool binden (Stau aus Threadpool und Pool unter Last) und bei
# Überlast nach Abo-Priorität annehmen, siehe db_admission.py. Innerhalb der Wartung/CORS-
# Schichten: auch die 503 trägt CORS-Header.
app.add_middleware(
    DbAdmissionMiddleware,
    guard=OVERLOAD_GUARD,
    max_active=settings.db_admission_limit or max(1, settings.db_pool_size + settings.db_max_overflow - settings.db_admission_reserve),
    wait_seconds=settings.db_admission_wait_seconds,
    skip_paths=("/api/health",),
    # Lange Upload-Bodies belegen sonst einen Platz ohne DB-Arbeit; die Galerie hat eine eigene Annahme.
    skip_prefixes=(
        "/api/files/gallery-uploads",
        "/api/files/document-uploads",
        "/api/tools/word-import/",
        "/api/admin/tenants/import",
    ),
)

from app.core.maintenance_middleware import MaintenanceMiddleware
# Vor der Upload-Annahme (äussere Schicht): während einer Wartung wird ein grosser Upload sofort
# abgewiesen, statt erst gepuffert zu werden. CORS liegt noch weiter aussen, damit auch die
# 503-Antworten die CORS-Header tragen.
app.add_middleware(MaintenanceMiddleware)

_CORS_ORIGINS = [o for o in [
    *settings.local_dev_origins,
    f"https://{settings.traefik_domain}" if settings.traefik_domain else None,
] if o] + sorted(settings.extra_cors_origin_set)

from app.core.origin_guard import OriginGuardMiddleware
# Innerhalb von CORS: auch die 403-Antwort trägt CORS-Header (SEC-009, siehe origin_guard.py).
app.add_middleware(OriginGuardMiddleware, allowed_origins=set(_CORS_ORIGINS))
# Quelladresse für das Audit-Log (gekürzt und gehasht, Datenschutz-Audit PRIV-013)
app.add_middleware(AuditContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
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
    await record_request_error(request, exc, 500)
    return JSONResponse(status_code=500, content={"detail": "Ein interner Fehler ist aufgetreten."})


@app.exception_handler(StorageWriteFenced)
async def storage_write_fenced_handler(request: Request, exc: StorageWriteFenced) -> JSONResponse:
    """Persistente Schreibvorgänge sind kurz gesperrt (Cutover/Wartung) - erwartet, kein Fehler
    für system_error_log. 503 + Retry-After, damit Clients später erneut versuchen."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Speichern ist gerade kurz gesperrt (Wartung). Bitte in Kürze erneut versuchen.", "code": "storage_write_fenced"},
        headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"},
    )


def _db_busy_response() -> JSONResponse:
    """Pool erschöpft (Concurrency-Audit CONC-010): nach DB_POOL_TIMEOUT_SECONDS schnell 503 mit
    Retry-After statt langem Warten - Last, kein Programmfehler, deshalb kein Fehlerprotokoll
    (gezählt in den Laufzeitkennzahlen, /admin/system)."""
    runtime_metrics.count("pool_timeouts")
    return JSONResponse(
        status_code=503,
        content={"detail": "Der Server ist gerade ausgelastet. Bitte gleich erneut versuchen.", "code": "db_busy"},
        headers={"Retry-After": "5", "Cache-Control": "no-store"},
    )


@app.exception_handler(SQLAlchemyTimeoutError)
async def db_pool_timeout_handler(request: Request, exc: SQLAlchemyTimeoutError) -> JSONResponse:
    return _db_busy_response()


@app.exception_handler(ThumbnailBusy)
async def thumbnail_busy_handler(request: Request, exc: ThumbnailBusy) -> JSONResponse:
    """Zu viele Vorschaubilder gleichzeitig in Erzeugung (file_service, CONC-014) - erwartet,
    kein Eintrag im Fehlerprotokoll. Der Thumbnail-Backfill im job-worker holt sie nach."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Vorschau wird erzeugt, bitte gleich erneut versuchen.", "code": "thumbnail_busy"},
        headers={"Retry-After": "5", "Cache-Control": "no-store"},
    )


@app.exception_handler(UploadLockBusy)
async def upload_lock_busy_handler(request: Request, exc: UploadLockBusy) -> JSONResponse:
    """Andere Uploads desselben Vereins laufen gerade (Upload-Lock, services/upload_lock.py) -
    erwartet, kein Eintrag im Fehlerprotokoll. Das Frontend wiederholt nach Retry-After."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Gerade werden andere Dateien dieses Vereins verarbeitet. Bitte gleich erneut versuchen.", "code": "upload_busy"},
        headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"},
    )


@app.exception_handler(StorageUnavailable)
async def storage_unavailable_handler(request: Request, exc: StorageUnavailable) -> JSONResponse:
    """Objektspeicher nicht erreichbar: protokollieren (unerwarteter Betriebsfehler) und 503
    statt 500 - der Zustand ist vorübergehend, nichts wurde inkonsistent bestätigt."""
    await record_request_error(request, exc, 503)
    return JSONResponse(
        status_code=503,
        content={"detail": "Der Dateispeicher ist vorübergehend nicht erreichbar.", "code": "storage_unavailable"},
        headers={"Retry-After": "30", "Cache-Control": "no-store"},
    )


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
    if isinstance(exc.__cause__, SQLAlchemyTimeoutError):
        # Route hat den Pool-Timeout als SQLAlchemyError abgefangen und umgewandelt.
        return _db_busy_response()
    if exc.status_code >= 400 and exc.__cause__ is not None and not isinstance(exc.__cause__, ValueError):
        await record_request_error(request, exc.__cause__, exc.status_code)
    return await http_exception_handler(request, exc)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_auth.router, prefix="/api/admin/auth", tags=["admin-auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_identity_verification.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_document_templates.router, prefix="/api/admin", tags=["admin"])
app.include_router(tenants.router, prefix="/api", tags=["tenants"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(roles.router, prefix="/api", tags=["roles"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(document_studio.router, prefix="/api", tags=["document-studio"])
app.include_router(document_verification.router, prefix="/api", tags=["documents"])
app.include_router(privacy_settings.router, prefix="/api", tags=["privacy"])
app.include_router(activity.router, prefix="/api", tags=["privacy"])
app.include_router(tenant_data_export.router, prefix="/api", tags=["privacy"])
app.include_router(retention.router, prefix="/api", tags=["privacy"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(cycle_configs.router, prefix="/api", tags=["cycle-configs"])
app.include_router(task_packages.router, prefix="/api", tags=["task-packages"])
app.include_router(table_snapshots.router, prefix="/api", tags=["table-snapshots"])
app.include_router(participants.router, prefix="/api", tags=["participants"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(tag_config.router, prefix="/api", tags=["tag-config"])
app.include_router(lists.router, prefix="/api", tags=["lists"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(agenda_items.router, prefix="/api", tags=["agenda-items"])
app.include_router(files.router, prefix="/api", tags=["files"])
# Logische Dokumente (Dateien-Tab, feature/document-management): GET /api/documents/{uuid}… -
# bewusst nach dem Router der Dokument-Engine, damit feste Pfade wie /documents/exports vorgehen.
app.include_router(managed_documents.router, prefix="/api", tags=["managed-documents"])
app.include_router(share_links.router, prefix="/api", tags=["share-links"])
app.include_router(public_share.router, prefix="/api", tags=["public-share"])
app.include_router(public_catalog.router, prefix="/api", tags=["public-catalog"])
app.include_router(calendar_feeds.router, prefix="/api", tags=["calendar-feeds"])
app.include_router(storage.router, prefix="/api", tags=["storage"])
app.include_router(finance.router, prefix="/api", tags=["finance"])
app.include_router(fines.router, prefix="/api", tags=["fines"])
app.include_router(statistics.router, prefix="/api", tags=["statistics"])
app.include_router(system_status.router, prefix="/api", tags=["system-status"])
app.include_router(submission_assignments.router, prefix="/api", tags=["submission-assignments"])
app.include_router(word_import.router, prefix="/api", tags=["word-import"])
app.include_router(collaboration_ws.router, tags=["collaboration"])
app.include_router(maintenance_public.router, prefix="/api", tags=["maintenance"])
app.include_router(admin_storage.router, prefix="/api/admin", tags=["admin-storage"])
app.include_router(admin_maintenance.router, prefix="/api/admin", tags=["admin-maintenance"])
app.include_router(admin_backups.router, prefix="/api/admin", tags=["admin-backups"])
app.include_router(admin_cashflow.router, prefix="/api/admin", tags=["admin-cashflow"])
