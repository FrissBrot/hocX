from sqlalchemy.orm import Session

from app.models import ElementDefinition
from app.repositories.element_definition_repository import ElementDefinitionRepository
from app.schemas.template import ElementDefinitionCreate, ElementDefinitionUpdate


class ElementDefinitionService:
    def __init__(self, repository: ElementDefinitionRepository | None = None) -> None:
        self.repository = repository or ElementDefinitionRepository()

    def list_element_definitions(self, db: Session):
        return self.repository.list(db)

    def get_element_definition(self, db: Session, element_definition_id: int):
        return self.repository.get(db, element_definition_id)

    def create_element_definition(self, db: Session, payload: ElementDefinitionCreate):
        entity = ElementDefinition(**payload.model_dump())
        return self.repository.create(db, entity)

    def update_element_definition(self, db: Session, element_definition_id: int, payload: ElementDefinitionUpdate):
        entity = self.repository.get(db, element_definition_id)
        if entity is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return entity
        return self.repository.update(db, entity, values)
