"""Wanderplaner im hocX-Backend: Eingangstor zum Wanderplaner-Fachservice.

Die Fachlogik und die Daten (Touren, Wegenetz, Umgebungsdaten) liegen im separaten
wanderplaner-backend mit eigener Datenbank. Diese Routen behalten die bisherigen URLs unter
/api/hiking-tours, damit das Frontend unveraendert bleibt, und erledigen alles, was zu hocX
gehoert:

- Login, Mandant, Rolle und Feature-Gating (require_wanderplaner_read/_write)
- Ablage des Druck-PDFs als StoredFile im Mandanten-Speicher
- Audit-Eintraege
- Abgleich der Fotoalben pro Tour (photo_tour_link_service)

Alles andere wird unveraendert an den Service weitergereicht (wanderplaner_client).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_wanderplaner_read, require_wanderplaner_write
from app.models.entities import StoredFile
from app.schemas.hiking_tour import PrintResponse
from app.services import wanderplaner_client
from app.services.audit_service import AuditService
from app.services.photo_tour_link_service import sync_photos_for_tours_best_effort

router = APIRouter()
audit = AuditService()

# GPX-Import (5 MB, siehe wanderplaner-backend/app/core/gpx.py) plus Multipart-Overhead.
MAX_FORWARD_BODY_BYTES = 6 * 1024 * 1024
SHEET_COUNT_HEADER = "x-wanderplaner-sheet-count"

_UUID = r"[0-9a-fA-F-]{36}"
_TOUR_PATH = re.compile(rf"^(?P<tour_id>{_UUID})(?:/(?P<rest>.*))?$")
# Weitergeleitet wird nur, was wie ein Wanderplaner-Pfad aussieht: Segmente aus Buchstaben,
# Ziffern und Bindestrichen. Kein ".", kein "%", keine leeren Segmente - sonst koennte ein
# Pfad wie "x/../../internal/..." die nur per Token geschuetzten internen Endpunkte des
# Service erreichen.
_SAFE_SUBPATH = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")

# Aktionen, nach denen sich Datum, Titel oder Geometrie einer Tour geaendert haben koennen -
# danach werden die Fotoalben neu abgeglichen. Reine Wegpunkt-Bearbeitungen aendern die
# Route erst beim naechsten "Route berechnen" und loesen deshalb keinen Abgleich aus.
_PHOTO_SYNC_ACTIONS = {
    ("POST", None),  # Tour anlegen, /planned, /gpx-import
    ("PATCH", ""),
    ("DELETE", ""),
    ("POST", "plan"),
    ("POST", "route"),
    ("POST", "analyze"),
}
_AUDIT_ACTIONS = {
    ("DELETE", ""): "hiking_tour.deleted",
    ("PATCH", "reconnaissance"): "hiking_tour.reconnoitered",
    ("POST", "approve"): "hiking_tour.approved",
}


def _caller(user: CurrentUser) -> wanderplaner_client.CallerContext:
    return wanderplaner_client.CallerContext(
        tenant_id=user.current_tenant_id, user_id=user.user_id, user_name=user.display_name
    )


def _call_service(method: str, path: str, *, user: CurrentUser, timeout: float | None = None, **kwargs):
    try:
        return wanderplaner_client.request(method, path, caller=_caller(user), timeout=timeout, **kwargs)
    except wanderplaner_client.WanderplanerUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Der Wanderplaner ist momentan nicht erreichbar.") from exc
    except wanderplaner_client.WanderplanerUpstreamError as exc:
        raise HTTPException(status_code=502, detail="Im Wanderplaner ist ein interner Fehler aufgetreten.") from exc


def _passthrough(upstream: wanderplaner_client.WanderplanerResponse) -> Response:
    headers = {
        name: value
        for name, value in upstream.headers.items()
        if name in wanderplaner_client.PASSTHROUGH_RESPONSE_HEADERS and name != "content-type"
    }
    return Response(
        content=upstream.body,
        status_code=upstream.status,
        media_type=upstream.headers.get("content-type"),
        headers=headers,
    )


async def _read_body(request: Request) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_FORWARD_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Anfrage ist zu gross")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORWARD_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Anfrage ist zu gross")
    return bytes(body) or None


def _store_print_pdf(db: Session, *, tenant_id: int, content: bytes, original_name: str) -> StoredFile:
    """Gleiche Ablage wie ExportService._store_generated_file (EXPORT_ROOT/generated, von
    dessen Aufbewahrungs-Sweep mit aufgeraeumt), nur direkt aus den Bytes des Service."""
    target_dir = Path(settings.export_root) / "generated"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex}-wanderplaner.pdf"
    target_path.write_bytes(content)
    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name=original_name,
        mime_type="application/pdf",
        storage_path=str(target_path.relative_to(settings.storage_root)),
        file_size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        created_by=None,
    )
    try:
        db.add(stored_file)
        db.flush()
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    return stored_file


def _download_name(upstream: wanderplaner_client.WanderplanerResponse) -> str:
    """Dateiname aus dem Content-Disposition des Service (filename*=UTF-8''...)."""
    disposition = upstream.headers.get("content-disposition", "")
    _, _, encoded = disposition.partition("filename*=UTF-8''")
    return unquote(encoded.strip()) or "Wanderung.pdf"


@router.post("/hiking-tours/{tour_id}/print", response_model=PrintResponse)
async def print_hiking_tour(
    tour_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Kartendruck-PDF: der Service rendert, hocX legt das PDF als StoredFile ab."""
    require_wanderplaner_write(user)
    body = await _read_body(request)
    upstream = await run_in_threadpool(
        _call_service,
        "POST",
        f"/api/hiking-tours/{tour_id}/print",
        user=user,
        body=body,
        content_type=request.headers.get("content-type"),
        timeout=settings.wanderplaner_print_timeout_seconds,
    )
    if upstream.status != 200:
        return _passthrough(upstream)
    stored_file = _store_print_pdf(db, tenant_id=user.current_tenant_id, content=upstream.body, original_name=_download_name(upstream))
    db.commit()
    db.refresh(stored_file)
    audit.log(db, action="hiking_tour.printed", actor=user, entity_type="hiking_tour", details={"hiking_tour_id": str(tour_id)})
    return PrintResponse(
        generated_file_id=stored_file.public_id,
        content_url=f"/api/stored-files/{stored_file.public_id}/content",
        sheet_count=int(upstream.headers.get(SHEET_COUNT_HEADER, "0")),
        created_at=stored_file.created_at,
    )


@router.api_route("/hiking-tours", methods=["GET", "POST"])
async def forward_hiking_tour_collection(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await _forward(request, "", db, user)


@router.api_route("/hiking-tours/{subpath:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def forward_hiking_tour_request(
    subpath: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if not _SAFE_SUBPATH.match(subpath):
        raise HTTPException(status_code=404, detail="Not Found")
    return await _forward(request, subpath, db, user)


async def _forward(request: Request, subpath: str, db: Session, user: CurrentUser) -> Response:
    """Alle uebrigen Wanderplaner-Aufrufe: Rechte pruefen, weiterleiten, danach Audit und
    Foto-Abgleich. Lesend = jede Rolle, schreibend = writer/admin (wie bisher)."""
    method = request.method
    if method == "GET":
        require_wanderplaner_read(user)
    else:
        require_wanderplaner_write(user)

    match = _TOUR_PATH.match(subpath)
    tour_id = match.group("tour_id") if match else None
    action = (match.group("rest") or "") if match else None

    body = await _read_body(request) if method in {"POST", "PATCH"} else None
    path = "/api/hiking-tours" + (f"/{subpath}" if subpath else "")
    upstream = await run_in_threadpool(
        _call_service,
        method,
        path,
        user=user,
        query=request.url.query or None,
        body=body,
        content_type=request.headers.get("content-type"),
    )

    if upstream.status < 400:
        audit_action = _AUDIT_ACTIONS.get((method, action))
        if audit_action is not None:
            audit.log(db, action=audit_action, actor=user, entity_type="hiking_tour", details={"hiking_tour_id": tour_id})
        if (method, action) in _PHOTO_SYNC_ACTIONS:
            await run_in_threadpool(_sync_photos, db, user)
    return _passthrough(upstream)


def _sync_photos(db: Session, user: CurrentUser) -> None:
    sync_photos_for_tours_best_effort(db, user.current_tenant_id, actor_email=user.email)
    db.commit()
