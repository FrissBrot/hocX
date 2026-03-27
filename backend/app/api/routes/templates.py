from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.schemas.template import (
    ElementDefinitionCreate,
    ElementDefinitionRead,
    ElementDefinitionUpdate,
    TemplateCreate,
    TemplateElementCreate,
    TemplateElementRead,
    TemplateElementUpdate,
    TemplateRead,
    TemplateUpdate,
)
from app.services.element_definition_service import ElementDefinitionService
from app.services.template_element_service import TemplateElementService
from app.services.template_service import TemplateService

router = APIRouter()
service = TemplateService()
element_definition_service = ElementDefinitionService()
template_element_service = TemplateElementService()


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(db: Session = Depends(get_db)):
    return service.list_templates(db)


@router.post("/templates", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    try:
        return service.create_template(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be created") from exc


@router.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = service.get_template(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/templates/{template_id}", response_model=TemplateRead)
def patch_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)):
    try:
        template = service.update_template(db, template_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template could not be updated") from exc
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/templates/{template_id}/elements", response_model=list[TemplateElementRead])
def list_template_elements(template_id: int, db: Session = Depends(get_db)):
    return template_element_service.list_template_elements(db, template_id)


@router.post("/templates/{template_id}/elements", response_model=TemplateElementRead, status_code=status.HTTP_201_CREATED)
def create_template_element(template_id: int, payload: TemplateElementCreate, db: Session = Depends(get_db)):
    try:
        return template_element_service.create_template_element(db, template_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template element could not be created") from exc


@router.patch("/template-elements/{template_element_id}", response_model=TemplateElementRead)
def patch_template_element(template_element_id: int, payload: TemplateElementUpdate, db: Session = Depends(get_db)):
    try:
        template_element = template_element_service.update_template_element(db, template_element_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Template element could not be updated") from exc
    if template_element is None:
        raise HTTPException(status_code=404, detail="Template element not found")
    return template_element


@router.delete("/template-elements/{template_element_id}", response_model=dict[str, str])
def delete_template_element(template_element_id: int, db: Session = Depends(get_db)):
    deleted = template_element_service.delete_template_element(db, template_element_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template element not found")
    return {"message": "Template element deleted"}


@router.get("/element-definitions", response_model=list[ElementDefinitionRead])
def list_element_definitions(db: Session = Depends(get_db)):
    return element_definition_service.list_element_definitions(db)


@router.post("/element-definitions", response_model=ElementDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_element_definition(payload: ElementDefinitionCreate, db: Session = Depends(get_db)):
    try:
        return element_definition_service.create_element_definition(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Element definition could not be created") from exc


@router.patch("/element-definitions/{element_definition_id}", response_model=ElementDefinitionRead)
def patch_element_definition(
    element_definition_id: int,
    payload: ElementDefinitionUpdate,
    db: Session = Depends(get_db),
):
    try:
        element_definition = element_definition_service.update_element_definition(db, element_definition_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Element definition could not be updated") from exc
    if element_definition is None:
        raise HTTPException(status_code=404, detail="Element definition not found")
    return element_definition
