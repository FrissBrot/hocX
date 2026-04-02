from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.schemas.participant import (
    ParticipantBulkDelete,
    ParticipantCreate,
    ParticipantImportResult,
    ParticipantRead,
    ParticipantTemplateAssignmentUpdate,
    ParticipantUpdate,
    TemplateParticipantAssignmentUpdate,
)
from app.services.participant_service import ParticipantService
from app.services.access_service import AccessService
from app.services.template_service import TemplateService
from app.schemas.template import TemplateRead

router = APIRouter()
participant_service = ParticipantService()
template_service = TemplateService()
access_service = AccessService()


@router.get("/participants", response_model=list[ParticipantRead])
def list_participants(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    return participant_service.list_participants(db, tenant_id=user.current_tenant_id, active_only=active_only)


@router.post("/participants", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED)
def create_participant(
    payload: ParticipantCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return participant_service.create_participant(db, payload, tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be created") from exc


@router.patch("/participants/{participant_id}", response_model=ParticipantRead)
def patch_participant(
    participant_id: int,
    payload: ParticipantUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    participant = participant_service.get_participant(db, participant_id)
    if participant is None or participant.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Participant not found")
    try:
        updated = participant_service.update_participant(db, participant_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be updated") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return updated


@router.delete("/participants/{participant_id}", response_model=dict[str, str])
def delete_participant(
    participant_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    participant = participant_service.get_participant(db, participant_id)
    if participant is None or participant.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Participant not found")
    try:
        deleted = participant_service.delete_participant(db, participant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Participant not found")
    return {"message": "Participant deleted"}


@router.post("/participants/import-csv", response_model=ParticipantImportResult, status_code=status.HTTP_200_OK)
async def import_participants_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        content = (await file.read()).decode("utf-8-sig")
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
    require_admin(user)
    try:
        deleted_count = participant_service.delete_participants(db, payload.participant_ids, tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participants could not be deleted") from exc
    return {"deleted_count": deleted_count}


@router.get("/templates/{template_id}/participants", response_model=list[ParticipantRead])
def list_template_participants(
    template_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    template = template_service.get_template(db, template_id)
    if template is None or template.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Template not found")
    access_service.ensure_can_read_template(db, user, template_id)
    return template_service.list_template_participants(db, template_id)


@router.put("/templates/{template_id}/participants", response_model=list[ParticipantRead])
def replace_template_participants(
    template_id: int,
    payload: TemplateParticipantAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    template = template_service.get_template(db, template_id)
    if template is None or template.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Template not found")

    allowed_ids = {
        participant.id
        for participant in participant_service.list_participants(db, tenant_id=user.current_tenant_id)
    }
    if any(participant_id not in allowed_ids for participant_id in payload.participant_ids):
        raise HTTPException(status_code=400, detail="One or more participants do not belong to the current tenant")

    try:
        return template_service.replace_template_participants(db, template_id, sorted(set(payload.participant_ids)))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template participants could not be updated") from exc


@router.get("/participants/{participant_id}/templates", response_model=list[TemplateRead])
def list_participant_templates(
    participant_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    participant = participant_service.get_participant(db, participant_id)
    if participant is None or participant.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Participant not found")
    templates = participant_service.list_templates_for_participant(db, participant_id)
    if access_service._is_restricted_reader(db, user):
        return [template for template in templates if access_service.can_read_template(db, user, template.id)]
    return templates


@router.put("/participants/{participant_id}/templates", response_model=list[TemplateRead])
def replace_participant_templates(
    participant_id: int,
    payload: ParticipantTemplateAssignmentUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    participant = participant_service.get_participant(db, participant_id)
    if participant is None or participant.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Participant not found")
    tenant_template_ids = {
        template.id
        for template in template_service.list_templates(db, tenant_id=user.current_tenant_id)
    }
    if any(template_id not in tenant_template_ids for template_id in payload.template_ids):
        raise HTTPException(status_code=400, detail="One or more templates do not belong to the current tenant")
    try:
        return participant_service.replace_templates_for_participant(db, participant_id, sorted(set(payload.template_ids)))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Participant templates could not be updated") from exc
