from sqlalchemy.orm import Session

from app.models import ElementDefinition, ListDefinition, Template, TemplateElement
from app.repositories.template_element_repository import TemplateElementRepository
from app.schemas.template import TemplateElementBehaviorUpdate, TemplateElementCreate, TemplateElementRead, TemplateElementUpdate
from app.services import public_id_service
from app.services.block_behavior import BEHAVIOR_FIELDS, resolve_block_behavior, resolve_element_wide_behavior
from app.services.block_config_ids import decode_block_config, encode_block_config


class TemplateElementService:
    def __init__(self, repository: TemplateElementRepository | None = None) -> None:
        self.repository = repository or TemplateElementRepository()

    def _read_model(self, db: Session, row) -> TemplateElementRead:
        template_element, definition = row
        config = definition.configuration_json or {}
        # Both configs are stored with internal ints embedded (linked_list_id, ...) -
        # encode to public ids for this API response, see block_config_ids.py.
        # resolve_block_behavior/resolve_element_wide_behavior only ever look at
        # block_behavior_overrides/block_overrides, never the id fields, so passing the
        # already-encoded config into them below is safe.
        template_element_config = encode_block_config(db, template_element.configuration_json)
        raw_blocks = sorted(config.get("blocks", []), key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0)))
        blocks = [
            {
                "id": block["id"],
                "template_element_id": template_element.public_id,
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
                "configuration_json": encode_block_config(db, block.get("configuration_json")),
                "created_at": template_element.created_at,
                **resolve_block_behavior(template_element_config, block),
            }
            for block in raw_blocks
        ]
        return TemplateElementRead(
            id=template_element.public_id,
            template_id=public_id_service.resolve_public_id(db, Template, template_element.template_id),
            element_definition_id=public_id_service.resolve_public_id(db, ElementDefinition, template_element.element_definition_id),
            sort_index=template_element.sort_index,
            title=definition.title,
            description=definition.description,
            configuration_json=template_element_config,
            created_at=template_element.created_at,
            blocks=blocks,
            behavior=resolve_element_wide_behavior(template_element_config, raw_blocks),
        )

    def list_template_elements(self, db: Session, template_id: int) -> list[TemplateElementRead]:
        return [self._read_model(db, row) for row in self.repository.list_for_template(db, template_id)]

    def get_template_element(self, db: Session, template_element_id: int):
        row = self.repository.get_with_definition(db, template_element_id)
        return self._read_model(db, row) if row else None

    def _referenced_list_definition_ids(self, config: dict | None) -> set[int]:
        """Collects both whole-list `linked_list_id` and any row-link `rows[].linked_list_id`
        values out of a block/element configuration_json. Mirrors the extraction logic in
        list_snapshot_service.referenced_list_definition_ids - keep both in sync if the
        list-linkage JSON shape ever changes."""
        config = config or {}
        ids: set[int] = set()
        top_level = config.get("linked_list_id")
        if top_level:
            ids.add(int(top_level))
        rows = config.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("linked_list_id"):
                    ids.add(int(row["linked_list_id"]))
        return ids

    def _validate_linked_lists(self, db: Session, config: dict | None, *, tenant_id: int) -> None:
        """Any linked_list_id referenced from a TemplateElement's configuration_json must
        point at a ListDefinition that actually exists and belongs to the same tenant as the
        template - otherwise a foreign or stale id gets stored silently and only surfaces
        much later as a crash when a protocol snapshot tries to resolve it."""
        for list_id in self._referenced_list_definition_ids(config):
            list_definition = db.get(ListDefinition, list_id)
            if list_definition is None or list_definition.tenant_id != tenant_id:
                raise ValueError(f"Linked list {list_id} not found")

    def create_template_element(self, db: Session, template_id: int, payload: TemplateElementCreate):
        existing_rows = self.repository.list_for_template(db, template_id)
        existing_sort_indexes = [template_element.sort_index for template_element, _definition in existing_rows]
        next_sort_index = payload.sort_index
        if next_sort_index in existing_sort_indexes or next_sort_index <= 0:
            next_sort_index = (max(existing_sort_indexes) if existing_sort_indexes else 0) + 10
        template = db.get(Template, template_id)
        # Route already confirmed template.tenant_id == the caller's tenant before calling
        # here; resolving element_definition_id scoped to that same tenant closes the
        # remaining gap where an admin could link a *different* tenant's ElementDefinition
        # into their own (rightfully owned) template. Same "404, no existence leak"
        # convention as the rest of this file - no distinct error for "wrong tenant" vs
        # "doesn't exist".
        element_definition_id = (
            public_id_service.resolve_internal_id(db, ElementDefinition, payload.element_definition_id, tenant_id=template.tenant_id)
            if template is not None
            else None
        )
        if element_definition_id is None:
            raise ValueError("Element definition not found")
        definition = db.get(ElementDefinition, element_definition_id)
        decoded_config = decode_block_config(db, payload.configuration_json, tenant_id=template.tenant_id)
        self._validate_linked_lists(db, decoded_config, tenant_id=template.tenant_id)
        entity = TemplateElement(
            template_id=template_id,
            element_definition_id=element_definition_id,
            sort_index=next_sort_index,
            section_name=definition.title,
            section_order=next_sort_index,
            is_required=False,
            is_visible=True,
            export_visible=True,
            configuration_json=decoded_config,
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
        if "configuration_json" in values:
            # An explicit `"configuration_json": null` in the PATCH body is otherwise
            # indistinguishable from "clear it to an empty object" and, since the DB
            # column's NOT NULL constraint turned out not to actually be enforced (schema
            # drift), silently stores a real None instead of {} - breaking every downstream
            # reader that assumes configuration_json is always a dict (audit finding,
            # 2026-08-25). Coerce to {} here, matching create_template_element's own
            # `payload.configuration_json or {}` convention, so this field is never
            # actually None in storage.
            if values["configuration_json"] is None:
                values["configuration_json"] = {}
            template = db.get(Template, entity.template_id)
            values["configuration_json"] = decode_block_config(
                db, values["configuration_json"], tenant_id=template.tenant_id if template else 0
            )
            self._validate_linked_lists(db, values["configuration_json"], tenant_id=template.tenant_id if template else None)
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
