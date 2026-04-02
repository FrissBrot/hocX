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

    def _render_type_for_element_type(self, element_type_id: int) -> int:
        mapping = {
            1: 2,  # text -> paragraph
            2: 3,  # todo -> todo_list
            3: 4,  # image -> image
            5: 6,  # static_text -> plain_text
            6: 5,  # form -> key_value
            7: 5,  # event_list -> key_value
            8: 2,  # bullet_list -> paragraph
            9: 5,  # attendance -> key_value
            10: 6,  # session_date -> plain_text
            11: 5,  # matrix -> key_value
        }
        return mapping.get(element_type_id, 2)

    def _normalize_blocks(self, blocks: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for block in blocks:
            next_block = dict(block)
            element_type_id = int(next_block.get("element_type_id", 1))
            next_block["element_type_id"] = element_type_id
            next_block["render_type_id"] = self._render_type_for_element_type(element_type_id)
            next_block["allows_multiple_values"] = element_type_id in {2, 3}
            config = dict(next_block.get("configuration_json") or {})
            config.setdefault("title_as_subtitle", True)
            next_block["configuration_json"] = config
            normalized.append(next_block)
        return normalized

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
            allows_multiple_values=False,
            export_visible=True,
            latex_template=None,
            configuration_json={"blocks": self._normalize_blocks([block.model_dump() for block in payload.blocks])},
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
            values["configuration_json"] = {"blocks": self._normalize_blocks(values.pop("blocks"))}
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
