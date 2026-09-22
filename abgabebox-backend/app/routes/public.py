from __future__ import annotations

import asyncio
import hashlib
import io
import re
from datetime import UTC, datetime
from pathlib import Path

import imagehash
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from app import element_resolver, repository, scanner
from app.captcha import mint_captcha_session_token, verify_captcha, verify_captcha_session_token
from app.config import settings
from app.db import get_db, serialized_upload, tenant_upload_lock
from app.schemas import AssignmentDetailPublic, AssignmentPublic, CaptchaVerifyResult, ElementPublic, UploadResult
from app.storage import move_from_quarantine, save_to_quarantine, tenant_storage_bytes


def _client_ip(request: Request) -> str | None:
    """The real client address, not request.client.host - this service sits behind Traefik
    (client -> Traefik -> this container), so request.client.host would always be Traefik's
    own address. Traefik is the sole hop in front of this service and always sets
    X-Forwarded-For itself on every request it proxies, so trusting its first entry here
    doesn't open a spoofing path a request could otherwise reach this code through directly."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None

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
    "pages": "application/vnd.apple.pages",
    "key": "application/vnd.apple.keynote",
    "numbers": "application/vnd.apple.numbers",
    "heic": "image/heic",
    "heif": "image/heif",
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
# .pages/.key/.numbers exported as a single file (the normal case, no "Package" option) are
# also just zip containers, like .docx/.xlsx/.pptx above - same signature, different extension.

# ftyp-Hauptmarken (Bytes 8-12) von HEIC/HEIF-Bildern; identische Liste wie in
# backend/app/services/apple_media.py. Absichtlich hier dupliziert statt importiert - siehe
# _read_upload_within_limit weiter unten zur Isolation von abgabebox-backend vom Hauptbackend.
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


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
    if extension in ("docx", "xlsx", "pptx", "pages", "key", "numbers"):
        return head.startswith(_ZIP_SIGNATURE)
    if extension in ("doc", "xls", "ppt"):
        return head.startswith(_OLE_SIGNATURE)
    if extension in ("heic", "heif"):
        return len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in _HEIF_BRANDS
    return False


# H11 (2026-08-12 Audit) had set this to the worst-case legitimate total (20 files x 100 MB
# = 2000 MB) either of a tenant's assignment.max_file_size_mb/max_files_per_element settings
# could ever combine to, reasoning it could then never reject a real upload. But every file in
# `files` gets read into memory and held there (in `contents` below) simultaneously through
# checksum/perceptual-hash computation and quarantine-writing, all before this request can
# release any of it - a legitimate-per-that-reasoning ~500 MB-2000 MB upload comfortably clears
# this cap yet reliably OOM-kills the whole abgabebox-backend container (mem_limit: 384m in
# docker-compose.yml, 2 workers), taking down every tenant's submission box at once, not just
# the uploader's (audit finding, 2026-08-25). Lowered to a ceiling this container can actually
# survive rather than one merely reachable in theory - a proper fix would stream each file to
# quarantine as it's read instead of accumulating all of them in memory first, but that touches
# every validation step below (dedup, perceptual-hash cross-comparison, quota) that currently
# assumes the whole batch is available in memory at once; recalibrating the cap is the safe,
# contained fix for this pass. The abgabebox-upload-body-limit Traefik middleware
# (docker-compose.yml) enforces the same number one layer earlier; keep both in sync.
MAX_UPLOAD_REQUEST_BYTES = 150 * 1024 * 1024  # 150 MB

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


def _exceeds_max_files_per_request(file_count: int) -> bool:
    """(Critical, audit finding 2026-08-27): a hard, tenant-config-independent ceiling on how
    many files a single request may contain. assignment.max_files_per_element (checked further
    below in upload(), against the DB) may legitimately be None ("unbegrenzt Dateien"), which
    used to mean there was NO application-level cap on this request at all - only Starlette's
    own default (1000 files/request) stood between one request and a sequential, per-file
    ClamAV scan (each up to a 30s clamd socket timeout) of up to 1000 files, tying up a worker
    for a very long time. This check is independent of max_files_per_element and always applies,
    even when that setting is unbounded. Extracted as its own function (same reasoning as
    _read_upload_within_limit above) so it's directly unit-testable without a full tenant/
    assignment/DB fixture."""
    return file_count > settings.max_files_per_upload_request


# secrets.token_urlsafe(24) - 32 Zeichen URL-safe Base64. Grosszuegig begrenzt, damit ein
# spaeter laengeres Token nicht sofort alle Links bricht; alles andere ist garantiert kein
# Token und wird ohne DB-Zugriff abgelehnt.
_LINK_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _get_tenant_or_404(db: Session, link_token: str) -> dict:
    """Resolves the link token (the URL's only credential) to the tenant it belongs to. The
    returned dict carries the link id too, so every later lookup is scoped to what THIS link may
    reach - an unknown/malformed token and a token without any matching Abgabe both end in the
    same 404, revealing nothing about which tenants or Abgaben exist."""
    if not _LINK_TOKEN_PATTERN.fullmatch(link_token):
        raise NOT_FOUND
    link = repository.get_link_by_token(db, token=link_token)
    if link is None:
        raise NOT_FOUND
    return {"id": link["tenant_id"], "link_id": link["id"]}


def _get_assignment_or_404(db: Session, tenant: dict, assignment_slug: str) -> dict:
    assignment = repository.get_assignment_by_slug(
        db, tenant_id=tenant["id"], link_id=tenant["link_id"], public_slug=assignment_slug
    )
    if assignment is None:
        raise NOT_FOUND
    return assignment


@router.get("/public/{link_token}/assignments", response_model=list[AssignmentPublic])
def list_assignments(link_token: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, link_token)
    assignments = repository.list_active_assignments(db, tenant_id=tenant["id"], link_id=tenant["link_id"])
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
    "/public/{link_token}/assignments/{assignment_slug}",
    response_model=AssignmentDetailPublic,
)
def get_assignment(link_token: str, assignment_slug: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, link_token)
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
    "/public/{link_token}/assignments/{assignment_slug}/elements",
    response_model=list[ElementPublic],
)
def list_elements(link_token: str, assignment_slug: str, db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, link_token)
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
    "/public/{link_token}/assignments/{assignment_slug}/elements/{element_ref}/captcha-verify",
    response_model=CaptchaVerifyResult,
)
async def verify_captcha_for_element(
    request: Request,
    link_token: str,
    assignment_slug: str,
    element_ref: str,
    captcha_solution: str = Form(...),
    db: Session = Depends(get_db),
):
    """Called once when the upload page loads (widget solves automatically), not per upload -
    see upload() below, which accepts the resulting session token instead of a raw
    captcha_solution so a visitor doesn't have to pass the bot-check again for every file."""
    tenant = _get_tenant_or_404(db, link_token)
    assignment = _get_assignment_or_404(db, tenant, assignment_slug)
    element = element_resolver.resolve_single_element(db, assignment, element_ref)
    if element is None:
        raise HTTPException(status_code=400, detail="Element ist nicht (mehr) offen")
    if not await verify_captcha(captcha_solution):
        raise HTTPException(status_code=400, detail="Captcha ungueltig")
    token = mint_captcha_session_token(link_token, assignment_slug, element_ref, client_ip=_client_ip(request))
    return CaptchaVerifyResult(session_token=token, expires_in_seconds=settings.captcha_session_ttl_minutes * 60)


@router.post(
    "/public/{link_token}/assignments/{assignment_slug}/elements/{element_ref}/upload",
    response_model=UploadResult,
)
async def upload(
    request: Request,
    link_token: str,
    assignment_slug: str,
    element_ref: str,
    captcha_session_token: str = Form(...),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
):
    tenant = _get_tenant_or_404(db, link_token)
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
    if not verify_captcha_session_token(captcha_session_token, link_token, assignment_slug, element_ref, client_ip=_client_ip(request)):
        _log("captcha_failed", "Bot-Verifikation fehlgeschlagen oder Sicherheitscheck abgelaufen")
        raise HTTPException(status_code=401, detail="Sicherheitscheck abgelaufen - bitte kurz warten")

    if not files:
        _log("validation_failed", "Keine Datei ausgewählt")
        raise HTTPException(status_code=400, detail="Keine Datei ausgewaehlt")

    # Checked before anything about any of `files` is read or scanned - see
    # _exceeds_max_files_per_request's docstring above.
    if _exceeds_max_files_per_request(len(files)):
        _log(
            "validation_failed",
            f"Zu viele Dateien in einer Anfrage ({len(files)}, max. {settings.max_files_per_upload_request})",
        )
        raise HTTPException(
            status_code=400,
            detail=f"Maximal {settings.max_files_per_upload_request} Dateien pro Anfrage erlaubt",
        )

    max_files = assignment["max_files_per_element"]

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

    # Hold across checksum lookup, scan and the final database commit.
    async with serialized_upload(tenant["id"]):
        # Identical submissions are silently acknowledged, before image decoding or ClamAV.
        # Keep the received count stable so the public response does not reveal duplicates.
        files_received = len(contents)
        existing_checksums = repository.list_checksums_for_element(
            db, assignment_id=assignment["id"], event_id=element["event_id"], list_entry_id=element["list_entry_id"]
        )
        unique_contents = []
        checksums = []
        for item in contents:
            checksum = hashlib.sha256(item[0]).hexdigest()
            if checksum not in existing_checksums:
                unique_contents.append(item)
                checksums.append(checksum)
                existing_checksums.add(checksum)
        contents = unique_contents
        if not contents:
            return UploadResult(ok=True, files_received=files_received, image_duplicate_warnings=[])

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
            existing_checksums_locked = repository.list_checksums_for_element(
                db, assignment_id=assignment["id"], event_id=element["event_id"], list_entry_id=element["list_entry_id"]
            )
            remaining_files = [
                (item, checksum, phash)
                for item, checksum, phash in zip(contents, checksums, perceptual_hashes)
                if checksum not in existing_checksums_locked
            ]
            if not remaining_files:
                return UploadResult(ok=True, files_received=files_received, image_duplicate_warnings=[])
            contents = [item for item, _, _ in remaining_files]
            checksums = [checksum for _, checksum, _ in remaining_files]
            perceptual_hashes = [phash for _, _, phash in remaining_files]
            incoming_bytes = sum(len(content) for content, _, _ in contents)

            # (Medium, audit finding 2026-08-27): tenant_storage_bytes() does a synchronous
            # Path.rglob()+stat() walk over every file ever stored for this tenant - cost grows with
            # total accumulated files, and it's called here while holding the cross-process
            # tenant_upload_lock above. Run off the event loop via asyncio.to_thread so a tenant with
            # a lot of accumulated files doesn't freeze this worker (and everyone else on it) for the
            # duration of the walk. A running per-tenant byte counter would avoid the walk
            # altogether, but this storage_root is also written to directly by the separate main
            # backend (see storage.py's move_from_quarantine docstring - the quarantine-path
            # transform, and therefore the files landing under the same tenant-N/ directories, is
            # shared with backend/app/services/submission_service.py's rescan/move flow), so an
            # in-process counter maintained only here could not stay accurate; asyncio.to_thread is
            # the safe, contained fix for this pass.
            if await asyncio.to_thread(tenant_storage_bytes, tenant["id"]) + incoming_bytes > quota_bytes:
                _log("validation_failed", f"Speicherlimit des Mandanten erreicht (max. {settings.tenant_storage_quota_mb} MB)")
                raise HTTPException(status_code=400, detail="Speicherlimit erreicht - bitte den Verein kontaktieren")

            # Authoritative re-check of max_files_per_element, now inside the same per-tenant
            # lock the quota check above uses (audit finding, 2026-08-25) - this is what
            # actually closes the TOCTOU the early check above can't: no other upload for this
            # tenant can be mid-write while this re-count runs, so "already_uploaded" here is
            # guaranteed accurate at the moment this request commits to writing its own files.
            if max_files is not None:
                already_uploaded = repository.count_files_by_element(db, assignment_id=assignment["id"]).get(
                    (element["event_id"], element["list_entry_id"]), 0
                )
                if already_uploaded + len(contents) > max_files:
                    remaining = max(0, max_files - already_uploaded)
                    _log("validation_failed", f"Zu viele Dateien (max. {max_files} insgesamt, {remaining} noch moeglich)")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Maximal {max_files} Dateien insgesamt erlaubt ({remaining} noch möglich)",
                    )

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
        # (Critical, audit finding 2026-08-27): scanner.scan_bytes() is a blocking call (raw
        # synchronous clamd socket, up to a 30s timeout) - calling it directly here would block this
        # entire async worker (every tenant, every other in-flight request) for the duration of each
        # scan. scan_many() runs each scan in a worker thread (asyncio.to_thread) with a small bounded
        # concurrency instead of a fully sequential loop - see scanner.py for the full rationale.
        scan_results = await scanner.scan_many(
            [f["_content"] for f in quarantine_files], host=settings.clamav_host, port=settings.clamav_port
        )

        # Step 3: Infected → delete quarantine files, reject upload.
        if "infected" in scan_results:
            for f in quarantine_files:
                try:
                    (Path(settings.storage_root) / f["storage_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
            _log("scan_infected", "Schadware gefunden – Upload abgelehnt")
            raise HTTPException(status_code=400, detail="Eine oder mehrere Dateien wurden als Schadware eingestuft")

        # Per-file, not a single overall_scan applied to the whole batch (audit finding,
        # 2026-08-25) - ClamAV being unreachable for just one file out of several used to hold
        # every file in this request back in quarantine, including ones that scanned cleanly,
        # instead of only the one actually still pending.
        any_pending = "pending" in scan_results

        # Step 4: Clean → move from quarantine to regular storage before DB insert; pending
        # stays in quarantine untouched (the rescan sweep resolves it later).
        saved_files: list[dict] = []
        for f, status in zip(quarantine_files, scan_results):
            file_info = {k: v for k, v in f.items() if k != "_content"}
            file_info["scan_status"] = status
            if status == "clean":
                try:
                    file_info["storage_path"] = move_from_quarantine(f["storage_path"])
                except Exception as exc:
                    _log("upload_error", f"Dateiverschiebung fehlgeschlagen: {exc}")
                    raise HTTPException(status_code=500, detail="Datei konnte nicht verschoben werden") from exc
            saved_files.append(file_info)

        if not any_pending:
            _log("moved_to_storage", "Aus Quarantäne in die Abgabe verschoben")

        # Step 5: Single DB transaction.
        try:
            repository.insert_full_upload(
                db,
                assignment_id=assignment["id"],
                event_id=element["event_id"],
                list_entry_id=element["list_entry_id"],
                files=saved_files,
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

        if any_pending:
            pending_count = sum(1 for status in scan_results if status == "pending")
            _log("scan_pending", f"ClamAV nicht erreichbar – {pending_count} von {len(scan_results)} Datei(en) in Quarantäne")
        if any(status == "clean" for status in scan_results):
            _log("scan_clean")
        _log("submitted", "Freigegeben")
        return UploadResult(ok=True, files_received=files_received, image_duplicate_warnings=image_duplicate_warnings)
