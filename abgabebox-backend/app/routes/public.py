from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import element_resolver, repository, scanner
from app.captcha import verify_captcha
from app.config import settings
from app.db import get_db
from app.schemas import AssignmentDetailPublic, AssignmentPublic, ElementPublic, UploadResult
from app.storage import move_from_quarantine, save_to_quarantine, tenant_storage_bytes

router = APIRouter()

NOT_FOUND = HTTPException(status_code=404, detail="Nicht gefunden")

# SECURITY: the client-sent Content-Type header (upload_file.content_type) is fully attacker
# controlled and must never be trusted or stored - a file named "x.pdf" with real HTML/JS
# content and a forged Content-Type used to be served back with Content-Disposition: inline
# and that forged type, letting a browser render it as HTML in the hocX backend's origin
# (stored XSS, since this upload endpoint has no login at all). Instead: (1) verify the actual
# file bytes match the extension's real magic number before accepting the upload at all, and
# (2) always derive the stored mime_type from this fixed, server-controlled map - never from
# the client - so downstream consumers (see get_submission_file_content in the main backend)
# can trust stored_file.mime_type completely.
_EXTENSION_MIME_MAP = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls/.ppt (Compound File Binary)
_ZIP_SIGNATURE = b"PK\x03\x04"  # modern .docx/.xlsx/.pptx (all just zip containers)


def _content_matches_extension(content: bytes, extension: str) -> bool:
    head = content[:16]
    if extension == "pdf":
        return head.startswith(b"%PDF-")
    if extension in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if extension == "webp":
        return head.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if extension in ("docx", "xlsx", "pptx"):
        return head.startswith(_ZIP_SIGNATURE)
    if extension in ("doc", "xls", "ppt"):
        return head.startswith(_OLE_SIGNATURE)
    return False


def _get_tenant_or_404(db: Session, tenant_slug: str) -> dict:
    tenant = repository.get_tenant_by_slug(db, public_slug=tenant_slug)
    if tenant is None:
        raise NOT_FOUND
    return tenant


def _get_assignment_or_404(db: Session, tenant: dict, assignment_slug: str) -> dict:
    assignment = repository.get_assignment_by_slug(db, tenant_id=tenant["id"], public_slug=assignment_slug)
    if assignment is None:
        raise NOT_FOUND
    return assignment


@router.get("/public/{tenant_slug}/assignments", response_model=list[AssignmentPublic])
def list_assignments(tenant_slug: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, tenant_slug)
    assignments = repository.list_active_assignments(db, tenant_id=tenant["id"])
    open_assignments = []
    for assignment in assignments:
        if element_resolver.resolve_open_elements(db, assignment):
            open_assignments.append(
                AssignmentPublic(
                    public_slug=assignment["public_slug"],
                    title=assignment["title"],
                    description=assignment["description"],
                )
            )
    return open_assignments


@router.get(
    "/public/{tenant_slug}/assignments/{assignment_slug}",
    response_model=AssignmentDetailPublic,
)
def get_assignment(tenant_slug: str, assignment_slug: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, tenant_slug)
    assignment = _get_assignment_or_404(db, tenant, assignment_slug)
    return AssignmentDetailPublic(
        public_slug=assignment["public_slug"],
        title=assignment["title"],
        description=assignment["description"],
        allowed_file_types=assignment["allowed_file_types"] or [],
        max_files_per_element=assignment["max_files_per_element"],
        max_file_size_mb=assignment["max_file_size_mb"],
    )


@router.get(
    "/public/{tenant_slug}/assignments/{assignment_slug}/elements",
    response_model=list[ElementPublic],
)
def list_elements(tenant_slug: str, assignment_slug: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, tenant_slug)
    assignment = _get_assignment_or_404(db, tenant, assignment_slug)
    elements = element_resolver.resolve_open_elements(db, assignment)
    return [
        ElementPublic(
            element_ref=element["element_ref"],
            label=element["label"],
            window_start=element["window_start"],
            window_end=element["window_end"],
        )
        for element in elements
    ]


@router.post(
    "/public/{tenant_slug}/assignments/{assignment_slug}/elements/{element_ref}/upload",
    response_model=UploadResult,
)
async def upload(
    tenant_slug: str,
    assignment_slug: str,
    element_ref: str,
    captcha_solution: str = Form(...),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
):
    tenant = _get_tenant_or_404(db, tenant_slug)
    assignment = _get_assignment_or_404(db, tenant, assignment_slug)

    def _log(status: str, error_message: str | None = None) -> None:
        try:
            repository.insert_upload_log(
                db,
                assignment_id=assignment["id"],
                element_ref=element_ref,
                status=status,
                error_message=error_message,
            )
        except Exception:
            pass

    # Fenster/Deadline + "noch offen"-Status IMMER serverseitig neu pruefen, nie dem Client vertrauen.
    element = element_resolver.resolve_single_element(db, assignment, element_ref)
    if element is None:
        _log("element_closed", "Element ist nicht (mehr) offen")
        raise HTTPException(status_code=400, detail="Element ist nicht (mehr) offen")

    if not await verify_captcha(captcha_solution):
        _log("captcha_failed", "Bot-Verifikation fehlgeschlagen")
        raise HTTPException(status_code=400, detail="Captcha ungueltig")

    if not files:
        _log("validation_failed", "Keine Datei ausgewählt")
        raise HTTPException(status_code=400, detail="Keine Datei ausgewaehlt")
    if len(files) > assignment["max_files_per_element"]:
        _log("validation_failed", f"Zu viele Dateien (max. {assignment['max_files_per_element']})")
        raise HTTPException(status_code=400, detail=f"Maximal {assignment['max_files_per_element']} Dateien erlaubt")

    allowed_types = {str(t).lower().lstrip(".") for t in (assignment["allowed_file_types"] or [])}
    max_bytes = assignment["max_file_size_mb"] * 1024 * 1024

    contents: list[tuple[bytes, str, str | None]] = []
    for upload_file in files:
        suffix = Path(upload_file.filename or "").suffix.lower().lstrip(".")
        if allowed_types and suffix not in allowed_types:
            _log("validation_failed", f"Dateityp nicht erlaubt: .{suffix}")
            raise HTTPException(status_code=400, detail=f"Dateityp '.{suffix}' nicht erlaubt")
        content = await upload_file.read()
        if len(content) > max_bytes:
            _log("validation_failed", f"Datei zu gross: {upload_file.filename} ({len(content) // 1024} KB, max. {assignment['max_file_size_mb']} MB)")
            raise HTTPException(status_code=400, detail=f"Datei zu gross (max. {assignment['max_file_size_mb']} MB)")
        if not _content_matches_extension(content, suffix):
            _log("validation_failed", f"Dateiinhalt passt nicht zur Endung: .{suffix}")
            raise HTTPException(status_code=400, detail=f"Dateiinhalt passt nicht zur angegebenen Endung '.{suffix}'")
        # Server-derived mime type, never the client-sent Content-Type header - see comment above.
        contents.append((content, upload_file.filename or "datei", _EXTENSION_MIME_MAP.get(suffix, "application/octet-stream")))

    _log("upload_received", f"{len(contents)} Datei(en) empfangen")

    incoming_bytes = sum(len(content) for content, _, _ in contents)
    quota_bytes = settings.tenant_storage_quota_mb * 1024 * 1024
    if tenant_storage_bytes(tenant["id"]) + incoming_bytes > quota_bytes:
        _log("validation_failed", f"Speicherlimit des Mandanten erreicht (max. {settings.tenant_storage_quota_mb} MB)")
        raise HTTPException(status_code=400, detail="Speicherlimit erreicht - bitte den Verein kontaktieren")

    def _slugify(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[äÄ]", "ae", text); text = re.sub(r"[öÖ]", "oe", text)
        text = re.sub(r"[üÜ]", "ue", text); text = re.sub(r"ß", "ss", text)
        return re.sub(r"[^a-z0-9]+", "-", text).strip("-")

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    assignment_slug = _slugify(assignment["title"])
    element_slug = _slugify(element.get("label") or element_ref)

    # Step 1: Save ALL files to quarantine first — nothing ever enters regular storage unscanned.
    quarantine_files: list[dict] = []
    for i, (content, original_name, mime_type) in enumerate(contents):
        suffix = Path(original_name).suffix.lower()
        try:
            q_path, checksum = save_to_quarantine(
                content, tenant_id=tenant["id"], assignment_id=assignment["id"], suffix=suffix
            )
        except Exception as exc:
            _log("upload_error", f"Quarantäne-Speicherung fehlgeschlagen: {exc}")
            raise HTTPException(status_code=500, detail="Datei konnte nicht gespeichert werden") from exc
        counter = f"_{i+1}" if len(contents) > 1 else ""
        display_name = f"{assignment_slug}_{element_slug}_{date_str}{counter}{suffix}"
        quarantine_files.append({
            "tenant_id": tenant["id"],
            "original_name": display_name,
            "mime_type": mime_type,
            "storage_path": q_path,
            "file_size_bytes": len(content),
            "checksum_sha256": checksum,
            "_content": content,
        })

    _log("quarantined", "In Quarantäne gespeichert, Scan wird gestartet")

    # Step 2: Scan every file via ClamAV stream.
    scan_results = [
        scanner.scan_bytes(f["_content"], host=settings.clamav_host, port=settings.clamav_port)
        for f in quarantine_files
    ]

    # Step 3: Infected → delete quarantine files, reject upload.
    if "infected" in scan_results:
        for f in quarantine_files:
            try:
                (Path(settings.storage_root) / f["storage_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        _log("scan_infected", "Schadware gefunden – Upload abgelehnt")
        raise HTTPException(status_code=400, detail="Eine oder mehrere Dateien wurden als Schadware eingestuft")

    overall_scan = "pending" if "pending" in scan_results else "clean"

    # Step 4: Clean → move from quarantine to regular storage before DB insert.
    saved_files: list[dict] = []
    for f in quarantine_files:
        file_info = {k: v for k, v in f.items() if k != "_content"}
        if overall_scan == "clean":
            try:
                file_info["storage_path"] = move_from_quarantine(f["storage_path"])
            except Exception as exc:
                _log("upload_error", f"Dateiverschiebung fehlgeschlagen: {exc}")
                raise HTTPException(status_code=500, detail="Datei konnte nicht verschoben werden") from exc
        saved_files.append(file_info)

    if overall_scan == "clean":
        _log("moved_to_storage", "Aus Quarantäne in die Abgabe verschoben")

    # Step 5: Single DB transaction.
    try:
        repository.insert_full_upload(
            db,
            assignment_id=assignment["id"],
            event_id=element["event_id"],
            list_entry_id=element["list_entry_id"],
            files=saved_files,
            scan_status=overall_scan,
        )
    except Exception as exc:
        _log("upload_error", f"Datenbankfehler: {exc}")
        raise

    if overall_scan == "pending":
        _log("scan_pending", "ClamAV nicht erreichbar – Datei in Quarantäne")
    else:
        _log("scan_clean")
    _log("submitted", "Freigegeben")
    return UploadResult(ok=True, files_received=len(contents))
