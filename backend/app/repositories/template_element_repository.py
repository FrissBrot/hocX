from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TemplateElement


class TemplateElementRepository:
    def list_for_template(self, db: Session, template_id: int) -> list[TemplateElement]:
        return list(
            db.scalars(
                select(TemplateElement)
                .where(TemplateElement.template_id == template_id)
                .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
            )
        )

    def get(self, db: Session, template_element_id: int) -> TemplateElement | None:
        return db.get(TemplateElement, template_element_id)

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
