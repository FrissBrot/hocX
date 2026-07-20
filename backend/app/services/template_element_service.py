from sqlalchemy.orm import Session

from app.models import ElementDefinition, TemplateElement
from app.repositories.template_element_repository import TemplateElementRepository
from app.schemas.template import TemplateElementBehaviorUpdate, TemplateElementCreate, TemplateElementRead, TemplateElementUpdate
from app.services.block_behavior import BEHAVIOR_FIELDS, resolve_block_behavior, resolve_element_wide_behavior


class TemplateElementService:
    def __init__(self, repository: TemplateElementRepository | None = None) -> None:
        self.repository = repository or TemplateElementRepository()

    def _read_model(self, row) -> TemplateElementRead:
        template_element, definition = row
        config = definition.configuration_json or {}
        template_element_config = template_element.configuration_json or {}
        raw_blocks = sorted(config.get("blocks", []), key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0)))
        blocks = [
            {
                "id": block["id"],
                "template_element_id": template_element.id,
                "element_definition_block_id": block["id"],
                "title": block["title"],
                "description": block.get("description"),
                "block_title": block.get("block_title"),
                "default_content": block.get("default_content"),
                "element_type_id": block["element_type_id"],
                "render_type_id": block["render_type_id"],
                "allows_multiple_values": block.get("allows_multiple_values", False),
                "sort_index": block["sort_index"],
                "render_order": block.get("render_order"),
                "latex_template": block.get("latex_template"),
                "configuration_json": block.get("configuration_json", {}),
                "created_at": template_element.created_at,
                **resolve_block_behavior(template_element_config, block),
            }
            for block in raw_blocks
        ]
        return TemplateElementRead(
            id=template_element.id,
            template_id=template_element.template_id,
            element_definition_id=template_element.element_definition_id,
            sort_index=template_element.sort_index,
            title=definition.title,
            description=definition.description,
            configuration_json=template_element_config,
            created_at=template_element.created_at,
            blocks=blocks,
            behavior=resolve_element_wide_behavior(template_element_config, raw_blocks),
        )

    def list_template_elements(self, db: Session, template_id: int) -> list[TemplateElementRead]:
        return [self._read_model(row) for row in self.repository.list_for_template(db, template_id)]

    def get_template_element(self, db: Session, template_element_id: int):
        row = self.repository.get_with_definition(db, template_element_id)
        return self._read_model(row) if row else None

    def create_template_element(self, db: Session, template_id: int, payload: TemplateElementCreate):
        existing_rows = self.repository.list_for_template(db, template_id)
        existing_sort_indexes = [template_element.sort_index for template_element, _definition in existing_rows]
        next_sort_index = payload.sort_index
        if next_sort_index in existing_sort_indexes or next_sort_index <= 0:
            next_sort_index = (max(existing_sort_indexes) if existing_sort_indexes else 0) + 10
        definition = db.get(ElementDefinition, payload.element_definition_id)
        if definition is None:
            raise ValueError("Element definition not found")
        entity = TemplateElement(
            template_id=template_id,
            element_definition_id=payload.element_definition_id,
            sort_index=next_sort_index,
            section_name=definition.title,
            section_order=next_sort_index,
            is_required=False,
            is_visible=True,
            export_visible=True,
            configuration_json=payload.configuration_json or {},
        )
        created = self.repository.create(db, entity)
        return self.get_template_element(db, created.id)

    def update_template_element(self, db: Session, template_element_id: int, payload: TemplateElementUpdate):
        entity = self.repository.get(db, template_element_id)
        if entity is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return self.get_template_element(db, template_element_id)
        updated = self.repository.update(db, entity, values)
        return self.get_template_element(db, updated.id)

    def delete_template_element(self, db: Session, template_element_id: int) -> bool:
        entity = self.repository.get(db, template_element_id)
        if entity is None:
            return False
        self.repository.delete(db, entity)
        return True

    def update_block_behavior(self, db: Session, template_element_id: int, payload: TemplateElementBehaviorUpdate):
        entity = self.repository.get(db, template_element_id)
        if entity is None:
            return None
        values = {
            field: value
            for field, value in payload.model_dump(exclude={"scope", "block_id"}, exclude_unset=True).items()
            if field in BEHAVIOR_FIELDS
        }
        if not values:
            return self.get_template_element(db, template_element_id)

        config = dict(entity.configuration_json or {})
        if payload.scope == "element":
            overrides = dict(config.get("block_behavior_overrides") or {})
            overrides.update(values)
            config["block_behavior_overrides"] = overrides
        else:
            if payload.block_id is None:
                raise ValueError("block_id is required when scope is 'block'")
            per_block = dict(config.get("block_overrides") or {})
            block_entry = dict(per_block.get(str(payload.block_id), {}))
            block_entry.update(values)
            per_block[str(payload.block_id)] = block_entry
            config["block_overrides"] = per_block

        self.repository.update(db, entity, {"configuration_json": config})
        return self.get_template_element(db, template_element_id)
