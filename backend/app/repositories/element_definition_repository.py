from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ElementDefinition


class ElementDefinitionRepository:
    def list(self, db: Session) -> list[ElementDefinition]:
        return list(db.scalars(select(ElementDefinition).order_by(ElementDefinition.id.desc())))

    def get(self, db: Session, element_definition_id: int) -> ElementDefinition | None:
        return db.get(ElementDefinition, element_definition_id)

    def create(self, db: Session, entity: ElementDefinition) -> ElementDefinition:
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def update(self, db: Session, entity: ElementDefinition, values: dict) -> ElementDefinition:
        for key, value in values.items():
            setattr(entity, key, value)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity
