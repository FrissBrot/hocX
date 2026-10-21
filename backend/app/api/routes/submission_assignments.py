from __future__ import annotations

import io
import re
import uuid
import zipfile

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_abgabebox_read, require_abgabebox_write
from app.models.entities import SubmissionAssignment, SubmissionUpload, StoredFile
from app.schemas.files import StoredFileMetadata, StoredFileTagsUpdate
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentRead,
    SubmissionAssignmentUpdate,
    SubmissionElementRead,
    SubmissionLinkCreate,
    SubmissionLinkRead,
    SubmissionLinkUpdate,
    SubmissionUploadLogEntry,
)
from app.schemas.deletion import DeletionPreview, DeletionRequest, DeletionResultRead
from app.services import deletion_service, public_id_service
from app.services.audit_service import AuditService
from app.core.storage import ABGABEBOX, get_object_store, object_response, write_object_to_zip
from app.services.file_service import FileService
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService

router = APIRouter()
service = SubmissionService()
link_service = SubmissionLinkService()
file_service = FileService()
audit = AuditService()


def _get_assignment_or_404(db: Session, assignment_id: uuid.UUID, user: CurrentUser) -> SubmissionAssignment:
    assignment = public_id_service.get_by_public_id(db, SubmissionAssignment, assignment_id, tenant_id=user.current_tenant_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return assignment


def _get_link_or_404(db: Session, link_id: uuid.UUID, user: CurrentUser):
    link = link_service.get_link(db, link_id, tenant_id=user.current_tenant_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link nicht gefunden")
    return link


@router.get("/submission-links", response_model=list[SubmissionLinkRead])
def list_links(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    return link_service.list_links(db, tenant_id=user.current_tenant_id)


@router.post("/submission-links", response_model=SubmissionLinkRead, status_code=status.HTTP_201_CREATED)
def create_link(
    payload: SubmissionLinkCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    try:
        return link_service.create_link(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Link konnte nicht erstellt werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.patch("/submission-links/{link_id}", response_model=SubmissionLinkRead)
def patch_link(
    link_id: uuid.UUID,
    payload: SubmissionLinkUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    link = _get_link_or_404(db, link_id, user)
    try:
        return link_service.update_link(db, link, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Link konnte nicht aktualisiert werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.post("/submission-links/{link_id}/regenerate", response_model=SubmissionLinkRead)
def regenerate_link(
    link_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Issues a new token - the old URL stops working immediately."""
    require_abgabebox_write(user)
    link = _get_link_or_404(db, link_id, user)
    try:
        result = link_service.regenerate_token(db, link)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Link konnte nicht erneuert werden") from exc
    for assignment in link_service.assignments_for_link(db, link):
        service.refresh_todo_links(db, assignment)
    return result


@router.delete("/submission-links/{link_id}", response_model=dict[str, str])
def delete_link(
    link_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    link = _get_link_or_404(db, link_id, user)
    affected = link_service.assignments_for_link(db, link)
    try:
        link_service.delete_link(db, link)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Link konnte nicht geloescht werden") from exc
    for assignment in affected:
        service.refresh_todo_links(db, assignment)
    return {"message": "Link geloescht"}


@router.get("/submission-assignments", response_model=list[SubmissionAssignmentRead])
def list_assignments(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    return service.list_assignments(db, tenant_id=user.current_tenant_id)


@router.post("/submission-assignments", response_model=SubmissionAssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: SubmissionAssignmentCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    try:
        return service.create_assignment(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Abgabe konnte nicht erstellt werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.patch("/submission-assignments/{assignment_id}", response_model=SubmissionAssignmentRead)
def patch_assignment(
    assignment_id: uuid.UUID,
    payload: SubmissionAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    current = _get_assignment_or_404(db, assignment_id, user)
    try:
        updated = service.update_assignment(db, current.id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Abgabe konnte nicht aktualisiert werden"
        raise HTTPException(status_code=400, detail=detail) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return updated


def _delete_assignment_with_files(db: Session, current: SubmissionAssignment, user: CurrentUser, delete_file_ids: set[uuid.UUID] | None) -> DeletionResultRead:
    """Gemeinsamer Ablauf von DELETE (alle Dateien) und POST …/delete (Auswahl) - PRIV-003."""
    assignment_id, title = current.id, current.title
    try:
        result = deletion_service.delete_assignment(db, current, delete_file_ids=delete_file_ids, actor_user_id=user.user_id, file_service=file_service)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Abgabe konnte nicht geloescht werden") from exc
    audit.log(
        db, action="submission_assignment.deleted", actor=user, entity_type="submission_assignment", entity_id=assignment_id,
        details={"title": title, "deleted_files": result.deleted_files, "kept_files": result.kept_files},
    )
    return DeletionResultRead(deleted_files=result.deleted_files, kept_files=result.kept_files, untouched_files=result.untouched_files)


@router.get("/submission-assignments/{assignment_id}/deletion-preview", response_model=DeletionPreview)
def preview_assignment_deletion(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Eingereichte Dateien und Galeriefotos der Abgabe für den Lösch-Dialog (PRIV-003)."""
    require_abgabebox_write(user)
    current = _get_assignment_or_404(db, assignment_id, user)
    return deletion_service.preview_read(deletion_service.assignment_preview(db, current))


@router.post("/submission-assignments/{assignment_id}/delete", response_model=DeletionResultRead)
def delete_assignment_with_selection(
    assignment_id: uuid.UUID,
    payload: DeletionRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Löscht die Abgabe; gewählte Dateien werden mitgelöscht, die übrigen in die Galerie übernommen."""
    require_abgabebox_write(user)
    current = _get_assignment_or_404(db, assignment_id, user)
    return _delete_assignment_with_files(db, current, user, set(payload.delete_file_ids))


@router.delete("/submission-assignments/{assignment_id}", response_model=dict[str, str])
def delete_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Ohne Auswahl: alle eingereichten Dateien und Galeriefotos der Abgabe werden mitgelöscht."""
    require_abgabebox_write(user)
    current = _get_assignment_or_404(db, assignment_id, user)
    _delete_assignment_with_files(db, current, user, None)
    return {"message": "Abgabe geloescht"}


def _get_own_upload_or_404(db: Session, upload_id: uuid.UUID, user: CurrentUser) -> SubmissionUpload:
    upload = public_id_service.get_by_public_id(db, SubmissionUpload, upload_id)  # nosemgrep: public-id-lookup-without-tenant -- Mandant wird direkt danach über die Abgabe geprüft
    assignment = service.get_assignment(db, upload.assignment_id) if upload is not None else None
    if upload is None or assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Einreichung nicht gefunden")
    return upload


@router.delete("/submission-uploads/{upload_id}", response_model=dict[str, int])
def delete_submission_upload(
    upload_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Eine Einreichung samt Dateien endgültig löschen (z. B. auf Wunsch der einreichenden Person)."""
    require_abgabebox_write(user)
    upload = _get_own_upload_or_404(db, upload_id, user)
    rows = [(upload_file, stored_file) for upload_file, stored_file in service.repository.list_upload_files(db, upload_id=upload.id)]
    upload_internal_id = upload.id
    try:
        if rows:
            deleted = deletion_service.delete_submission_files(db, rows, file_service=file_service)
        else:
            deleted = 0
            db.delete(upload)
            db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Einreichung konnte nicht geloescht werden") from exc
    audit.log(db, action="submission_upload.deleted", actor=user, entity_type="submission_upload", entity_id=upload_internal_id, details={"deleted_files": deleted})
    return {"deleted_files": deleted}


@router.delete("/submission-uploads/{upload_id}/files/{file_id}", response_model=dict[str, int])
def delete_submission_file(
    upload_id: uuid.UUID,
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Eine eingereichte Datei endgültig löschen; eine dadurch leere Einreichung verschwindet mit."""
    require_abgabebox_write(user)
    upload = _get_own_upload_or_404(db, upload_id, user)
    rows = [(upload_file, stored_file) for upload_file, stored_file in service.repository.list_upload_files(db, upload_id=upload.id) if stored_file.public_id == file_id]
    if not rows:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    upload_internal_id = upload.id
    try:
        deleted = deletion_service.delete_submission_files(db, rows, file_service=file_service)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Datei konnte nicht geloescht werden") from exc
    audit.log(db, action="submission_file.deleted", actor=user, entity_type="submission_upload", entity_id=upload_internal_id, details={"deleted_files": deleted})
    return {"deleted_files": deleted}


@router.get("/submission-assignments/{assignment_id}/elements", response_model=list[SubmissionElementRead])
def list_elements(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    return service.get_assignment_elements(db, assignment)


@router.post("/submission-assignments/{assignment_id}/elements/{element_ref}/reopen", response_model=SubmissionElementRead)
def reopen_element(
    assignment_id: uuid.UUID,
    element_ref: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    try:
        return service.reopen_element(db, assignment, element_ref)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Element konnte nicht wieder aufgeschaltet werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.post("/submission-assignments/{assignment_id}/elements/{element_ref}/close", response_model=SubmissionElementRead)
def close_element(
    assignment_id: uuid.UUID,
    element_ref: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    try:
        return service.close_element(db, assignment, element_ref)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Element konnte nicht geschlossen werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/submission-uploads/{upload_id}/files/{file_id}/content")
def get_submission_file_content(
    upload_id: uuid.UUID,
    file_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]  # None nur bei direktem Aufruf in Tests
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    upload = public_id_service.get_by_public_id(db, SubmissionUpload, upload_id)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, file_id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    upload, stored_file = service.get_stored_file_for_upload(db, upload_id=upload.id, stored_file_id=stored_file.id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    assignment = service.get_assignment(db, upload.assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if stored_file.scan_status == "error":
        raise HTTPException(422, "Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=423, detail="Datei wird noch auf Viren geprüft")
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde als Schadware eingestuft und gesperrt")
    mime = stored_file.mime_type or "application/octet-stream"
    # SECURITY: only ever trust the stored mime_type, never the filename - abgabebox uploads now
    # derive mime_type server-side from verified file content (see _EXTENSION_MIME_MAP in
    # abgabebox-backend/app/routes/public.py), so this is safe to rely on. Everything that isn't
    # a verified PDF is forced to "attachment" + nosniff so a browser never renders it inline,
    # regardless of what mime_type ends up being.
    is_pdf = mime.lower() == "application/pdf"
    disposition = "inline" if is_pdf else "attachment"
    return object_response(
        request,
        ABGABEBOX,
        stored_file.storage_path,
        media_type=mime,
        filename=stored_file.original_name,
        attachment=disposition == "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
        not_found_detail="Datei fehlt im Dateisystem",
    )


@router.get("/submission-uploads/{upload_id}/files/{file_id}/thumbnail")
def get_submission_file_thumbnail(
    upload_id: uuid.UUID,
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Small JPEG preview for the "Dateien" grid - same access rules as
    get_submission_file_content. Generated lazily on first request since abgabebox-backend's
    restricted DB role never sets thumbnail_path itself (see FileService.ensure_thumbnail)."""
    require_abgabebox_read(user)
    upload_public = public_id_service.get_by_public_id(db, SubmissionUpload, upload_id)
    stored_file_public = public_id_service.get_by_public_id(db, StoredFile, file_id)
    if upload_public is None or stored_file_public is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    upload, stored_file = service.get_stored_file_for_upload(db, upload_id=upload_public.id, stored_file_id=stored_file_public.id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    assignment = service.get_assignment(db, upload.assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde als Schadware eingestuft und gesperrt")
    if stored_file.scan_status == "error":
        raise HTTPException(422, "Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=423, detail="Datei wird noch auf Viren geprüft")
    thumbnail_path = file_service.ensure_thumbnail(db, stored_file, settings.abgabebox_storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        # Immutable per file id (see get_stored_file_thumbnail in routes/files.py) - safe to
        # cache far longer than a day.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    )


@router.patch("/submission-uploads/{upload_id}/files/{file_id}/tags", response_model=list[str])
def update_submission_file_tags(
    upload_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: StoredFileTagsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Tags leben auf `stored_file`, das die Haupt-Backend-DB-Rolle voll beschreiben darf -
    unabhaengig von abgabebox-backends eigener restricted Rolle, die diesen Endpoint nie
    aufruft (Tags werden ausschliesslich von Mandanten-Writern auf der "Dateien"-Seite
    gesetzt, nie beim Hochladen selbst)."""
    require_abgabebox_write(user)
    upload_public = public_id_service.get_by_public_id(db, SubmissionUpload, upload_id)
    stored_file_public = public_id_service.get_by_public_id(db, StoredFile, file_id)
    if upload_public is None or stored_file_public is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    upload, stored_file = service.get_stored_file_for_upload(db, upload_id=upload_public.id, stored_file_id=stored_file_public.id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    assignment = service.get_assignment(db, upload.assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return file_service.update_stored_file_tags(db, stored_file, payload.tags)


@router.get("/submission-uploads/{upload_id}/files/{file_id}/metadata", response_model=StoredFileMetadata)
def get_submission_file_metadata(
    upload_id: uuid.UUID,
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    upload_public = public_id_service.get_by_public_id(db, SubmissionUpload, upload_id)
    stored_file_public = public_id_service.get_by_public_id(db, StoredFile, file_id)
    if upload_public is None or stored_file_public is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    upload, stored_file = service.get_stored_file_for_upload(db, upload_id=upload_public.id, stored_file_id=stored_file_public.id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    assignment = service.get_assignment(db, upload.assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    metadata = file_service.get_stored_file_metadata(db, stored_file, settings.abgabebox_storage_root, assignment.tenant_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    return metadata


@router.get("/clamav/status")
def get_clamav_status(
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=5)
        version = cd.version()
        return {"status": "online", "version": version}
    except Exception:
        return {"status": "offline", "version": None}


@router.get("/submission-assignments/{assignment_id}/summary")
def get_assignment_summary(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    counts = service.repository.count_submissions_summary(db, assignment_id=assignment.id)
    total = None
    if assignment.source_type == "list" and assignment.list_definition_id:
        total = service.repository.count_list_entries(db, list_definition_id=assignment.list_definition_id)
    elif assignment.source_type == "events":
        total = len(service.list_assignment_events(db, assignment))
    elif assignment.source_type == "manual":
        total = 1
    return {
        "submitted": counts["clean"],
        "quarantine": counts["quarantine"],
        "infected": counts["infected"],
        "total": total,
    }


@router.post("/submission-assignments/{assignment_id}/rescan-pending")
def rescan_pending(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_write(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    return service.rescan_pending(db, assignment.id)


@router.get("/submission-assignments/{assignment_id}/upload-log", response_model=list[SubmissionUploadLogEntry])
def get_upload_log(
    assignment_id: uuid.UUID,
    element_ref: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)
    return service.get_upload_log(db, assignment_id=assignment.id, element_ref=element_ref)


@router.get("/submission-assignments/{assignment_id}/download-zip")
def download_all_files_zip(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_abgabebox_read(user)
    assignment = _get_assignment_or_404(db, assignment_id, user)

    elements = service.get_assignment_elements(db, assignment)

    buf = io.BytesIO()
    used_names: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for element in elements:
            if not element.files or element.upload_id is None:
                continue
            upload = public_id_service.get_by_public_id(db, SubmissionUpload, element.upload_id)
            if upload is None:
                continue
            for file in element.files:
                stored_file_row = public_id_service.get_by_public_id(db, StoredFile, file.id)
                if stored_file_row is None:
                    continue
                _, stored_file = service.get_stored_file_for_upload(
                    db, upload_id=upload.id, stored_file_id=stored_file_row.id
                )
                if stored_file is None or stored_file.scan_status != "clean":
                    continue
                if not get_object_store().exists(ABGABEBOX, stored_file.storage_path):
                    continue
                arcname = stored_file.original_name
                if arcname in used_names:
                    used_names[arcname] += 1
                    stem, _, ext = arcname.rpartition(".")
                    arcname = f"{stem}_{used_names[arcname]}.{ext}" if ext else f"{arcname}_{used_names[arcname]}"
                else:
                    used_names[arcname] = 0
                write_object_to_zip(zf, ABGABEBOX, stored_file.storage_path, arcname)

    buf.seek(0)
    slug = re.sub(r"[^a-z0-9]+", "-", (assignment.title or str(assignment_id)).lower()).strip("-")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )
