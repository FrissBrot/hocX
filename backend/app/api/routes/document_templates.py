import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.models.entities import DocumentTemplate, DocumentTemplatePart
from app.schemas.document_template import (
    DocumentTemplateCreate,
    DocumentTemplatePartCreate,
    DocumentTemplatePartRead,
    DocumentTemplatePartUpdate,
    DocumentTemplateRead,
    DocumentTemplateUpdate,
)
from app.services import public_id_service
from app.services.document_template_service import DocumentTemplateService

router = APIRouter()
service = DocumentTemplateService()


def _resolve_document_template_id(db: Session, user: CurrentUser, document_template_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, DocumentTemplate, document_template_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Document template not found")
    return internal_id


def _resolve_part_id(db: Session, user: CurrentUser, part_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, DocumentTemplatePart, part_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Document template part not found")
    return internal_id


@router.get("/document-templates", response_model=list[DocumentTemplateRead])
def list_document_templates(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return service.list_document_templates(db, tenant_id=user.current_tenant_id)


@router.post("/document-templates", response_model=DocumentTemplateRead, status_code=status.HTTP_201_CREATED)
def create_document_template(
    payload: DocumentTemplateCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return service.create_document_template(db, payload, tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Document template could not be created") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Document template files could not be written") from exc


@router.patch("/document-templates/{document_template_id}", response_model=DocumentTemplateRead)
def patch_document_template(
    document_template_id: uuid.UUID,
    payload: DocumentTemplateUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _resolve_document_template_id(db, user, document_template_id)
    try:
        updated = service.update_document_template(db, internal_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Document template could not be updated") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Document template files could not be written") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Document template not found")
    return updated


@router.delete("/document-templates/{document_template_id}", response_model=dict[str, str])
def delete_document_template(
    document_template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _resolve_document_template_id(db, user, document_template_id)
    try:
      deleted = service.delete_document_template(db, internal_id)
    except SQLAlchemyError as exc:
      db.rollback()
      raise HTTPException(status_code=400, detail="Document template could not be deleted") from exc
    if not deleted:
      raise HTTPException(status_code=404, detail="Document template not found")
    return {"message": "Document template deleted"}


@router.get("/document-template-parts", response_model=list[DocumentTemplatePartRead])
def list_document_template_parts(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return service.list_document_template_parts(db, tenant_id=user.current_tenant_id)


@router.post("/document-template-parts", response_model=DocumentTemplatePartRead, status_code=status.HTTP_201_CREATED)
async def create_document_template_part(
    code: str | None = Form(default=None),
    name: str = Form(...),
    part_type: str = Form(...),
    description: str | None = Form(default=None),
    version: int = Form(default=1),
    is_active: bool = Form(default=True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    payload = DocumentTemplatePartCreate(
        code=code,
        name=name,
        part_type=part_type,
        description=description,
        version=version,
        is_active=is_active,
    )
    try:
        return await service.create_document_template_part(db, payload, file, tenant_id=user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Document template part could not be created") from exc


@router.patch("/document-template-parts/{part_id}", response_model=DocumentTemplatePartRead)
async def patch_document_template_part(
    part_id: uuid.UUID,
    code: str | None = Form(default=None),
    name: str | None = Form(default=None),
    part_type: str | None = Form(default=None),
    description: str | None = Form(default=None),
    version: int | None = Form(default=None),
    is_active: bool | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _resolve_part_id(db, user, part_id)
    payload = DocumentTemplatePartUpdate(
        code=code,
        name=name,
        part_type=part_type,
        description=description,
        version=version,
        is_active=is_active,
    )
    try:
        updated = await service.update_document_template_part(db, internal_id, payload, file)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Document template part could not be updated") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Document template part not found")
    return updated


@router.delete("/document-template-parts/{part_id}", response_model=dict[str, str])
def delete_document_template_part(
    part_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _resolve_part_id(db, user, part_id)
    try:
        deleted = service.delete_document_template_part(db, internal_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Document template part could not be deleted") from exc
    except OSError as exc:
        # Unlike every other write route in this file, this one had no OSError handling
        # at all (audit finding, 2026-08-25) - delete_document_template_part's own file
        # unlink() plus the _refresh_templates_using_part rematerialization it triggers
        # (mkdir/rmtree/file writes) can both raise one, which would otherwise surface as
        # an unhandled 500 after the DB delete had already committed.
        raise HTTPException(status_code=400, detail="Document template part files could not be updated") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Document template part not found")
    return {"message": "Document template part deleted"}
