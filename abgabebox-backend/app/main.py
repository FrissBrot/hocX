import traceback as traceback_module
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import SessionLocal
from app.repository import insert_error_log
from app.routes import public

Path(settings.storage_root).mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name, version="0.1.0")

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


app.include_router(public.router, prefix="/api", tags=["public"])
