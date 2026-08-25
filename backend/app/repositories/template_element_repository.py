from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ElementDefinition, TemplateElement


class TemplateElementRepository:
    def list_for_template(self, db: Session, template_id: int):
        # LEFT JOIN, not INNER (audit finding, 2026-08-25): element_definition_id is
        # currently protected by ON DELETE RESTRICT, so an inner join can't drop a row
        # today - but that's an incidental property of the current schema, not something
        # this query itself enforces. A future migration loosening that constraint would
        # otherwise make a TemplateElement whose definition was deleted vanish from this
        # list with no error, instead of surfacing with ElementDefinition=None.
        query = (
            select(TemplateElement, ElementDefinition)
            .outerjoin(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template_id)
            .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, template_element_id: int) -> TemplateElement | None:
        return db.get(TemplateElement, template_element_id)

    def get_with_definition(self, db: Session, template_element_id: int):
        # See list_for_template's identical comment above.
        query = (
            select(TemplateElement, ElementDefinition)
            .outerjoin(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
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
