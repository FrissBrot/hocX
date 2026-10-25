from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.locking import lock_row

from app.models import ElementDefinition, Event, EventCategory, Protocol, ProtocolElement, ProtocolElementBlock, Template, TemplateElement, TemplateElementBlock
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
from app.services.snapshot_reference_ids import snapshot_reference_ids, translate_attendance_entries, translate_participant_refs
from app.services import public_id_service
from app.services.element_config import parse_session_time
from app.services.fine_tariff_service import tariff_block_values
from app.services.responsible_label_service import resolve_display_section_titles_batch


class BlockConfigConflict(Exception):
    """Blockkonfiguration wurde seit dem Stand des Clients geändert (409 config_conflict)."""

    def __init__(self, block: ProtocolElementBlock) -> None:
        super().__init__("config_conflict")
        self.block = block


class ProtocolElementService:
    def __init__(
        self,
        repository: ProtocolElementRepository | None = None,
        block_repository: ProtocolElementBlockRepository | None = None,
    ) -> None:
        self.repository = repository or ProtocolElementRepository()
        self.block_repository = block_repository or ProtocolElementBlockRepository()

    def list_protocol_elements(self, db: Session, protocol_id: int) -> list[ProtocolElementRead]:
        from app.services.protocol_service import ProtocolService

        ProtocolService().refresh_membership_blocks(db, protocol_id)
        protocol_row = db.execute(
            select(Protocol.status, Protocol.tenant_id, Protocol.template_id).where(Protocol.id == protocol_id)
        ).one_or_none()
        protocol_status = protocol_row.status if protocol_row else ""
        protocol_tenant_id = protocol_row.tenant_id if protocol_row else None
        protocol_template_id = protocol_row.template_id if protocol_row else None
        element_rows = self.repository.list_for_protocol(db, protocol_id)
        elements = [row[0] for row in element_rows]
        show_when_empty_by_id = {row[0].id: row[1] for row in element_rows}
        block_rows = self.repository.list_blocks_for_elements(db, [element.id for element in elements])
        blocks_by_element: dict[int, list[ProtocolElementBlockRead]] = {}
        section_titles_by_element_id = resolve_display_section_titles_batch(db, elements, protocol_status or "", protocol_tenant_id)

        fine_values: dict | None = None
        for row in block_rows:
            block = row.ProtocolElementBlock
            config = dict(block.configuration_snapshot_json or {})
            # Bussen: der Block trägt nur fines_enabled, Konto und Beträge kommen aus dem Tarif
            # der Vorlage bzw. des Mandanten (fine_tariff_service). attendance-fines.ts liest
            # diese Schlüssel.
            if row.element_type_code == "attendance":
                if config.get("fines_enabled") and protocol_tenant_id is not None:
                    if fine_values is None:
                        fine_values = tariff_block_values(db, protocol_tenant_id, protocol_template_id)
                    config.update(fine_values)
                else:
                    config.update({"fine_account_id": None, "fine_amount_late": 0, "fine_amount_absent": 0})
            if row.element_type_code == "attendance":
                config = translate_attendance_entries(db, config)
            if protocol_tenant_id is not None:
                config = translate_participant_refs(db, config, protocol_tenant_id)
            blocks_by_element.setdefault(block.protocol_element_id, []).append(
                ProtocolElementBlockRead(
                    id=block.public_id,
                    protocol_element_id=public_id_service.resolve_public_id(db, ProtocolElement, block.protocol_element_id),
                    template_element_block_id=public_id_service.resolve_public_id(db, TemplateElementBlock, block.template_element_block_id)
                    if block.template_element_block_id is not None
                    else None,
                    element_definition_id=public_id_service.resolve_public_id(db, ElementDefinition, block.element_definition_id)
                    if block.element_definition_id is not None
                    else None,
                    element_type_id=block.element_type_id,
                    render_type_id=block.render_type_id,
                    element_type_code=row.element_type_code,
                    render_type_code=row.render_type_code,
                    config_version=block.config_version,
                    title_snapshot=block.title_snapshot,
                    display_title_snapshot=block.display_title_snapshot,
                    description_snapshot=block.description_snapshot,
                    block_title_snapshot=block.block_title_snapshot,
                    copy_from_last_protocol=bool(config.get("copy_from_last_protocol", False)),
                    is_editable_snapshot=block.is_editable_snapshot,
                    allows_multiple_values_snapshot=block.allows_multiple_values_snapshot,
                    sort_index=block.sort_index,
                    render_order=block.render_order,
                    is_required_snapshot=block.is_required_snapshot,
                    is_visible_snapshot=block.is_visible_snapshot,
                    export_visible_snapshot=block.export_visible_snapshot,
                    configuration_snapshot_json=config,
                    public_reference_ids=snapshot_reference_ids(db, config, protocol_tenant_id),
                    text_content=row.text_content,
                    tracked_dirty=bool(row.tracked_dirty),
                    tracked_baseline_content=row.tracked_baseline_content,
                    display_compiled_text=row.display_compiled_text,
                    display_snapshot_json=row.display_snapshot_json or {},
                )
            )

        return [
            ProtocolElementRead(
                id=element.public_id,
                protocol_id=public_id_service.resolve_public_id(db, Protocol, element.protocol_id),
                template_element_id=public_id_service.resolve_public_id(db, TemplateElement, element.template_element_id)
                if element.template_element_id is not None
                else None,
                sort_index=element.sort_index,
                section_name_snapshot=section_titles_by_element_id[element.id],
                section_order_snapshot=element.section_order_snapshot,
                is_required_snapshot=element.is_required_snapshot,
                is_visible_snapshot=element.is_visible_snapshot,
                export_visible_snapshot=element.export_visible_snapshot,
                show_when_empty=show_when_empty_by_id.get(element.id, False),
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

    def delete_protocol_element_block(self, db: Session, protocol_element_block_id: int) -> bool:
        protocol_element_block = self.block_repository.get(db, protocol_element_block_id)
        if protocol_element_block is None:
            return False
        self.block_repository.delete(db, protocol_element_block)
        return True

    def update_protocol_element_block(self, db: Session, protocol_element_block_id: int, payload: ProtocolElementBlockUpdate):
        values = payload.model_dump(exclude_unset=True)
        expected_version = values.pop("expected_config_version", None)
        protocol_element_block = self.block_repository.get(db, protocol_element_block_id)
        if protocol_element_block is None:
            return None
        if not values:
            return protocol_element_block
        if "configuration_snapshot_json" in values:
            # Optimistische Sperre (Concurrency-Audit CONC-005): Zeile sperren und frisch laden,
            # dann gegen den Stand des Clients prüfen - sonst überschriebe das Gesamt-JSON still
            # eine gleichzeitige Änderung (z. B. eine andere Matrixzelle).
            protocol_element_block = lock_row(db, protocol_element_block)
            if expected_version is not None and expected_version != protocol_element_block.config_version:
                raise BlockConfigConflict(protocol_element_block)
        updated = self.block_repository.update(db, protocol_element_block, values)
        self._sync_session_date_marker(db, updated)
        return updated

    def set_attendance_status(
        self, db: Session, block_id: int, participant_id: int, participant_name: str, status: str
    ) -> ProtocolElementBlock | None:
        """Atomic, single-participant upsert into one attendance block's attendance_entries -
        reads the block fresh *under a row lock* and writes back only this participant's entry,
        instead of the client sending the whole array back (see focused-element-editor.tsx::
        handleAttendanceChange). Ohne die Zeilensperre (Concurrency-Audit CONC-005) lasen zwei
        gleichzeitige Klicks denselben Stand und der zweite Commit verwarf den ersten."""
        block = self.block_repository.get(db, block_id)
        if block is None:
            return None
        block = lock_row(db, block)
        config = dict(block.configuration_snapshot_json or {})
        entries = [
            entry for entry in config.get("attendance_entries", []) if entry.get("participant_id") != participant_id
        ]
        entries.append({"participant_id": participant_id, "participant_name": participant_name, "status": status})
        config["attendance_entries"] = entries
        return self.block_repository.update(db, block, {"configuration_snapshot_json": config})

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
        parsed_time = parse_session_time(config.get("selected_time"))
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
            if category_id is None:
                # Falling back to the magic id 1 here (audit finding, 2026-08-25) would
                # silently attach the generated session-marker event to whatever category
                # happens to occupy that id - a missing seed category is a data/setup bug
                # that should surface loudly instead.
                raise ValueError("Neither 'group_session' nor 'other' event category is seeded for this installation")
            next_event = Event(
                tenant_id=protocol.tenant_id,
                event_date=parsed_date,
                start_time=parsed_time,
                event_category_id=int(category_id),
                tag=tag,
                title=title,
                description="Generated from session date block",
                is_session_marker=True,
            )
            db.add(next_event)
            db.flush()
            template.next_event_id = next_event.id
        else:
            next_event.event_date = parsed_date
            next_event.start_time = parsed_time
            next_event.tag = tag
            next_event.title = title
            db.add(next_event)

        if protocol.event_id:
            template.last_event_id = protocol.event_id

        db.add(template)
        db.commit()
