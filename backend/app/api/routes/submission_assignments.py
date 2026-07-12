from __future__ import annotations

import io
import re
import zipfile

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentRead,
    SubmissionAssignmentUpdate,
    SubmissionElementRead,
    SubmissionUploadLogEntry,
)
from app.services.file_service import _safe_storage_path
from app.services.submission_service import SubmissionService

router = APIRouter()
service = SubmissionService()


@router.get("/submission-assignments", response_model=list[SubmissionAssignmentRead])
def list_assignments(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    return service.list_assignments(db, tenant_id=user.current_tenant_id)


@router.post("/submission-assignments", response_model=SubmissionAssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: SubmissionAssignmentCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        return service.create_assignment(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Abgabe konnte nicht erstellt werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.patch("/submission-assignments/{assignment_id}", response_model=SubmissionAssignmentRead)
def patch_assignment(
    assignment_id: int,
    payload: SubmissionAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_assignment(db, assignment_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    try:
        updated = service.update_assignment(db, assignment_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Abgabe konnte nicht aktualisiert werden"
        raise HTTPException(status_code=400, detail=detail) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return updated


@router.delete("/submission-assignments/{assignment_id}", response_model=dict[str, str])
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_assignment(db, assignment_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    try:
        deleted = service.delete_assignment(db, assignment_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Abgabe konnte nicht geloescht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return {"message": "Abgabe geloescht"}


@router.get("/submission-assignments/{assignment_id}/elements", response_model=list[SubmissionElementRead])
def list_elements(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return service.get_assignment_elements(db, assignment)


@router.post("/submission-assignments/{assignment_id}/elements/{element_ref}/reopen", response_model=SubmissionElementRead)
def reopen_element(
    assignment_id: int,
    element_ref: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    try:
        return service.reopen_element(db, assignment, element_ref)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Element konnte nicht wieder aufgeschaltet werden"
        raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/submission-uploads/{upload_id}/files/{file_id}/content")
def get_submission_file_content(
    upload_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    upload, stored_file = service.get_stored_file_for_upload(db, upload_id=upload_id, stored_file_id=file_id)
    if upload is None or stored_file is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    assignment = service.get_assignment(db, upload.assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=423, detail="Datei wird noch auf Viren geprüft")
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde als Schadware eingestuft und gesperrt")
    file_path = _safe_storage_path(settings.abgabebox_storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Datei fehlt im Dateisystem")
    mime = stored_file.mime_type or "application/octet-stream"
    is_pdf = mime.lower() == "application/pdf" or stored_file.original_name.lower().endswith(".pdf")
    disposition = "inline" if is_pdf else "attachment"
    return FileResponse(
        path=file_path,
        media_type=mime,
        headers={"Content-Disposition": f'{disposition}; filename="{stored_file.original_name}"'},
    )


@router.get("/clamav/status")
def get_clamav_status(
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=5)
        version = cd.version()
        return {"status": "online", "version": version}
    except Exception:
        return {"status": "offline", "version": None}


@router.get("/submission-assignments/{assignment_id}/summary")
def get_assignment_summary(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    counts = service.repository.count_submissions_summary(db, assignment_id=assignment_id)
    total = None
    if assignment.source_type == "list" and assignment.list_definition_id:
        total = service.repository.count_list_entries(db, list_definition_id=assignment.list_definition_id)
    clean = max(0, counts["submitted"] - counts["quarantine"] - counts["infected"])
    return {
        "submitted": clean,
        "quarantine": counts["quarantine"],
        "infected": counts["infected"],
        "total": total,
    }


@router.post("/submission-assignments/{assignment_id}/rescan-pending")
def rescan_pending(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return service.rescan_pending(db, assignment_id)


@router.get("/submission-assignments/{assignment_id}/upload-log", response_model=list[SubmissionUploadLogEntry])
def get_upload_log(
    assignment_id: int,
    element_ref: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    return service.get_upload_log(db, assignment_id=assignment_id, element_ref=element_ref)


@router.post("/submission-assignments/{assignment_id}/sync-todos")
def sync_todos(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
    try:
        result = service.sync_submission_todos(db, assignment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/submission-assignments/{assignment_id}/download-zip")
def download_all_files_zip(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    assignment = service.get_assignment(db, assignment_id)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")

    elements = service.get_assignment_elements(db, assignment)

    buf = io.BytesIO()
    used_names: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for element in elements:
            if not element.files or element.upload_id is None:
                continue
            for file in element.files:
                _, stored_file = service.get_stored_file_for_upload(
                    db, upload_id=element.upload_id, stored_file_id=file.id
                )
                if stored_file is None or stored_file.scan_status != "clean":
                    continue
                file_path = _safe_storage_path(settings.abgabebox_storage_root, stored_file.storage_path)
                if not file_path.exists():
                    continue
                arcname = stored_file.original_name
                if arcname in used_names:
                    used_names[arcname] += 1
                    stem, _, ext = arcname.rpartition(".")
                    arcname = f"{stem}_{used_names[arcname]}.{ext}" if ext else f"{arcname}_{used_names[arcname]}"
                else:
                    used_names[arcname] = 0
                zf.write(file_path, arcname=arcname)

    buf.seek(0)
    slug = re.sub(r"[^a-z0-9]+", "-", (assignment.title or str(assignment_id)).lower()).strip("-")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )
