from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventCategory, Protocol, ProtocolElement, ProtocolElementBlock, Template
from app.repositories.protocol_element_repository import (
    ProtocolElementBlockRepository,
    ProtocolElementRepository,
)
from app.schemas.protocol import (
    ProtocolElementBlockRead,
    ProtocolElementBlockUpdate,
    ProtocolElementRead,
    ProtocolElementUpdate,
)


class ProtocolElementService:
    def __init__(
        self,
        repository: ProtocolElementRepository | None = None,
        block_repository: ProtocolElementBlockRepository | None = None,
    ) -> None:
        self.repository = repository or ProtocolElementRepository()
        self.block_repository = block_repository or ProtocolElementBlockRepository()

    def list_protocol_elements(self, db: Session, protocol_id: int) -> list[ProtocolElementRead]:
        elements = self.repository.list_for_protocol(db, protocol_id)
        block_rows = self.repository.list_blocks_for_elements(db, [element.id for element in elements])
        blocks_by_element: dict[int, list[ProtocolElementBlockRead]] = {}

        for row in block_rows:
            block = row.ProtocolElementBlock
            blocks_by_element.setdefault(block.protocol_element_id, []).append(
                ProtocolElementBlockRead(
                    id=block.id,
                    protocol_element_id=block.protocol_element_id,
                    template_element_block_id=block.template_element_block_id,
                    element_definition_id=block.element_definition_id,
                    element_type_id=block.element_type_id,
                    render_type_id=block.render_type_id,
                    element_type_code=row.element_type_code,
                    render_type_code=row.render_type_code,
                    title_snapshot=block.title_snapshot,
                    display_title_snapshot=block.display_title_snapshot,
                    description_snapshot=block.description_snapshot,
                    block_title_snapshot=block.block_title_snapshot,
                    copy_from_last_protocol=bool((block.configuration_snapshot_json or {}).get("copy_from_last_protocol", False)),
                    is_editable_snapshot=block.is_editable_snapshot,
                    allows_multiple_values_snapshot=block.allows_multiple_values_snapshot,
                    sort_index=block.sort_index,
                    render_order=block.render_order,
                    is_required_snapshot=block.is_required_snapshot,
                    is_visible_snapshot=block.is_visible_snapshot,
                    export_visible_snapshot=block.export_visible_snapshot,
                    latex_template_snapshot=block.latex_template_snapshot,
                    configuration_snapshot_json=block.configuration_snapshot_json,
                    text_content=row.text_content,
                    display_compiled_text=row.display_compiled_text,
                    display_snapshot_json=row.display_snapshot_json or {},
                )
            )

        return [
            ProtocolElementRead(
                id=element.id,
                protocol_id=element.protocol_id,
                template_element_id=element.template_element_id,
                sort_index=element.sort_index,
                section_name_snapshot=element.section_name_snapshot,
                section_order_snapshot=element.section_order_snapshot,
                is_required_snapshot=element.is_required_snapshot,
                is_visible_snapshot=element.is_visible_snapshot,
                export_visible_snapshot=element.export_visible_snapshot,
                blocks=blocks_by_element.get(element.id, []),
            )
            for element in elements
        ]

    def update_protocol_element(self, db: Session, protocol_element_id: int, payload: ProtocolElementUpdate):
        protocol_element = self.repository.get(db, protocol_element_id)
        if protocol_element is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return protocol_element
        return self.repository.update(db, protocol_element, values)

    def update_protocol_element_block(self, db: Session, protocol_element_block_id: int, payload: ProtocolElementBlockUpdate):
        protocol_element_block = self.block_repository.get(db, protocol_element_block_id)
        if protocol_element_block is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return protocol_element_block
        updated = self.block_repository.update(db, protocol_element_block, values)
        self._sync_session_date_marker(db, updated)
        return updated

    def _sync_session_date_marker(self, db: Session, block: ProtocolElementBlock) -> None:
        config = block.configuration_snapshot_json or {}
        if config.get("block_kind") != "session_date":
            return

        protocol_element = db.get(ProtocolElement, block.protocol_element_id)
        if protocol_element is None:
            return
        protocol = db.get(Protocol, protocol_element.protocol_id)
        if protocol is None:
            return
        template = db.get(Template, protocol.template_id)
        if template is None:
            return

        selected_date = config.get("selected_date")
        parsed_date = date.fromisoformat(selected_date) if isinstance(selected_date, str) and selected_date else None
        title = (config.get("session_label") or "Naechste Sitzung").strip() or "Naechste Sitzung"
        tag = (config.get("session_tag") or "next_session").strip() or "next_session"

        if not parsed_date:
            template.next_event_id = None
            if protocol.event_id:
                template.last_event_id = protocol.event_id
            db.add(template)
            db.commit()
            return

        next_event = db.get(Event, template.next_event_id) if template.next_event_id else None
        if next_event is None:
            category_id = db.scalar(select(EventCategory.id).where(EventCategory.code == "group_session"))
            if category_id is None:
                category_id = db.scalar(select(EventCategory.id).where(EventCategory.code == "other"))
            next_event = Event(
                tenant_id=protocol.tenant_id,
                event_date=parsed_date,
                event_category_id=int(category_id or 1),
                tag=tag,
                title=title,
                description="Generated from session date block",
            )
            db.add(next_event)
            db.flush()
            template.next_event_id = next_event.id
        else:
            next_event.event_date = parsed_date
            next_event.tag = tag
            next_event.title = title
            db.add(next_event)

        if protocol.event_id:
            template.last_event_id = protocol.event_id

        db.add(template)
        db.commit()
