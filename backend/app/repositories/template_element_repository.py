from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ElementDefinition, TemplateElement


class TemplateElementRepository:
    def list_for_template(self, db: Session, template_id: int):
        query = (
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template_id)
            .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, template_element_id: int) -> TemplateElement | None:
        return db.get(TemplateElement, template_element_id)

    def get_with_definition(self, db: Session, template_element_id: int):
        query = (
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.id == template_element_id)
        )
        return db.execute(query).first()

    def create(self, db: Session, entity: TemplateElement) -> TemplateElement:
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def update(self, db: Session, entity: TemplateElement, values: dict) -> TemplateElement:
        for key, value in values.items():
            setattr(entity, key, value)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def delete(self, db: Session, entity: TemplateElement) -> None:
        db.delete(entity)
        db.commit()
