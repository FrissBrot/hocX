from datetime import date
from types import SimpleNamespace

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    DocumentTemplate,
    Event,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolExportCache,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoredFile,
    Template,
    TodoStatus,
)


class ExportRepository:
    def get_protocol(self, db: Session, protocol_id: int) -> Protocol | None:
        return db.get(Protocol, protocol_id)

    def get_document_template(self, db: Session, document_template_id: int | None) -> DocumentTemplate | None:
        if document_template_id is None:
            return None
        return db.get(DocumentTemplate, document_template_id)

    def list_protocol_elements(self, db: Session, protocol_id: int) -> list[ProtocolElement]:
        return list(
            db.scalars(
                select(ProtocolElement)
                .where(ProtocolElement.protocol_id == protocol_id)
                .order_by(ProtocolElement.sort_index.asc())
            )
        )

    def list_protocol_element_blocks(self, db: Session, protocol_element_id: int) -> list[ProtocolElementBlock]:
        return list(
            db.scalars(
                select(ProtocolElementBlock)
                .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
                .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
            )
        )

    def get_protocol_text(self, db: Session, protocol_element_block_id: int) -> ProtocolText | None:
        return db.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == protocol_element_block_id))

    def _frozen_todo_snapshot(self, protocol: Protocol | None) -> dict | None:
        # Gleiche Regel wie ProtocolTodoService.frozen_snapshot: nur abgeschlossene Protokolle.
        if protocol is None or protocol.status != "abgeschlossen":
            return None
        snapshot = protocol.todos_snapshot_json
        return snapshot if isinstance(snapshot, dict) else None

    @staticmethod
    def _snapshot_rows(items: list[dict]) -> list[SimpleNamespace]:
        """Snapshot-Einträge (ProtocolTodoRead als JSON) in dieselbe Zeilenform bringen wie
        die Live-Abfragen unten (row.ProtocolTodo.task, row.todo_status_code, ...)."""
        rows = []
        for item in items:
            due = item.get("resolved_due_date")
            rows.append(SimpleNamespace(
                ProtocolTodo=SimpleNamespace(task=item.get("task") or "", tags=item.get("tags") or []),
                todo_status_code=item.get("todo_status_code"),
                assigned_participant_name=item.get("assigned_participant_name"),
                due_event_title=item.get("due_event_title"),
                due_event_date=date.fromisoformat(item["due_event_date"]) if item.get("due_event_date") else None,
                resolved_due_date=date.fromisoformat(due) if due else None,
                resolved_due_label=item.get("resolved_due_label"),
            ))
        return rows

    def list_protocol_todos(self, db: Session, protocol_element_block_id: int):
        protocol = db.scalar(
            select(Protocol)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == protocol_element_block_id)
        )
        snapshot = self._frozen_todo_snapshot(protocol)
        if snapshot is not None:
            return self._snapshot_rows((snapshot.get("blocks") or {}).get(str(protocol_element_block_id)) or [])
        due_event = Event.__table__.alias("due_event")
        next_event = Event.__table__.alias("next_event")
        last_event = Event.__table__.alias("last_event")
        query = (
            select(
                ProtocolTodo,
                TodoStatus.code.label("todo_status_code"),
                Participant.display_name.label("assigned_participant_name"),
                due_event.c.title.label("due_event_title"),
                due_event.c.event_date.label("due_event_date"),
                case(
                    (ProtocolTodo.due_date.is_not(None), ProtocolTodo.due_date),
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.event_date),
                    (ProtocolTodo.due_marker == "next_session", next_event.c.event_date),
                    (ProtocolTodo.due_marker == "last_session", last_event.c.event_date),
                    else_=None,
                ).label("resolved_due_date"),
                case(
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.title),
                    (ProtocolTodo.due_marker == "next_session", "naechste Sitzung"),
                    (ProtocolTodo.due_marker == "last_session", "letzte Sitzung"),
                    else_=None,
                ).label("resolved_due_label"),
            )
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .outerjoin(Participant, Participant.id == ProtocolTodo.assigned_participant_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .join(Template, Template.id == Protocol.template_id)
            .outerjoin(due_event, due_event.c.id == ProtocolTodo.due_event_id)
            .outerjoin(next_event, next_event.c.id == Template.next_event_id)
            .outerjoin(last_event, last_event.c.id == Template.last_event_id)
            .where(ProtocolTodo.protocol_element_block_id == protocol_element_block_id)
            .where(ProtocolTodo.pending_delete.is_(False))
            .order_by(ProtocolTodo.sort_index.asc())
        )
        return db.execute(query).all()

    def list_todos_by_tag(self, db: Session, protocol_id: int, tag: str):
        snapshot = self._frozen_todo_snapshot(db.get(Protocol, protocol_id))
        if snapshot is not None:
            items = [item for block in (snapshot.get("blocks") or {}).values() for item in block if tag in (item.get("tags") or [])]
            items.sort(key=lambda item: item.get("sort_index") or 0)
            return self._snapshot_rows(items)
        due_event = Event.__table__.alias("due_event")
        next_event = Event.__table__.alias("next_event")
        last_event = Event.__table__.alias("last_event")
        query = (
            select(
                ProtocolTodo,
                TodoStatus.code.label("todo_status_code"),
                Participant.display_name.label("assigned_participant_name"),
                due_event.c.title.label("due_event_title"),
                due_event.c.event_date.label("due_event_date"),
                case(
                    (ProtocolTodo.due_date.is_not(None), ProtocolTodo.due_date),
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.event_date),
                    (ProtocolTodo.due_marker == "next_session", next_event.c.event_date),
                    (ProtocolTodo.due_marker == "last_session", last_event.c.event_date),
                    else_=None,
                ).label("resolved_due_date"),
                case(
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.title),
                    (ProtocolTodo.due_marker == "next_session", "naechste Sitzung"),
                    (ProtocolTodo.due_marker == "last_session", "letzte Sitzung"),
                    else_=None,
                ).label("resolved_due_label"),
            )
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .outerjoin(Participant, Participant.id == ProtocolTodo.assigned_participant_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .join(Template, Template.id == Protocol.template_id)
            .outerjoin(due_event, due_event.c.id == ProtocolTodo.due_event_id)
            .outerjoin(next_event, next_event.c.id == Template.next_event_id)
            .outerjoin(last_event, last_event.c.id == Template.last_event_id)
            .where(Protocol.id == protocol_id)
            .where(ProtocolTodo.tags.op("@>")(func.jsonb_build_array(tag)))
            .order_by(ProtocolTodo.sort_index.asc())
        )
        return db.execute(query).all()

    def list_protocol_images(self, db: Session, protocol_element_block_id: int):
        query = (
            select(ProtocolImage, StoredFile)
            .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
            .where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolImage.sort_index.asc())
        )
        return db.execute(query).all()

    def create_stored_file(self, db: Session, stored_file: StoredFile) -> StoredFile:
        db.add(stored_file)
        db.flush()
        return stored_file

    def create_export_cache(self, db: Session, cache: ProtocolExportCache) -> ProtocolExportCache:
        db.add(cache)
        db.flush()
        return cache

    def latest_export_cache(
        self, db: Session, protocol_id: int, *, export_format: str | None = None
    ) -> ProtocolExportCache | None:
        """Neuester Export eines Protokolls; mit export_format nur dieser Art. Der Inhaltsvergleich
        in ExportService.export_pdf braucht die Art: ohne Filter verglich er den Protokoll-Body
        auch mit dem Body einer zwischendurch exportierten Todo-/Terminliste (bzw. dem kompletten
        LaTeX-Quelltext eines LaTeX-Exports) und zählte die Protokollversion grundlos hoch."""
        query = select(ProtocolExportCache).where(ProtocolExportCache.protocol_id == protocol_id)
        if export_format is not None:
            query = query.where(ProtocolExportCache.export_format == export_format)
        return db.scalar(query.order_by(ProtocolExportCache.created_at.desc(), ProtocolExportCache.id.desc()))

    def get_stored_file(self, db: Session, stored_file_id: int | None) -> StoredFile | None:
        if stored_file_id is None:
            return None
        return db.get(StoredFile, stored_file_id)
