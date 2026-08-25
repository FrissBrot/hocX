from sqlalchemy.orm import Session

from app.models import ElementDefinition, Event, ListDefinition, Participant
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
            4: 6,  # display -> plain_text (ProtocolDisplaySnapshot.compiled_text is plain rendered text, same as static_text)
            5: 6,  # static_text -> plain_text
            6: 5,  # form -> key_value
            7: 5,  # event_list -> key_value
            8: 2,  # bullet_list -> paragraph
            9: 5,  # attendance -> key_value
            10: 6,  # session_date -> plain_text
            11: 5,  # matrix -> key_value
        }
        return mapping.get(element_type_id, 2)

    def _referenced_list_definition_ids(self, config: dict | None) -> set[int]:
        """Collects both whole-list `linked_list_id` and any row-link `rows[].linked_list_id`
        values out of a single block's configuration_json. Mirrors
        TemplateElementService._referenced_list_definition_ids - keep both in sync if the
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

    def _referenced_auto_source_list_ids(self, config: dict | None) -> set[int]:
        """Matrix-Automodus: a block's configuration_json can carry auto_source.list_id (or
        the legacy matrix_column_source_list_id) instead of linked_list_id - the id that
        drives the "auto" column generation in ProtocolService.create_from_template."""
        config = config or {}
        ids: set[int] = set()
        auto_source = config.get("auto_source")
        old_list_id = config.get("matrix_column_source_list_id")
        list_id = (auto_source or {}).get("list_id") if isinstance(auto_source, dict) else None
        for candidate in (list_id, old_list_id):
            if candidate:
                ids.add(int(candidate))
        return ids

    def _referenced_participant_and_event_ids(self, config: dict | None) -> tuple[set[int], set[int]]:
        """template_participant_id/template_participant_ids/template_event_id are embedded
        per-row values (matrix/form rows) baked directly into every protocol created from
        this element definition, via ProtocolService.create_from_template - without a tenant
        check here, a definition could permanently embed another tenant's participant/event
        data into every protocol using it."""
        config = config or {}
        participant_ids: set[int] = set()
        event_ids: set[int] = set()
        rows = config.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get("template_participant_id"):
                    participant_ids.add(int(row["template_participant_id"]))
                for pid in row.get("template_participant_ids") or []:
                    if pid:
                        participant_ids.add(int(pid))
                if row.get("template_event_id"):
                    event_ids.add(int(row["template_event_id"]))
        return participant_ids, event_ids

    def _validate_linked_lists(self, db: Session, blocks: list[dict], *, tenant_id: int) -> None:
        """Every linked_list_id/auto_source.list_id referenced from any of this element
        definition's blocks must point at a ListDefinition belonging to the same tenant -
        otherwise a matrix/list block built from this element definition would spread a
        foreign tenant's list content (column titles, row contents, potentially participant
        data) into every protocol that uses it (audit D8, 2026-08-16; matrix-automode gap
        closed 2026-08-25). Mirrors TemplateElementService._validate_linked_lists, which
        already closes the equivalent gap for template-element-level configuration. Also
        validates embedded template_participant_id(s)/template_event_id row values for the
        same reason - see _referenced_participant_and_event_ids."""
        referenced_list_ids: set[int] = set()
        referenced_participant_ids: set[int] = set()
        referenced_event_ids: set[int] = set()
        for block in blocks:
            config = block.get("configuration_json")
            referenced_list_ids |= self._referenced_list_definition_ids(config)
            referenced_list_ids |= self._referenced_auto_source_list_ids(config)
            participant_ids, event_ids = self._referenced_participant_and_event_ids(config)
            referenced_participant_ids |= participant_ids
            referenced_event_ids |= event_ids
        for list_id in referenced_list_ids:
            list_definition = db.get(ListDefinition, list_id)
            if list_definition is None or list_definition.tenant_id != tenant_id:
                raise ValueError(f"Linked list {list_id} not found")
        for participant_id in referenced_participant_ids:
            participant = db.get(Participant, participant_id)
            if participant is None or participant.tenant_id != tenant_id:
                raise ValueError(f"Participant {participant_id} not found")
        for event_id in referenced_event_ids:
            event = db.get(Event, event_id)
            if event is None or event.tenant_id != tenant_id:
                raise ValueError(f"Event {event_id} not found")

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
        normalized_blocks = self._normalize_blocks([block.model_dump() for block in payload.blocks])
        self._validate_linked_lists(db, normalized_blocks, tenant_id=tenant_id)
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
            configuration_json={"blocks": normalized_blocks},
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
            normalized_blocks = self._normalize_blocks(values.pop("blocks"))
            self._validate_linked_lists(db, normalized_blocks, tenant_id=entity.tenant_id)
            values["configuration_json"] = {"blocks": normalized_blocks}
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
