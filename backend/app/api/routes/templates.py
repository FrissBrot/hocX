from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.template import TemplateCreate, TemplateRead
from app.services.template_service import TemplateService

router = APIRouter()
service = TemplateService()


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(db: Session = Depends(get_db)):
    return service.list_templates(db)


@router.post("/templates", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    return service.create_template(db, payload)


@router.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = service.get_template(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/templates/{template_id}", response_model=dict[str, str])
def patch_template(template_id: int):
    return {"message": f"PATCH /templates/{template_id} scaffolded"}


@router.get("/templates/{template_id}/elements", response_model=list[dict])
def list_template_elements(template_id: int):
    return [{"template_id": template_id, "message": "Template elements endpoint scaffolded"}]


@router.post("/templates/{template_id}/elements", response_model=dict[str, str])
def create_template_element(template_id: int):
    return {"message": f"POST /templates/{template_id}/elements scaffolded"}


@router.patch("/template-elements/{template_element_id}", response_model=dict[str, str])
def patch_template_element(template_element_id: int):
    return {"message": f"PATCH /template-elements/{template_element_id} scaffolded"}


@router.delete("/template-elements/{template_element_id}", response_model=dict[str, str])
def delete_template_element(template_element_id: int):
    return {"message": f"DELETE /template-elements/{template_element_id} scaffolded"}


@router.get("/element-definitions", response_model=list[dict])
def list_element_definitions():
    return []


@router.post("/element-definitions", response_model=dict[str, str])
def create_element_definition():
    return {"message": "POST /element-definitions scaffolded"}


@router.patch("/element-definitions/{element_definition_id}", response_model=dict[str, str])
def patch_element_definition(element_definition_id: int):
    return {"message": f"PATCH /element-definitions/{element_definition_id} scaffolded"}

