import logging
import traceback as traceback_module
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import hiking_tours, internal
from app.core.config import settings

_logger = logging.getLogger(__name__)

Path(settings.work_root).mkdir(parents=True, exist_ok=True)

if not settings.internal_token:
    _logger.warning(
        "STARTUP: WANDERPLANER_INTERNAL_TOKEN ist leer - jede Anfrage wird abgelehnt (fail closed), "
        "bis das Token in hocX-Backend und Wanderplaner-Service gleich gesetzt ist."
    )

app = FastAPI(title=settings.app_name, version="1.0.0")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Dieser Service hat keinen Zugriff auf system_error_log der hocX-DB. Er gibt die
    Fehlerdetails deshalb an den einzigen Aufrufer - das hocX-Backend im internen Netz -
    zurueck, der sie dort protokolliert und dem Browser nur eine generische Meldung zeigt
    (siehe wanderplaner_client.py im hocX-Backend)."""
    _logger.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Ein interner Fehler ist aufgetreten.",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": "".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)),
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(hiking_tours.router, prefix="/api", tags=["hiking-tours"])
app.include_router(internal.router, tags=["internal"])
