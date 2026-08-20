from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, datetime
from pathlib import Path

import imagehash
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from app import element_resolver, repository, scanner
from app.captcha import mint_captcha_session_token, verify_captcha, verify_captcha_session_token
from app.config import settings
from app.db import get_db, tenant_upload_lock
from app.schemas import AssignmentDetailPublic, AssignmentPublic, CaptchaVerifyResult, ElementPublic, UploadResult
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
# M20 (2026-08-12 audit): .doc/.xls/.ppt all share this one generic OLE/CFB container signature,
# so a file that is actually a .doc but declared as .xls (or any other combination of the three)
# currently passes this check - only the container format is verified, not which Office app
# produced it. A real sub-type check exists in principle: an OLE/CFB root directory entry carries
# a CLSID (GUID) that differs between Word/Excel/PowerPoint documents, and it's reachable by
# parsing a handful of fields out of the fixed 512-byte header (sector size, first directory
# sector) plus the root entry's fixed-offset CLSID field in that sector - no new dependency
# needed. Deliberately NOT implemented here: doing it correctly requires exact CLSID constants
# and exact byte offsets, and this sandbox has no real .doc/.xls/.ppt sample files (no LibreOffice
# or similar available to generate any) to verify a hand-rolled parser against. A wrong constant
# or off-by-one in the header math would either (a) silently never reject anything - an audit
# finding that looks fixed but isn't - or (b) reject genuine .doc/.xls/.ppt uploads from real
# users, which is worse than today's behavior. The actual security impact of accepting the wrong
# legacy Office sub-type is also limited: unlike the forged-Content-Type issue this file already
# guards against above, all three still end up served as an OLE/CFB blob with a server-controlled
# mime_type from _EXTENSION_MIME_MAP, not e.g. inline-rendered HTML - so this is a data-integrity
# gap (wrong file type accepted), not a code-execution/XSS one. If this is revisited: verify any
# CLSID constants against real sample files first, or take a dependency on a maintained parser
# (e.g. olefile) instead of a hand-rolled one - either beats guessing.
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


# H11 (2026-08-12 Audit): hard per-request cap, independent of whatever a tenant's
# assignment.max_file_size_mb / max_files_per_element happen to be configured to (validated only
# up to 100 MB / 20 files each in the main backend, see backend/app/schemas/submission.py) - this
# is the worst-case legitimate total (20 x 100 MB) either of those two DB-driven settings could
# ever combine to, so it can never reject a real upload while still giving this route its own
# fixed ceiling instead of an unbounded one. The abgabebox-upload-body-limit Traefik middleware
# (docker-compose.yml) enforces the same number one layer earlier, before this application code -
# or even Starlette's multipart parser - ever runs; keep both numbers in sync.
MAX_UPLOAD_REQUEST_BYTES = 20 * 100 * 1024 * 1024  # 2000 MB

_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Hamming-Distanz (von 64 Bit) zweier pHashes, ab der zwei Bilder als "wahrscheinlich
# dasselbe Motiv" gelten - gleicher Richtwert wie backend/app/services/file_service.py
# (bewusst dupliziert statt geteilt, siehe _read_upload_within_limit-Docstring oben).
PERCEPTUAL_DUPLICATE_THRESHOLD = 5


def _compute_perceptual_hash(content: bytes, mime_type: str) -> str | None:
    """DCT-based perceptual hash (pHash) for the tenant-wide image-similarity warning.
    Returns None for non-image mime types or content PIL can't decode."""
    if mime_type not in _IMAGE_MIME_TYPES:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            return str(imagehash.phash(image))
    except Exception:
        return None


def _has_close_perceptual_match(perceptual_hash: str, candidates: list[str]) -> bool:
    this_hash = imagehash.hex_to_hash(perceptual_hash)
    return any(this_hash - imagehash.hex_to_hash(candidate) <= PERCEPTUAL_DUPLICATE_THRESHOLD for candidate in candidates)


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes | None:
    """Defense in depth for H11: rejects an oversized upload using Starlette's already-known
    `.size` (populated by the multipart parser before the route runs) instead of unconditionally
    buffering the whole thing into a second `bytes` object first just to measure it - a file
    already known to be oversized never gets that extra full copy. Same pattern as
    backend/app/api/routes/word_import.py's _read_upload_within_limit, deliberately duplicated
    rather than imported to keep this public-facing service's dependency surface isolated from
    the main backend (see storage.py's move_from_quarantine docstring for the same rationale
    elsewhere in this file).

    This alone does NOT stop Starlette from buffering the entire request body to disk before the
    route (and therefore this function) ever runs - that's what the Traefik maxRequestBodyBytes
    middleware above is for. Returns None if too large."""
    if file.size is not None and file.size > max_bytes:
        return None
    content = await file.read()
    if len(content) > max_bytes:
        return None
    return content


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
            uploaded_count=element["uploaded_count"],
        )
        for element in elements
    ]


@router.post(
    "/public/{tenant_slug}/assignments/{assignment_slug}/elements/{element_ref}/captcha-verify",
    response_model=CaptchaVerifyResult,
)
async def verify_captcha_for_element(
    tenant_slug: str,
    assignment_slug: str,
    element_ref: str,
    captcha_solution: str = Form(...),
    db: Session = Depends(get_db),
):
    """Called once when the upload page loads (widget solves automatically), not per upload -
    see upload() below, which accepts the resulting session token instead of a raw
    captcha_solution so a visitor doesn't have to pass the bot-check again for every file."""
    tenant = _get_tenant_or_404(db, tenant_slug)
    assignment = _get_assignment_or_404(db, tenant, assignment_slug)
    element = element_resolver.resolve_single_element(db, assignment, element_ref)
    if element is None:
        raise HTTPException(status_code=400, detail="Element ist nicht (mehr) offen")
    if not await verify_captcha(captcha_solution):
        raise HTTPException(status_code=400, detail="Captcha ungueltig")
    token = mint_captcha_session_token(tenant_slug, assignment_slug, element_ref)
    return CaptchaVerifyResult(session_token=token, expires_in_seconds=settings.captcha_session_ttl_minutes * 60)


@router.post(
    "/public/{tenant_slug}/assignments/{assignment_slug}/elements/{element_ref}/upload",
    response_model=UploadResult,
)
async def upload(
    tenant_slug: str,
    assignment_slug: str,
    element_ref: str,
    captcha_session_token: str = Form(...),
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

    # 401 statt 400: das Frontend unterscheidet daran "Sicherheitscheck abgelaufen, bitte neu
    # verifizieren" (Widget erneut ausloesen) von den echten Validierungsfehlern unten (400).
    if not verify_captcha_session_token(captcha_session_token, tenant_slug, assignment_slug, element_ref):
        _log("captcha_failed", "Bot-Verifikation fehlgeschlagen oder Sicherheitscheck abgelaufen")
        raise HTTPException(status_code=401, detail="Sicherheitscheck abgelaufen - bitte kurz warten")

    if not files:
        _log("validation_failed", "Keine Datei ausgewählt")
        raise HTTPException(status_code=400, detail="Keine Datei ausgewaehlt")

    # Kumulatives Modell (seit 2026-08-17): max_files_per_element gilt fuer die Gesamtzahl ueber
    # alle bisherigen Upload-Vorgaenge dieses Elements hinweg, nicht nur fuer diese eine Anfrage.
    # None = unbegrenzt viele Dateien.
    max_files = assignment["max_files_per_element"]
    if max_files is not None:
        already_uploaded = repository.count_files_by_element(db, assignment_id=assignment["id"]).get(
            (element["event_id"], element["list_entry_id"]), 0
        )
        remaining = max(0, max_files - already_uploaded)
        if len(files) > remaining:
            _log("validation_failed", f"Zu viele Dateien (max. {max_files} insgesamt, {remaining} noch moeglich)")
            raise HTTPException(
                status_code=400,
                detail=f"Maximal {max_files} Dateien insgesamt erlaubt ({remaining} noch möglich)",
            )

    allowed_types = {str(t).lower().lstrip(".") for t in (assignment["allowed_file_types"] or [])}
    max_bytes = assignment["max_file_size_mb"] * 1024 * 1024

    contents: list[tuple[bytes, str, str | None]] = []
    total_bytes_read = 0
    for upload_file in files:
        suffix = Path(upload_file.filename or "").suffix.lower().lstrip(".")
        if allowed_types and suffix not in allowed_types:
            _log("validation_failed", f"Dateityp nicht erlaubt: .{suffix}")
            raise HTTPException(status_code=400, detail=f"Dateityp '.{suffix}' nicht erlaubt")
        # H11: bounded read (see _read_upload_within_limit above) instead of an unconditional
        # `await upload_file.read()` on the whole body.
        content = await _read_upload_within_limit(upload_file, max_bytes)
        if content is None:
            _log("validation_failed", f"Datei zu gross: {upload_file.filename} (max. {assignment['max_file_size_mb']} MB)")
            raise HTTPException(status_code=400, detail=f"Datei zu gross (max. {assignment['max_file_size_mb']} MB)")
        total_bytes_read += len(content)
        if total_bytes_read > MAX_UPLOAD_REQUEST_BYTES:
            _log("validation_failed", f"Upload insgesamt zu gross ({total_bytes_read // 1024 // 1024} MB)")
            raise HTTPException(status_code=400, detail="Upload insgesamt zu gross")
        if not _content_matches_extension(content, suffix):
            _log("validation_failed", f"Dateiinhalt passt nicht zur Endung: .{suffix}")
            raise HTTPException(status_code=400, detail=f"Dateiinhalt passt nicht zur angegebenen Endung '.{suffix}'")
        # Server-derived mime type, never the client-sent Content-Type header - see comment above.
        contents.append((content, upload_file.filename or "datei", _EXTENSION_MIME_MAP.get(suffix, "application/octet-stream")))

    _log("upload_received", f"{len(contents)} Datei(en) empfangen")

    # Exakt-Duplikat-Pruefung (SHA-256): dieselbe Datei darf nicht zweimal fuer dasselbe
    # Element landen - weder zweimal in diesem Request noch erneut in einem spaeteren.
    # Laeuft bewusst vor jeglichem Quarantaene-Schreiben (siehe Schritt 1 unten), damit ein
    # Duplikat abgelehnt wird, ohne dass ueberhaupt etwas auf Platte geschrieben wurde.
    checksums = [hashlib.sha256(content).hexdigest() for content, _, _ in contents]
    existing_checksums = repository.list_checksums_for_element(
        db, assignment_id=assignment["id"], event_id=element["event_id"], list_entry_id=element["list_entry_id"]
    )
    seen_in_request: set[str] = set()
    for (_content, original_name, _mime), checksum in zip(contents, checksums):
        if checksum in seen_in_request or checksum in existing_checksums:
            _log("validation_failed", f"Datei bereits hochgeladen: {original_name}")
            raise HTTPException(status_code=400, detail=f"Datei '{original_name}' wurde bereits hochgeladen")
        seen_in_request.add(checksum)

    # Bild-Aehnlichkeitspruefung (Perceptual Hash): nur Warnung, blockiert nicht - siehe
    # _compute_perceptual_hash. Mandantenweit statt element-scoped, und erfasst dank der
    # gemeinsamen stored_file-Tabelle automatisch auch Protokoll-Bilder aus dem Haupt-Backend.
    perceptual_hashes = [_compute_perceptual_hash(content, mime) for content, _, mime in contents]
    tenant_image_hashes = [phash for _id, phash in repository.list_tenant_image_hashes(db, tenant_id=tenant["id"])]
    image_duplicate_warnings: list[str] = []
    for i, ((_content, original_name, _mime), phash) in enumerate(zip(contents, perceptual_hashes)):
        if phash is None:
            continue
        other_hashes_in_request = [h for j, h in enumerate(perceptual_hashes) if h is not None and j != i]
        if _has_close_perceptual_match(phash, tenant_image_hashes + other_hashes_in_request):
            image_duplicate_warnings.append(f"{original_name} ähnelt einem bereits im Mandanten hochgeladenen Bild.")

    incoming_bytes = sum(len(content) for content, _, _ in contents)
    quota_bytes = settings.tenant_storage_quota_mb * 1024 * 1024

    def _slugify(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[äÄ]", "ae", text); text = re.sub(r"[öÖ]", "oe", text)
        text = re.sub(r"[üÜ]", "ue", text); text = re.sub(r"ß", "ss", text)
        return re.sub(r"[^a-z0-9]+", "-", text).strip("-")

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    assignment_slug = _slugify(assignment["title"])
    element_slug = _slugify(element.get("label") or element_ref)

    # H12: quota check + Step 1 (writing to quarantine, which is what actually changes what
    # tenant_storage_bytes() sees) both happen inside a per-tenant advisory lock so two
    # near-simultaneous uploads for the same tenant can't both pass the check before either has
    # written its bytes to disk (TOCTOU) - see db.tenant_upload_lock for the full rationale,
    # including why this is a cross-process Postgres lock and not an in-process asyncio.Lock.
    quarantine_files: list[dict] = []
    with tenant_upload_lock(tenant["id"]):
        if tenant_storage_bytes(tenant["id"]) + incoming_bytes > quota_bytes:
            _log("validation_failed", f"Speicherlimit des Mandanten erreicht (max. {settings.tenant_storage_quota_mb} MB)")
            raise HTTPException(status_code=400, detail="Speicherlimit erreicht - bitte den Verein kontaktieren")

        # Step 1: Save ALL files to quarantine first — nothing ever enters regular storage unscanned.
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
                "perceptual_hash": perceptual_hashes[i],
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
        # M16: files were already moved out of quarantine (Step 4) before this insert, and
        # regular storage - unlike quarantine/ - has no age-based cleanup loop at all (see
        # cleanup_stale_quarantine_files's docstring in storage.py), so a failed insert here
        # would otherwise leave them on disk forever with no DB row and no reaper to catch
        # them. Delete them back out rather than reordering Step 4/5 (which would need the
        # DB row to exist before the file is confirmed moved, trading one orphan class for
        # another - a DB row pointing at a file that never made it out of quarantine).
        for f in saved_files:
            try:
                (Path(settings.storage_root) / f["storage_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        _log("upload_error", f"Datenbankfehler: {exc}")
        raise

    if overall_scan == "pending":
        _log("scan_pending", "ClamAV nicht erreichbar – Datei in Quarantäne")
    else:
        _log("scan_clean")
    _log("submitted", "Freigegeben")
    return UploadResult(ok=True, files_received=len(contents), image_duplicate_warnings=image_duplicate_warnings)
