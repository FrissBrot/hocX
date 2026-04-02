from sqlalchemy.orm import Session

from app.models import ElementDefinition, TemplateElement
from app.repositories.template_element_repository import TemplateElementRepository
from app.schemas.template import TemplateElementCreate, TemplateElementRead, TemplateElementUpdate


class TemplateElementService:
    def __init__(self, repository: TemplateElementRepository | None = None) -> None:
        self.repository = repository or TemplateElementRepository()

    def _read_model(self, row) -> TemplateElementRead:
        template_element, definition = row
        config = definition.configuration_json or {}
        blocks = [
            {
                "id": block["id"],
                "template_element_id": template_element.id,
                "element_definition_block_id": block["id"],
                "title": block["title"],
                "description": block.get("description"),
                "block_title": block.get("block_title"),
                "default_content": block.get("default_content"),
                "copy_from_last_protocol": block.get("copy_from_last_protocol", False),
                "element_type_id": block["element_type_id"],
                "render_type_id": block["render_type_id"],
                "is_editable": block.get("is_editable", True),
                "allows_multiple_values": block.get("allows_multiple_values", False),
                "export_visible": block.get("export_visible", True),
                "is_visible": block.get("is_visible", True),
                "sort_index": block["sort_index"],
                "render_order": block.get("render_order"),
                "latex_template": block.get("latex_template"),
                "configuration_json": block.get("configuration_json", {}),
                "created_at": template_element.created_at,
            }
            for block in sorted(config.get("blocks", []), key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0)))
        ]
        return TemplateElementRead(
            id=template_element.id,
            template_id=template_element.template_id,
            element_definition_id=template_element.element_definition_id,
            sort_index=template_element.sort_index,
            title=definition.title,
            description=definition.description,
            configuration_json=template_element.configuration_json or {},
            created_at=template_element.created_at,
            blocks=blocks,
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
