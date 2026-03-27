from sqlalchemy.orm import Session

from app.models import ElementDefinition
from app.repositories.element_definition_repository import ElementDefinitionRepository
from app.schemas.template import (
    ElementDefinitionCreate,
    ElementDefinitionRead,
    ElementDefinitionUpdate,
)


class ElementDefinitionService:
    def __init__(self, repository: ElementDefinitionRepository | None = None) -> None:
        self.repository = repository or ElementDefinitionRepository()

    def _read_model(self, entity: ElementDefinition) -> ElementDefinitionRead:
        config = entity.configuration_json or {}
        return ElementDefinitionRead(
            id=entity.id,
            tenant_id=entity.tenant_id,
            title=entity.title,
            description=entity.description,
            is_active=entity.is_active,
            blocks=config.get("blocks", []),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def list_element_definitions(self, db: Session, *, tenant_id: int):
        return [self._read_model(entity) for entity in self.repository.list(db, tenant_id=tenant_id)]

    def get_element_definition(self, db: Session, element_definition_id: int):
        entity = self.repository.get(db, element_definition_id)
        return self._read_model(entity) if entity else None

    def create_element_definition(self, db: Session, payload: ElementDefinitionCreate, *, tenant_id: int):
        entity = ElementDefinition(
            tenant_id=tenant_id,
            element_type_id=1,
            render_type_id=2,
            title=payload.title,
            display_title=payload.title,
            description=payload.description,
            is_editable=False,
            allows_multiple_values=True,
            export_visible=True,
            latex_template=None,
            configuration_json={"blocks": [block.model_dump() for block in payload.blocks]},
            is_active=payload.is_active,
        )
        created = self.repository.create(db, entity)
        return self._read_model(created)

    def update_element_definition(self, db: Session, element_definition_id: int, payload: ElementDefinitionUpdate):
        entity = self.repository.get(db, element_definition_id)
        if entity is None:
            return None

        values = payload.model_dump(exclude_unset=True)
        if "blocks" in values:
            values["configuration_json"] = {"blocks": values.pop("blocks")}
        if "title" in values:
            values["display_title"] = values["title"]
        if not values:
            return self._read_model(entity)
        updated = self.repository.update(db, entity, values)
        return self._read_model(updated)

    def delete_element_definition(self, db: Session, element_definition_id: int) -> bool:
        entity = self.repository.get(db, element_definition_id)
        if entity is None:
            return False
        self.repository.delete(db, entity)
        return True
