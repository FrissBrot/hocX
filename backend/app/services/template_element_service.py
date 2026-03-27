from sqlalchemy.orm import Session

from app.models import TemplateElement
from app.repositories.template_element_repository import TemplateElementRepository
from app.schemas.template import TemplateElementCreate, TemplateElementUpdate


class TemplateElementService:
    def __init__(self, repository: TemplateElementRepository | None = None) -> None:
        self.repository = repository or TemplateElementRepository()

    def list_template_elements(self, db: Session, template_id: int):
        return self.repository.list_for_template(db, template_id)

    def get_template_element(self, db: Session, template_element_id: int):
        return self.repository.get(db, template_element_id)

    def create_template_element(self, db: Session, template_id: int, payload: TemplateElementCreate):
        entity = TemplateElement(template_id=template_id, **payload.model_dump())
        return self.repository.create(db, entity)

    def update_template_element(self, db: Session, template_element_id: int, payload: TemplateElementUpdate):
        entity = self.repository.get(db, template_element_id)
        if entity is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return entity
        return self.repository.update(db, entity, values)

    def delete_template_element(self, db: Session, template_element_id: int) -> bool:
        entity = self.repository.get(db, template_element_id)
        if entity is None:
            return False
        self.repository.delete(db, entity)
        return True
