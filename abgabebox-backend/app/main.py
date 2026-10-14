import asyncio
import logging
import traceback as traceback_module
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.captcha import captcha_configured, captcha_partially_configured
from app.config import is_dev_or_test_environment, settings
from app.db import SessionLocal, engine
from app.repository import insert_error_log, upload_path_referenced
from app.routes import public
from app.objstore_client import StorageWriteFenced
from app.storage import cleanup_stale_quarantine_files

_logger = logging.getLogger(__name__)

Path(settings.storage_root).mkdir(parents=True, exist_ok=True)  # nur beim Dateisystem-Backend genutzt

# Loud, once-at-startup version of captcha.captcha_enabled()'s per-request warning (audit
# finding, 2026-08-25) - a partial FriendlyCaptcha config (exactly one of sitekey/api_key
# set) is a real misconfiguration that previously disabled bot verification silently with no
# signal anywhere. This surfaces it immediately in the deploy/startup logs instead of only
# lazily on the first upload attempt.
if captcha_partially_configured():
    _logger.warning(
        "STARTUP: FriendlyCaptcha ist nur teilweise konfiguriert (FRIENDLY_CAPTCHA_SITEKEY "
        "oder FRIENDLY_CAPTCHA_API_KEY fehlt). Bot-Verifikation ist aktiv, schlaegt aber bis "
        "zur vollstaendigen Konfiguration fehl - Uploads werden abgelehnt."
    )

# Loud, once-at-startup counterpart for the "entirely unconfigured" case (audit finding,
# 2026-08-27): captcha.py's _skip_captcha_when_unconfigured() now only skips verification on a
# stack explicitly marked dev/test (ABGABEBOX_ENVIRONMENT) - everywhere else, no FriendlyCaptcha
# keys at all now means every upload is rejected (fail closed), not silently allowed through.
# That is a much bigger operational change than the partial-config case above (ALL uploads fail,
# not just some), so it gets the same immediate startup visibility rather than only surfacing
# lazily on the first upload attempt.
if not captcha_configured() and not is_dev_or_test_environment():
    _logger.warning(
        "STARTUP: Kein FriendlyCaptcha konfiguriert (FRIENDLY_CAPTCHA_SITEKEY und "
        "FRIENDLY_CAPTCHA_API_KEY fehlen beide) und ABGABEBOX_ENVIRONMENT=%r gilt nicht als "
        "dev/test. Alle Uploads werden abgelehnt (fail closed), bis FriendlyCaptcha konfiguriert "
        "ist oder ABGABEBOX_ENVIRONMENT auf 'development'/'test' gesetzt wird.",
        settings.environment,
    )


def _record_background_error(exc: Exception) -> None:
    """Same as _record_error below, but for code with no Request to pull a method/path from -
    background loops run entirely outside the HTTP request/response cycle the global exception
    handlers watch, so without this the error would only ever reach the container logs, never
    system_error_log/the admin panel."""
    db = SessionLocal()
    try:
        insert_error_log(
            db,
            tenant_id=None,
            request_method=None,
            request_path=None,
            status_code=None,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback="".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)),
        )
    except Exception:
        db.rollback()
    finally:
        db.close()


# Muss in backend/app/core/background_loops.py (EXTERNAL_LOCK_IDS) eingetragen bleiben: beide
# Dienste teilen sich dieselbe Datenbank und damit denselben Advisory-Lock-Raum. Bis 2026-10-11
# stand hier 202600007 - dieselbe ID wie export_cleanup im Backend, sodass sich die beiden Loops
# gegenseitig Ticks weggenommen haben.
QUARANTINE_CLEANUP_LOCK_ID = 202600016
# Jobname in backend/app/core/job_registry.py (Übersicht unter /admin/jobs).
QUARANTINE_CLEANUP_JOB_NAME = "abgabebox_quarantine_cleanup"


def _record_job_run(*, status: str, started_at: datetime, error: str | None = None) -> None:
    """Meldet einen Lauf an system_job_status über die SECURITY-DEFINER-Funktion record_job_run
    (Migration 0105) - die Rolle hocx_abgabebox hat kein DML auf die Tabelle, nur EXECUTE.
    Best effort: ein Fehler hier darf den Loop nicht stoppen, landet aber in system_error_log."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT record_job_run(:job_name, :status, :started_at, NOW(), :error, TRUE)"),
                {"job_name": QUARANTINE_CLEANUP_JOB_NAME, "status": status, "started_at": started_at, "error": error},
            )
    except Exception as exc:
        _logger.exception("Lauf von %s konnte nicht protokolliert werden", QUARANTINE_CLEANUP_JOB_NAME)
        _record_background_error(exc)


async def quarantine_cleanup_loop() -> None:
    """Entfernt alte verwaiste Quarantänedateien; registrierte Uploads bleiben erhalten."""
    interval_seconds = settings.quarantine_cleanup_interval_minutes * 60
    max_age_seconds = max(24 * 60 * 60, settings.quarantine_max_age_minutes * 60)
    while True:
        with engine.begin() as conn:
            acquired = conn.execute(text(f"SELECT pg_try_advisory_xact_lock({QUARANTINE_CLEANUP_LOCK_ID})")).scalar()
            if acquired:
                started_at = datetime.now(timezone.utc)
                try:
                    with SessionLocal() as db:
                        await asyncio.to_thread(cleanup_stale_quarantine_files, db, max_age_seconds, is_referenced=lambda path: upload_path_referenced(db, path))
                except Exception as exc:
                    _logger.exception("Quarantäne-Cleanup fehlgeschlagen; beim nächsten Durchlauf erneut versuchen")
                    _record_background_error(exc)
                    await asyncio.to_thread(_record_job_run, status="failure", started_at=started_at, error=f"{type(exc).__name__}: {exc}"[:4000])
                else:
                    await asyncio.to_thread(_record_job_run, status="success", started_at=started_at)
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(quarantine_cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title=settings.app_name, version="1.1.13", lifespan=lifespan)

from app.upload_admission import UploadAdmissionMiddleware
app.add_middleware(UploadAdmissionMiddleware, path="/api/public/", max_bytes=public.MAX_UPLOAD_BODY_BYTES)

from app.maintenance import MaintenanceMiddleware, current_state, retry_after
# Aussen vor der Upload-Annahme: während einer Wartung wird ein Upload sofort abgewiesen.
app.add_middleware(MaintenanceMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _record_error(request: Request, exc: Exception, status_code: int) -> None:
    """Never raises - a failure to log an error must not mask the original error.
    No tenant/actor here: this is the public, unauthenticated Abgabebox - unlike the main
    backend there's no session cookie to resolve a tenant/user from at this generic level."""
    db = SessionLocal()
    try:
        insert_error_log(
            db,
            tenant_id=None,
            request_method=request.method,
            request_path=request.url.path,
            status_code=status_code,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback="".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)),
        )
    except Exception:
        db.rollback()
    finally:
        db.close()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net for anything a route didn't already catch - guarantees no raw error text
    ever reaches a public, unauthenticated response."""
    _record_error(request, exc, 500)
    return JSONResponse(status_code=500, content={"detail": "Ein interner Fehler ist aufgetreten."})


@app.exception_handler(HTTPException)
async def logged_http_exception_handler(request: Request, exc: HTTPException):
    """Routes here already convert unexpected errors to a curated HTTPException (`from exc`) -
    this records the original chained cause without changing the response, same convention
    as the main backend's handler."""
    if exc.status_code >= 400 and exc.__cause__ is not None:
        _record_error(request, exc.__cause__, exc.status_code)
    return await http_exception_handler(request, exc)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe for the Compose healthcheck - same shape as the main backend's
    /api/health. Doesn't touch the DB: this service has no other unauthenticated,
    dependency-free route a healthcheck could use instead."""
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/public/maintenance-status")
def maintenance_status() -> JSONResponse:
    """Minimaler Status für die Abgabebox-Seite: gesperrt ja/nein und voraussichtliches Ende."""
    state = current_state()
    return JSONResponse(
        {"active": state.full_active, "uploads_blocked": state.full_active or state.writes_blocked or state.uploads_blocked,
         "estimated_end_at": state.estimated_end_at.isoformat() if state.estimated_end_at else None},
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.exception_handler(StorageWriteFenced)
async def storage_write_fenced_handler(request: Request, exc: StorageWriteFenced) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Hochladen ist gerade kurz gesperrt. Bitte in Kürze erneut versuchen.", "code": "storage_write_fenced"},
                        headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"})


app.include_router(public.router, prefix="/api", tags=["public"])
