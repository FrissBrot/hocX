import uuid
from datetime import date

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader, require_writer
from app.models.entities import Participant, Template
from app.schemas.participant import (
    ParticipantBulkDelete,
    ParticipantCreate,
    ParticipantImportResult,
    ParticipantRead,
    ParticipantTemplateAssignmentUpdate,
    TemplateParticipantAssignment,
    TemplateParticipantAssignmentRead,
    ParticipantUpdate,
    TemplateParticipantAssignmentUpdate,
)
from app.services import public_id_service
from app.services.participant_service import ParticipantService
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.template_service import TemplateService
from app.schemas.template import TemplateRead

router = APIRouter()
participant_service = ParticipantService()
template_service = TemplateService()
access_service = AccessService()
audit = AuditService()


def _get_participant_or_404(db: Session, participant_id: uuid.UUID, user: CurrentUser) -> Participant:
    participant = public_id_service.get_by_public_id(db, Participant, participant_id, tenant_id=user.current_tenant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return participant

# Participant CSV imports are small by nature (one row per person); unlike word_import.py's
# uploads there was no limit at all here before this fix - an arbitrarily large "CSV" body
# was read fully into memory (audit finding, 2026-08-25).
MAX_PARTICIPANT_CSV_BYTES = 5 * 1024 * 1024  # 5 MB


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes | None:
    """Mirrors word_import.py's helper of the same name - rejects an oversized upload using
    Starlette's already-known `.size` before buffering the whole thing into memory just to
    measure it. Returns None if too large."""
    if file.size is not None and file.size > max_bytes:
        return None
    content = await file.read()
    if len(content) > max_bytes:
        return None
    return content


def _normalized_template_participant_assignments(
    db: Session, payload: TemplateParticipantAssignmentUpdate, *, tenant_id: int
) -> list[tuple[int, bool]]:
    raw_assignments = payload.participants or [
        TemplateParticipantAssignment(participant_id=participant_id)
        for participant_id in payload.participant_ids
    ]
    participant_public_ids = [assignment.participant_id for assignment in raw_assignments]
    id_map = public_id_service.resolve_internal_ids(db, Participant, participant_public_ids, tenant_id=tenant_id)
    assignments_by_participant_id: dict[int, bool] = {}
    for assignment in raw_assignments:
        internal_id = id_map.get(assignment.participant_id)
        if internal_id is None:
            raise HTTPException(status_code=400, detail="One or more participants do not belong to the current tenant")
        assignments_by_participant_id[internal_id] = bool(assignment.exclude_from_attendance)
    return sorted(assignments_by_participant_id.items())


@router.get("/participants", response_model=list[ParticipantRead])
def list_participants(
    active_only: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    # Ceiling raised from 500 to 2000 (audit finding, 2026-08-25) - the templates/{id} and
    # elements admin pages fetch the full participant list for their picker UI with a
    # hardcoded limit=500 and no truncation warning, so a tenant with more than 500
    # participants silently lost entries from those pickers with zero indication. 2000
    # covers realistic association sizes; a tenant that still exceeds it would need actual
    # pagination in those picker components, not just a higher number here.
    limit: int = Query(default=100, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    return participant_service.list_participants(db, tenant_id=user.current_tenant_id, active_only=active_only, skip=skip, limit=limit)


@router.post("/participants", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED)
def create_participant(
    payload: ParticipantCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        return participant_service.create_participant(db, payload, tenant_id=user.current_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be created") from exc


@router.patch("/participants/{participant_id}", response_model=ParticipantRead)
def patch_participant(
    participant_id: uuid.UUID,
    payload: ParticipantUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    participant = _get_participant_or_404(db, participant_id, user)
    try:
        updated = participant_service.update_participant(db, participant.id, payload, tenant_id=user.current_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be updated") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return updated


@router.delete("/participants/{participant_id}", response_model=dict[str, str])
def delete_participant(
    participant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    participant = _get_participant_or_404(db, participant_id, user)
    try:
        deleted = participant_service.delete_participant(db, participant.id, tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Participant not found")
    # Audit S10, 2026-08-16: this route had no audit trail at all, unlike finance.py/
    # fines.py/users.py/protocols.py/todos.py.
    audit.log(db, action="participant.deleted", actor=user, entity_type="participant", entity_id=participant.id)
    return {"message": "Participant deleted"}


@router.post("/participants/import-csv", response_model=ParticipantImportResult, status_code=status.HTTP_200_OK)
async def import_participants_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    raw_bytes = await _read_upload_within_limit(file, MAX_PARTICIPANT_CSV_BYTES)
    if raw_bytes is None:
        raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_PARTICIPANT_CSV_BYTES // 1024 // 1024} MB")
    try:
        content = raw_bytes.decode("utf-8-sig")
        return participant_service.import_csv(db, content, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, UnicodeDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="CSV import failed") from exc


@router.delete("/participants", response_model=dict[str, int])
def bulk_delete_participants(
    payload: ParticipantBulkDelete,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    id_map = public_id_service.resolve_internal_ids(db, Participant, payload.participant_ids, tenant_id=user.current_tenant_id)
    try:
        deleted_count = participant_service.delete_participants(db, list(id_map.values()), tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participants could not be deleted") from exc
    audit.log(
        db, action="participant.bulk_deleted", actor=user, entity_type="participant",
        details={"participant_ids": [str(i) for i in payload.participant_ids], "deleted_count": deleted_count},
    )
    return {"deleted_count": deleted_count}


@router.get("/templates/{template_id}/participants", response_model=list[TemplateParticipantAssignmentRead])
def list_template_participants(
    template_id: uuid.UUID,
    as_of: date | None = Query(default=None, description="Only include participants who were members on this date (joined_at/left_at)"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Was require_reader - inconsistent with GET /participants (require_writer) even
    # though this returns the same (or more) participant data (audit finding, 2026-08-25):
    # a reader/Kassier role could read full participant details here despite being denied
    # by the base list endpoint.
    require_writer(user)
    template = public_id_service.get_by_public_id(db, Template, template_id, tenant_id=user.current_tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    access_service.ensure_can_read_template(db, user, template.id)
    return template_service.list_template_participants(db, template.id, as_of=as_of)


@router.put("/templates/{template_id}/participants", response_model=list[TemplateParticipantAssignmentRead])
def replace_template_participants(
    template_id: uuid.UUID,
    payload: TemplateParticipantAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    template = public_id_service.get_by_public_id(db, Template, template_id, tenant_id=user.current_tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Raises 400 itself if a participant_id doesn't resolve within this tenant.
    assignments = _normalized_template_participant_assignments(db, payload, tenant_id=user.current_tenant_id)

    try:
        return template_service.replace_template_participants(db, template.id, assignments)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template participants could not be updated") from exc


@router.get("/participants/{participant_id}/templates", response_model=list[TemplateRead])
def list_participant_templates(
    participant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Deliberately require_reader, not require_writer (audit H6, 2026-08-12) - the
    # restricted-reader scoping below (a participant-linked reader only ever sees their
    # own template assignments, an unrestricted reader sees the full tenant list) is the
    # point of this endpoint; gating it behind require_writer would make it unreachable
    # for the reader accounts it exists for. See test_audit_2026_08_12_high_fixes_B.py.
    require_reader(user)
    participant = _get_participant_or_404(db, participant_id, user)
    templates = participant_service.list_templates_for_participant(db, participant.id)
    if access_service.is_restricted_reader(db, user):
        return [template for template in templates if access_service.can_read_template(db, user, template.id)]
    return templates


@router.put("/participants/{participant_id}/templates", response_model=list[TemplateRead])
def replace_participant_templates(
    participant_id: uuid.UUID,
    payload: ParticipantTemplateAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    participant = _get_participant_or_404(db, participant_id, user)
    template_id_map = public_id_service.resolve_internal_ids(db, Template, payload.template_ids, tenant_id=user.current_tenant_id)
    if len(template_id_map) != len(set(payload.template_ids)):
        raise HTTPException(status_code=400, detail="One or more templates do not belong to the current tenant")
    try:
        return participant_service.replace_templates_for_participant(db, participant.id, sorted(set(template_id_map.values())))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant templates could not be updated") from exc
