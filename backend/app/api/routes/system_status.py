"""Öffentlicher, per Token geschützter Statusendpunkt für externe Überwachung (Uptime Kuma).

Liegt bewusst unter /api statt /api/admin: Traefik leitet /api/admin nur über die Admin-Domain,
ein externer Monitor soll aber dieselbe öffentliche Adresse prüfen wie die Nutzer. Antwortet mit
503, sobald ein kritisches Problem offen ist oder der Systemstatus veraltet ist - dann schlägt
der HTTP-Monitor in Uptime Kuma an, auch wenn das Backend selbst keine ntfy-Nachricht mehr
verschicken kann. Die Antwort enthält nur Zähler, keine Details (Token könnte in Logs landen)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import system_alert_service, system_health_service
from app.services.notification_settings_service import NotificationSettingsService

router = APIRouter()
_settings_service = NotificationSettingsService()


def _request_token(request: Request, token: str | None) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return token


@router.get("/system-status/summary")
def system_status_summary(
    request: Request,
    token: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
):
    if not _settings_service.verify_status_token(db, _request_token(request, token)):
        raise HTTPException(status_code=401, detail="Invalid status token")

    now = datetime.now(timezone.utc)
    snapshot = system_health_service.load_snapshot()
    stale = system_health_service.is_stale(snapshot, now)
    problems = system_alert_service.current_problems(db, snapshot, now=now)
    critical = sum(1 for problem in problems if problem.severity == "critical")
    warnings = sum(1 for problem in problems if problem.severity == "warning")
    status = "stale" if stale else ("critical" if critical else ("warning" if warnings else "ok"))
    return JSONResponse(
        status_code=503 if stale or critical else 200,
        content={
            "status": status,
            "critical": critical,
            "warnings": warnings,
            "collected_at": snapshot.collected_at.isoformat() if snapshot else None,
        },
        headers={"Cache-Control": "no-store"},
    )
