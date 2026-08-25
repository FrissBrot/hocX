import asyncio
import logging
import traceback as traceback_module
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.captcha import captcha_partially_configured
from app.config import settings
from app.db import SessionLocal
from app.repository import insert_error_log
from app.routes import public
from app.storage import cleanup_stale_quarantine_files

_logger = logging.getLogger(__name__)

Path(settings.storage_root).mkdir(parents=True, exist_ok=True)

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


async def quarantine_cleanup_loop() -> None:
    """Periodic sweep that deletes stale orphaned files under quarantine/ - see
    storage.cleanup_stale_quarantine_files for why this is filesystem-age-based only (the
    restricted DB role this service runs as has no SELECT on submission_upload_file/stored_file
    to check for orphan status the way the main backend's rescan loops do).

    Runs in every uvicorn worker (--workers 2, no single-instance process in this deployment),
    so each tick is guarded by a Postgres advisory lock - only the worker that acquires it runs
    the sweep, the other skips that tick. Same pattern as the main backend's
    domain_health_check_loop/abgabebox_rescan_loop (backend/app/main.py). Advisory locks are a
    plain Postgres function call, not a table grant, so this works fine under the restricted role
    even though it has no SELECT/UPDATE/DELETE on any table.
    """
    interval_seconds = settings.quarantine_cleanup_interval_minutes * 60
    max_age_seconds = settings.quarantine_max_age_minutes * 60
    while True:
        db = SessionLocal()
        try:
            acquired = db.execute(text("SELECT pg_try_advisory_lock(202600007)")).scalar()
            if acquired:
                try:
                    cleanup_stale_quarantine_files(max_age_seconds)
                finally:
                    db.execute(text("SELECT pg_advisory_unlock(202600007)"))
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(quarantine_cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

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


app.include_router(public.router, prefix="/api", tags=["public"])
