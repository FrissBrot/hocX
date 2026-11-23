"""Öffentliche Seite «Meine Abgabe» (/abgabe/verwalten): persönlicher Link aus der Mail, ohne Login
(app/services/submission_access_service.py, docs/SUBMISSION_OWNER_ACCESS.md).

- Der Token steht immer im Body (auch beim Lesen und Herunterladen), nie in Pfad oder Query; alles
  läuft über POST (Origin-Prüfung, keine Cookies nötig).
- Jede ungültige Anfrage bekommt dieselbe 404-Antwort, ohne Hinweis, woran es liegt.
- Rate-Limit je IP und je Link; Hochladen und Zurückziehen strenger.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.client_ip import client_ip
from app.core.config import settings
from app.core.db import get_db, release_for_stream
from app.core.offload import run_coroutine_in_thread
from app.core.rate_limit import enforce_rate_limit
from app.core.storage import ABGABEBOX, MAIN, object_response
from app.models import GalleryImage, StoredFile
from app.schemas.files import UploadFileResult
from app.services import submission_access_service as access_service
from app.services import submission_upload_rules
from app.services.file_service import FileService
from app.services import upload_job_service
from app.services.submission_service import SubmissionService, raw_element_ref
from app.services.upload_pipeline import MAX_UPLOAD_BYTES, stage_upload_to_disk

router = APIRouter()

INVALID = "Link ungültig oder abgelaufen"
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}
MAX_FILES_PER_REQUEST = 10
UPLOAD_PATH = "/api/public/submission-access/upload"
# Der Token kommt beim Hochladen im Header: so prüft ihn der Multipart-Schutz, bevor der Body
# gelesen wird (anonyme Uploads landen nie in /tmp).
TOKEN_HEADER = "X-Submission-Access-Token"
MAX_UPLOAD_REQUEST_BYTES = MAX_FILES_PER_REQUEST * MAX_UPLOAD_BYTES + 5 * 1024 * 1024


def upload_token_valid(token: str) -> bool:
    return access_service.token_active(token)


class AccessTokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class DownloadBody(AccessTokenBody):
    file_id: uuid.UUID


class WithdrawBody(AccessTokenBody):
    confirm: bool


class AccessFileRead(BaseModel):
    id: uuid.UUID
    name: str
    size: int | None
    scan_status: str


class AccessViewRead(BaseModel):
    tenant_name: str
    person_name: str
    title: str
    description: str | None
    element_label: str
    window_start: str | None
    window_end: str | None
    status: str
    submitted_at: str | None
    files: list[AccessFileRead]
    can_withdraw: bool
    can_upload: bool
    allowed_file_types: list[str]
    max_file_size_mb: int
    remaining_files: int | None


def _limit(request: Request, token: str, action: str, *, per_ip: int, per_token: int) -> None:
    enforce_rate_limit(f"submission-access-ip:{action}:{client_ip(request)}", limit=per_ip, period_seconds=15 * 60)
    enforce_rate_limit(f"submission-access-token:{action}:{access_service.hash_token(token)[:16]}", limit=per_token, period_seconds=60 * 60)


def _resolve_or_404(db: Session, token: str) -> access_service.Access:
    access = access_service.resolve(db, token)
    if access is None:
        raise HTTPException(status_code=404, detail={"code": "link_invalid", "message": INVALID})
    return access


def _view(db: Session, access: access_service.Access) -> AccessViewRead:
    element = access.element
    rules = submission_upload_rules.load_rules(db, access.assignment, element.element_ref)
    return AccessViewRead(
        tenant_name=access.tenant_name,
        person_name=access.person.first_name or access.person.display_name,
        title=access.assignment.title,
        description=access.assignment.description,
        element_label=element.label,
        window_start=element.window_start.isoformat() if element.window_start else None,
        window_end=element.window_end.isoformat() if element.window_end else None,
        status=element.status,
        submitted_at=element.submitted_at.isoformat() if element.submitted_at else None,
        files=[AccessFileRead(id=file.id, name=file.original_name, size=file.file_size_bytes, scan_status=file.scan_status) for file in element.files],
        can_withdraw=access_service.can_withdraw(access),
        can_upload=access_service.can_upload(access),
        allowed_file_types=[str(item) for item in (access.assignment.allowed_file_types or [])],
        max_file_size_mb=access.assignment.max_file_size_mb,
        remaining_files=rules.remaining,
    )


@router.post("/public/submission-access/view", response_model=AccessViewRead)
def view_submission(body: AccessTokenBody, request: Request, response: Response, db: Session = Depends(get_db)):
    _limit(request, body.token, "view", per_ip=60, per_token=120)
    response.headers.update(NO_STORE)
    return _view(db, _resolve_or_404(db, body.token))


@router.post("/public/submission-access/download")
def download_submission_file(body: DownloadBody, request: Request, db: Session = Depends(get_db)):
    _limit(request, body.token, "download", per_ip=120, per_token=240)
    access = _resolve_or_404(db, body.token)
    # Nur Dateien DIESES Elements, und nur geprüfte
    file = next((item for item in access.element.files if item.id == body.file_id), None)
    stored = db.query(StoredFile).filter(StoredFile.public_id == body.file_id, StoredFile.tenant_id == access.assignment.tenant_id).first() if file else None
    if file is None or stored is None or stored.scan_status != "clean":
        raise HTTPException(status_code=404, detail={"code": "file_unavailable", "message": "Datei nicht verfügbar"})
    namespace = ABGABEBOX if file.content_url.startswith("/api/submission-uploads/") else MAIN
    return release_for_stream(db, object_response(
        request, namespace, stored.storage_path, media_type=stored.mime_type or "application/octet-stream",
        filename=stored.original_name, attachment=True,
        headers={**NO_STORE, "X-Content-Type-Options": "nosniff"}, not_found_detail="Datei fehlt im Speicher",
    ))


@router.post("/public/submission-access/withdraw", response_model=AccessViewRead)
def withdraw_submission(body: WithdrawBody, request: Request, response: Response, db: Session = Depends(get_db)):
    _limit(request, body.token, "withdraw", per_ip=10, per_token=10)
    response.headers.update(NO_STORE)
    access = _resolve_or_404(db, body.token)
    if not body.confirm or not access_service.can_withdraw(access):
        raise HTTPException(status_code=409, detail={"code": "withdraw_not_allowed", "message": "Diese Abgabe kann nicht zurückgezogen werden"})
    access_service.withdraw(db, access)
    return _view(db, _resolve_or_404(db, body.token))


class AccessUploadResult(BaseModel):
    view: AccessViewRead
    errors: list[str]
    file_results: list[UploadFileResult]


def _element_checksums(db: Session, assignment, element_ref: str, raw: dict) -> dict[str, uuid.UUID | None]:
    """Hash -> Datei aller nicht zurückgezogenen Einreichungen DIESES Elements (Abgabebox und
    Direkt-Uploads/Link mit Element-Bezug), wie list_checksums_for_element der Abgabebox."""
    from app.services.context_visibility_service import abgabe_links
    from app.services.file_service import BLOCKED_SCAN_STATUSES

    links = abgabe_links(include_withdrawn=False)
    same_element = or_(
        links.c.element_ref == element_ref,
        (links.c.element_ref.is_(None))
        & links.c.event_id.is_not_distinct_from(raw["event_id"])
        & links.c.list_entry_id.is_not_distinct_from(raw["list_entry_id"])
        & links.c.manual_element_id.is_not_distinct_from(raw.get("manual_element_id")),
    )
    rows = db.execute(
        select(StoredFile.checksum_sha256, StoredFile.source_checksum_sha256, StoredFile.public_id)
        .join(links, links.c.stored_file_id == StoredFile.id)
        .where(
            links.c.assignment_id == assignment.id,
            StoredFile.tenant_id == assignment.tenant_id,
            StoredFile.scan_status.notin_(BLOCKED_SCAN_STATUSES),
            same_element,
            # Clips von Live Photos zeigt die Ansicht des Links nicht - auch nicht als Treffer melden
            ~select(GalleryImage.id).where(GalleryImage.live_video_stored_file_id == StoredFile.id).exists(),
        )
    )
    known: dict[str, uuid.UUID | None] = {}
    for checksum, source_checksum, public_id in rows:
        for value in (checksum, source_checksum):
            if value:
                known.setdefault(value, public_id)
    return known


def _merge_element_duplicates(
    planned: list[tuple[str, str]], saved: list[tuple[str, bytes]], results: list[dict], known: dict[str, uuid.UUID | None]
) -> list[dict]:
    """Ergebnis je Datei in Eingangsreihenfolge; übergangene Element-Duplikate erscheinen wie ein
    normaler Upload (Datei des Elements bzw. der gerade gespeicherten ersten Kopie)."""
    by_hash: dict[str, dict] = {}
    for (_name, content), result in zip(saved, results):
        by_hash.setdefault(hashlib.sha256(content).hexdigest(), result)
    merged: list[dict] = []
    used: set[int] = set()
    for name, checksum in planned:
        result = by_hash.get(checksum)
        if result is not None and id(result) not in used:
            used.add(id(result))
            merged.append(result)
        elif result is not None:
            merged.append({**result, "name": name})
        else:
            existing = known.get(checksum)
            merged.append({"name": name, "status": "uploaded", "file_id": str(existing) if existing else None})
    return merged


@router.post("/public/submission-access/upload", response_model=AccessUploadResult)
async def upload_submission(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    token: str = Header(..., alias=TOKEN_HEADER, min_length=10, max_length=200),
    db: Session = Depends(get_db),
):
    return await run_coroutine_in_thread(_upload_impl, request=request, response=response, token=token, files=files, db=db)


async def _upload_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    *, request: Request, response: Response, token: str, files: list[UploadFile], db: Session,
) -> AccessUploadResult:
    _limit(request, token, "upload", per_ip=20, per_token=20)
    response.headers.update(NO_STORE)
    access = _resolve_or_404(db, token)
    if not access_service.can_upload(access):
        raise HTTPException(status_code=409, detail={"code": "upload_not_allowed", "message": "Für diese Abgabe ist kein Hochladen möglich"})
    if not files or len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=413, detail={"code": "too_many_files", "message": f"Höchstens {MAX_FILES_PER_REQUEST} Dateien auf einmal"})
    element_ref = access.element.element_ref
    rules = submission_upload_rules.load_rules(db, access.assignment, element_ref)
    problem = rules.check_count(len(files)) or next((error for error in (rules.check_extension(file.filename or "") for file in files) if error), None)
    if problem is not None:
        raise HTTPException(status_code=400, detail={"code": "upload_rules", "message": problem})
    max_bytes = min(MAX_UPLOAD_BYTES, rules.max_bytes)
    staging_dir = Path(settings.upload_root) / "_staging" / "submission-access"
    staged: list[tuple[str, bytes]] = []
    for file in files:
        name = file.filename or ""
        staged_path = await stage_upload_to_disk(file, target_dir=staging_dir, max_bytes=max_bytes, suffix=Path(name).suffix.lower() or ".bin")
        try:
            staged.append((name, staged_path.read_bytes()))
        finally:
            staged_path.unlink(missing_ok=True)
    # Wie der In-App-Upload (files.py::_resolve_upload_target): Termin und Bezeichnung des Elements
    raw = next(
        (item for item in SubmissionService()._resolve_raw_elements(db, access.assignment)
         if raw_element_ref(item) == element_ref),
        None,
    )
    if raw is None:
        raise HTTPException(status_code=404, detail={"code": "link_invalid", "message": INVALID})
    # Exakte Duplikate nur innerhalb DIESES Elements still übergehen (wie die Abgabebox): die
    # Antwort sieht aus wie ein normaler Upload; Dateien ausserhalb des Elements spielen keine
    # Rolle (dort wird eine eigene Kopie gespeichert, kein Hinweis auf andere Dateien des Vereins).
    known = _element_checksums(db, access.assignment, element_ref, raw)
    to_save: list[tuple[str, bytes]] = []
    planned: list[tuple[str, str]] = []  # (Name, Hash) in Eingangsreihenfolge
    for name, content in staged:
        checksum = hashlib.sha256(content).hexdigest()
        planned.append((name, checksum))
        if checksum not in known:
            known[checksum] = None  # auch Duplikate innerhalb dieser Einreichung
            to_save.append((name, content))
    file_results: list[dict] = []
    errors: list[str] = []
    # Upload-Verlauf (0250): Vorgang «persönlicher Link» nur für die Verwaltung sichtbar (E-15) -
    # ohne Personendaten im Vorgang (actor_kind statt Name); Konto, falls die Person eines hat.
    history = upload_job_service.open_job(
        db, tenant_id=access.assignment.tenant_id, channel="submission_link", created_by=access.person.id,
        actor_kind="submission_person", status="processing", submission_assignment_id=access.assignment.id,
        submission_element_ref=element_ref, submission_element_label=raw["label"], event_id=raw["event_id"],
    ) if to_save else None
    if to_save:
        _items, errors = await FileService().save_document_uploads(
            db, tenant_id=access.assignment.tenant_id, files=to_save, tags=[], created_by=access.person.id,
            upload_event_id=raw["event_id"], upload_assignment=access.assignment, upload_element_ref=element_ref,
            upload_element_label=raw["label"], file_results=file_results, allow_images=True,
            # Ohne Anmeldung: nie verraten, ob eine Datei im Verein schon existiert (kein «übersprungen»
            # mit fremder ID, kein Duplikat-Text) - ausserhalb des Elements wird gespeichert.
            allow_duplicates=True,
            before_commit=lambda: upload_job_service.record_results(db, history, file_results),
        )
        if history is not None:
            upload_job_service.finish(db, history)
            db.commit()
    file_results = _merge_element_duplicates(planned, to_save, file_results, known)
    # Aufgabe nachführen (erledigt, sobald eine geprüfte Datei da ist; sonst erledigt der Scan sie)
    SubmissionService()._element_with_todo_sync(db, access.assignment, element_ref)
    return AccessUploadResult(view=_view(db, _resolve_or_404(db, token)), errors=errors, file_results=[UploadFileResult(**result) for result in file_results])
