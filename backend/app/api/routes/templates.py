import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.core.db import get_db
from app.models.entities import ElementDefinition, Template, TemplateElement
from app.schemas.template import (
    ElementDefinitionCreate,
    ElementDefinitionRead,
    ElementDefinitionUpdate,
    TemplateCreate,
    TemplateDuplicateRequest,
    TemplateElementBehaviorUpdate,
    TemplateElementCreate,
    TemplateElementRead,
    TemplateElementUpdate,
    TemplateRead,
    TemplateUpdate,
)
from app.services import public_id_service
from app.services.element_definition_service import ElementDefinitionService
from app.services.access_service import AccessService
from app.services.template_element_service import TemplateElementService
from app.services.template_service import TemplateService

router = APIRouter()
service = TemplateService()
element_definition_service = ElementDefinitionService()
template_element_service = TemplateElementService()
access_service = AccessService()


def _get_template_or_404(db: Session, template_id: uuid.UUID, user: CurrentUser) -> Template:
    template = public_id_service.get_by_public_id(db, Template, template_id, tenant_id=user.current_tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def _get_element_definition_or_404(db: Session, element_definition_id: uuid.UUID, user: CurrentUser) -> ElementDefinition:
    definition = public_id_service.get_by_public_id(db, ElementDefinition, element_definition_id, tenant_id=user.current_tenant_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Element definition not found")
    return definition


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return service.list_templates(
        db,
        tenant_id=user.current_tenant_id,
        query=q,
        status=status_filter,
        user_id=user.user_id,
        restrict_to_assigned=access_service.is_restricted_reader(db, user),
    )


@router.post("/templates", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return service.create_template(db, payload, tenant_id=user.current_tenant_id, created_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be created") from exc


@router.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    template = _get_template_or_404(db, template_id, user)
    access_service.ensure_can_read_template(db, user, template.id)
    return template


@router.patch("/templates/{template_id}", response_model=TemplateRead)
def patch_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    existing = _get_template_or_404(db, template_id, user)
    try:
        template = service.update_template(db, existing.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be updated") from exc
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/templates/{template_id}/duplicate", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def duplicate_template(
    template_id: uuid.UUID,
    payload: TemplateDuplicateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    existing = _get_template_or_404(db, template_id, user)
    try:
        duplicate = service.duplicate_template(db, existing.id, new_name=payload.name, created_by=user.user_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be duplicated") from exc
    if duplicate is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return duplicate


@router.delete("/templates/{template_id}", response_model=dict[str, str])
def delete_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    existing = _get_template_or_404(db, template_id, user)
    try:
        deleted = service.delete_template(db, existing.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deleted"}


@router.get("/templates/{template_id}/elements", response_model=list[TemplateElementRead])
def list_template_elements(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    template = _get_template_or_404(db, template_id, user)
    access_service.ensure_can_read_template(db, user, template.id)
    return template_element_service.list_template_elements(db, template.id)


@router.post("/templates/{template_id}/elements", response_model=TemplateElementRead, status_code=status.HTTP_201_CREATED)
def create_template_element(
    template_id: uuid.UUID,
    payload: TemplateElementCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    template = _get_template_or_404(db, template_id, user)
    try:
        return template_element_service.create_template_element(db, template.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template element could not be created") from exc


def _ensure_template_element_in_tenant(db: Session, user: CurrentUser, template_element_id: uuid.UUID) -> int:
    """Same tenant check create_template_element/list_template_elements above already do via
    their template_id path param - here the id in the path is the *element's* id, so we have
    to resolve its owning template ourselves before allowing a write. 404 (not 403) on
    mismatch, matching this file's existing convention of not confirming a foreign id exists.
    Returns the element's internal id for the caller to use."""
    entity = public_id_service.get_by_public_id(db, TemplateElement, template_element_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Template element not found")
    template = service.get_template(db, entity.template_id)
    if template is None or template.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Template element not found")
    return entity.id


@router.patch("/template-elements/{template_element_id}", response_model=TemplateElementRead)
def patch_template_element(
    template_element_id: uuid.UUID,
    payload: TemplateElementUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _ensure_template_element_in_tenant(db, user, template_element_id)
    try:
        template_element = template_element_service.update_template_element(db, internal_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template element could not be updated") from exc
    if template_element is None:
        raise HTTPException(status_code=404, detail="Template element not found")
    return template_element


@router.patch("/template-elements/{template_element_id}/behavior", response_model=TemplateElementRead)
def patch_template_element_behavior(
    template_element_id: uuid.UUID,
    payload: TemplateElementBehaviorUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _ensure_template_element_in_tenant(db, user, template_element_id)
    try:
        template_element = template_element_service.update_block_behavior(db, internal_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Behavior could not be updated") from exc
    if template_element is None:
        raise HTTPException(status_code=404, detail="Template element not found")
    return template_element


@router.delete("/template-elements/{template_element_id}", response_model=dict[str, str])
def delete_template_element(
    template_element_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    internal_id = _ensure_template_element_in_tenant(db, user, template_element_id)
    deleted = template_element_service.delete_template_element(db, internal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template element not found")
    return {"message": "Template element deleted"}


@router.get("/element-definitions", response_model=list[ElementDefinitionRead])
def list_element_definitions(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return element_definition_service.list_element_definitions(db, tenant_id=user.current_tenant_id)


@router.get("/element-definitions/{element_definition_id}", response_model=ElementDefinitionRead)
def get_element_definition(
    element_definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    definition = _get_element_definition_or_404(db, element_definition_id, user)
    return element_definition_service.get_element_definition(db, definition.id)


@router.post("/element-definitions", response_model=ElementDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_element_definition(
    payload: ElementDefinitionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return element_definition_service.create_element_definition(db, payload, tenant_id=user.current_tenant_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Element definition could not be created") from exc


@router.patch("/element-definitions/{element_definition_id}", response_model=ElementDefinitionRead)
def patch_element_definition(
    element_definition_id: uuid.UUID,
    payload: ElementDefinitionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    current = _get_element_definition_or_404(db, element_definition_id, user)
    try:
        element_definition = element_definition_service.update_element_definition(db, current.id, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Element definition could not be updated") from exc
    if element_definition is None:
        raise HTTPException(status_code=404, detail="Element definition not found")
    return element_definition


@router.delete("/element-definitions/{element_definition_id}", response_model=dict[str, str])
def delete_element_definition(
    element_definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    current = _get_element_definition_or_404(db, element_definition_id, user)
    try:
        deleted = element_definition_service.delete_element_definition(db, current.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Element definition could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Element definition not found")
    return {"message": "Element definition deleted"}
