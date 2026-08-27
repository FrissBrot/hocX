import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ElementDefinition
from app.services import public_id_service


class ElementDefinitionRepository:
    def list(self, db: Session, *, tenant_id: int) -> list[ElementDefinition]:
        statement = select(ElementDefinition).where(ElementDefinition.tenant_id == tenant_id).order_by(ElementDefinition.id.desc())
        return list(db.scalars(statement))

    def get(self, db: Session, element_definition_id: int) -> ElementDefinition | None:
        return db.get(ElementDefinition, element_definition_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> ElementDefinition | None:
        return public_id_service.get_by_public_id(db, ElementDefinition, public_id, tenant_id=tenant_id)

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

    def delete(self, db: Session, entity: ElementDefinition) -> None:
        db.delete(entity)
        db.commit()
