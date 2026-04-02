from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    DocumentTemplate,
    ElementDefinition,
    ElementType,
    Event,
    ListEntry,
    Participant,
    Protocol,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolTodo,
    ProtocolText,
    Template,
    TemplateElement,
    TemplateParticipant,
    TodoStatus,
)
from app.services.document_template_service import DocumentTemplateService
from app.services.access_service import AccessService
from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolUpdate


class ProtocolService:
    def __init__(self, repository: ProtocolRepository | None = None) -> None:
        self.repository = repository or ProtocolRepository()
        self.document_template_service = DocumentTemplateService()
        self.access_service = AccessService()

    def list_protocols(
        self,
        db: Session,
        *,
        tenant_id: int,
        query: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
        restrict_to_assigned: bool = False,
    ):
        protocol_ids = None
        if restrict_to_assigned and user_id is not None:
            protocol_ids = self.access_service.repository.list_protocol_ids(db, user_id=user_id, tenant_id=tenant_id)
        return self.repository.list(db, tenant_id=tenant_id, query=query, status=status, protocol_ids=protocol_ids)

    def get_protocol(self, db: Session, protocol_id: int):
        return self.repository.get(db, protocol_id)

    def _cycle_bounds(self, protocol_date: date, *, reset_month: int, reset_day: int) -> tuple[date, date]:
        cutoff_this_year = date(protocol_date.year, reset_month, reset_day)
        if protocol_date <= cutoff_this_year:
            cycle_end = cutoff_this_year
            previous_cutoff = date(protocol_date.year - 1, reset_month, reset_day)
            cycle_start = previous_cutoff + timedelta(days=1)
        else:
            cycle_start = cutoff_this_year + timedelta(days=1)
            cycle_end = date(protocol_date.year + 1, reset_month, reset_day)
        return cycle_start, cycle_end

    def _sequence_counts(self, db: Session, *, tenant_id: int, template_id: int, protocol_date: date, reset_month: int, reset_day: int) -> dict[str, int]:
        cycle_start, cycle_end = self._cycle_bounds(protocol_date, reset_month=reset_month, reset_day=reset_day)
        overall = self.repository.next_template_sequence(db, tenant_id=tenant_id, template_id=template_id)

        yearly = int(
            db.scalar(
                select(func.count(Protocol.id)).where(
                    Protocol.tenant_id == tenant_id,
                    Protocol.template_id == template_id,
                    func.extract("year", Protocol.protocol_date) == protocol_date.year,
                )
            )
            or 0
        ) + 1

        monthly = int(
            db.scalar(
                select(func.count(Protocol.id)).where(
                    Protocol.tenant_id == tenant_id,
                    Protocol.template_id == template_id,
                    func.extract("year", Protocol.protocol_date) == protocol_date.year,
                    func.extract("month", Protocol.protocol_date) == protocol_date.month,
                )
            )
            or 0
        ) + 1

        cycle = int(
            db.scalar(
                select(func.count(Protocol.id)).where(
                    Protocol.tenant_id == tenant_id,
                    Protocol.template_id == template_id,
                    Protocol.protocol_date >= cycle_start,
                    Protocol.protocol_date <= cycle_end,
                )
            )
            or 0
        ) + 1

        return {
            "n": overall,
            "n_year": yearly,
            "n_month": monthly,
            "n_cycle": cycle,
            "cycle_year_start": cycle_start.year,
            "cycle_year_end": cycle_end.year,
        }

    def _format_pattern(self, pattern: str | None, *, counts: dict[str, int], protocol_date: date) -> str | None:
        if not pattern:
            return None
        rendered = pattern
        square_bracket_tokens = [
            "n",
            "n_year",
            "n_month",
            "n_cycle",
            "date",
            "dd.mm.yyyy",
            "dd.mm.yy",
            "date:DD.MM.YYYY",
            "date:DD.MM.YY",
            "date:YYYY-MM-DD",
            "date:DD.MM",
            "yyyy",
            "yy",
            "mm",
            "m",
            "dd",
            "d",
            "cycle_yyyy_start",
            "cycle_yyyy_end",
        ]
        for token in square_bracket_tokens:
            rendered = rendered.replace(f"[{token}]", f"{{{token}}}")
        replacements = {
            "{n}": str(counts["n"]),
            "{n_year}": str(counts["n_year"]),
            "{n_month}": str(counts["n_month"]),
            "{n_cycle}": str(counts["n_cycle"]),
            "{date}": protocol_date.strftime("%d.%m.%Y"),
            "{dd.mm.yyyy}": protocol_date.strftime("%d.%m.%Y"),
            "{dd.mm.yy}": protocol_date.strftime("%d.%m.%y"),
            "{date:DD.MM.YYYY}": protocol_date.strftime("%d.%m.%Y"),
            "{date:DD.MM.YY}": protocol_date.strftime("%d.%m.%y"),
            "{date:YYYY-MM-DD}": protocol_date.strftime("%Y-%m-%d"),
            "{date:DD.MM}": protocol_date.strftime("%d.%m"),
            "{yyyy}": protocol_date.strftime("%Y"),
            "{yy}": protocol_date.strftime("%y"),
            "{mm}": protocol_date.strftime("%m"),
            "{m}": str(protocol_date.month),
            "{dd}": protocol_date.strftime("%d"),
            "{d}": str(protocol_date.day),
            "{cycle_yyyy_start}": str(counts["cycle_year_start"]),
            "{cycle_yyyy_end}": str(counts["cycle_year_end"]),
        }
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        return rendered

    def _payload_key(
        self,
        *,
        source_sort_index: int,
        repeat_source_type: str | None = None,
        repeat_source_id: int | None = None,
    ) -> tuple[int, str, int | None]:
        return (int(source_sort_index), repeat_source_type or "", int(repeat_source_id) if repeat_source_id is not None else None)

    def _render_context_text(self, value: str | None, context: dict | None) -> str | None:
        if value is None or not context:
            return value
        context_tokens = context.get("tokens", {}) if isinstance(context, dict) else {}
        if not context_tokens:
            return value
        rendered = value
        for token, replacement in context_tokens.items():
            rendered = rendered.replace(token, replacement)
        return rendered

    def _coerce_optional_int(self, value) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_int_list(self, values) -> list[int]:
        if not isinstance(values, list):
            return []
        result: list[int] = []
        for value in values:
            parsed = self._coerce_optional_int(value)
            if parsed is not None:
                result.append(parsed)
        return result

    def _recently_listed_event_ids(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        template_element_id: int | None,
        protocol_date: date,
        current_protocol_id: int,
        lookback_protocols: int = 3,
    ) -> set[int]:
        if template_element_id is None or lookback_protocols <= 0:
            return set()
        recent_protocol_ids = list(
            db.scalars(
                select(Protocol.id)
                .where(
                    Protocol.tenant_id == tenant_id,
                    Protocol.template_id == template_id,
                    Protocol.id != current_protocol_id,
                    or_(
                        Protocol.protocol_date < protocol_date,
                        (Protocol.protocol_date == protocol_date) & (Protocol.id < current_protocol_id),
                    ),
                )
                .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
                .limit(lookback_protocols)
            )
        )
        if not recent_protocol_ids:
            return set()
        listed_ids: set[int] = set()
        rows = db.execute(
            select(ProtocolElementBlock.configuration_snapshot_json)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(
                ProtocolElement.protocol_id.in_(recent_protocol_ids),
                ProtocolElement.template_element_id == template_element_id,
            )
        ).scalars()
        for config in rows:
            if not isinstance(config, dict):
                continue
            if str(config.get("repeat_source_type") or "") != "event":
                continue
            source_id = config.get("repeat_source_id")
            if source_id is None:
                continue
            try:
                listed_ids.add(int(source_id))
            except (TypeError, ValueError):
                continue
        return listed_ids

    def _latest_previous_protocol_id(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_date: date,
        current_protocol_id: int,
    ) -> int | None:
        return db.scalar(
            select(Protocol.id)
            .where(
                Protocol.tenant_id == tenant_id,
                Protocol.template_id == template_id,
                Protocol.id != current_protocol_id,
                or_(
                    Protocol.protocol_date < protocol_date,
                    (Protocol.protocol_date == protocol_date) & (Protocol.id < current_protocol_id),
                ),
            )
            .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
            .limit(1)
        )

    def _event_repeat_contexts(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        template_element_id: int | None,
        protocol_date: date,
        current_protocol_id: int,
        repeat_config: dict,
    ) -> list[dict[str, object]]:
        statement = select(Event).where(Event.tenant_id == tenant_id)
        tag_filter = str(repeat_config.get("event_tag_filter") or "").strip().lower()
        title_filter = str(repeat_config.get("event_title_filter") or "").strip().lower()
        description_filter = str(repeat_config.get("event_description_filter") or "").strip().lower()
        date_mode = str(repeat_config.get("event_date_mode") or "relative_window")
        window_start_days = int(repeat_config.get("event_window_start_days") or 0)
        window_end_days = int(repeat_config.get("event_window_end_days") or 14)
        include_unlisted_past = bool(repeat_config.get("event_include_unlisted_past", False))
        start_date = protocol_date + timedelta(days=min(window_start_days, window_end_days))
        end_date = protocol_date + timedelta(days=max(window_start_days, window_end_days))
        if date_mode == "all_future" and not include_unlisted_past:
            statement = statement.where(Event.event_date >= protocol_date)
        statement = statement.order_by(Event.event_date.asc(), Event.id.asc())
        recently_listed_ids = (
            self._recently_listed_event_ids(
                db,
                tenant_id=tenant_id,
                template_id=template_id,
                template_element_id=template_element_id,
                protocol_date=protocol_date,
                current_protocol_id=current_protocol_id,
            )
            if include_unlisted_past
            else set()
        )
        contexts: list[dict[str, object]] = []
        for event in db.scalars(statement):
            event_end_date = event.event_end_date or event.event_date
            if tag_filter and tag_filter not in (event.tag or "").lower():
                continue
            if title_filter and title_filter not in (event.title or "").lower():
                continue
            if description_filter and description_filter not in (event.description or "").lower():
                continue
            in_primary_window = (
                event_end_date >= protocol_date
                if date_mode == "all_future"
                else event_end_date >= start_date and event.event_date <= end_date
            )
            include_as_past_catchup = include_unlisted_past and event_end_date < protocol_date and event.id not in recently_listed_ids
            if not in_primary_window and not include_as_past_catchup:
                continue
            date_range = event.event_date.strftime("%d.%m.%Y") if event_end_date == event.event_date else f"{event.event_date.strftime('%d.%m.%Y')} - {event_end_date.strftime('%d.%m.%Y')}"
            contexts.append(
                {
                    "tokens": {
                        "{title}": event.title or "",
                        "{Titel}": event.title or "",
                        "{description}": event.description or "",
                        "{Beschreibung}": event.description or "",
                        "{event_date}": event.event_date.strftime("%d.%m.%Y"),
                        "{event_end_date}": event_end_date.strftime("%d.%m.%Y"),
                        "{event_date_range}": date_range,
                        "{date}": event.event_date.strftime("%d.%m.%Y"),
                        "{tag}": event.tag or "",
                        "{id}": str(event.id),
                    },
                    "source_type": "event",
                    "source_id": event.id,
                    "source_label": event.title or "",
                }
            )
        return contexts

    def _todo_repeat_contexts(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_date: date,
        current_protocol_id: int,
        repeat_config: dict,
    ) -> list[dict[str, object]]:
        latest_protocol_id = self._latest_previous_protocol_id(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            protocol_date=protocol_date,
            current_protocol_id=current_protocol_id,
        )
        if latest_protocol_id is None:
            return []
        closed_status_ids = list(db.scalars(select(TodoStatus.id).where(TodoStatus.code.in_(["done", "cancelled"]))))
        statement = (
            select(ProtocolTodo, ProtocolElementBlock.block_title_snapshot, Participant.display_name)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .outerjoin(Participant, Participant.id == ProtocolTodo.assigned_participant_id)
            .where(
                Protocol.tenant_id == tenant_id,
                Protocol.template_id == template_id,
                Protocol.id == latest_protocol_id,
            )
            .order_by(Protocol.protocol_date.desc(), ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
        )
        if bool(repeat_config.get("todo_open_only", True)) and closed_status_ids:
            statement = statement.where(ProtocolTodo.todo_status_id.not_in(closed_status_ids))
        block_title_filter = str(repeat_config.get("todo_block_title_filter") or "").strip().lower()
        task_filter = str(repeat_config.get("todo_task_filter") or "").strip().lower()
        contexts: list[dict[str, str]] = []
        for todo, block_title, participant_name in db.execute(statement).all():
            if block_title_filter and block_title_filter not in (block_title or "").lower():
                continue
            if task_filter and task_filter not in (todo.task or "").lower():
                continue
            contexts.append(
                {
                    "tokens": {
                        "{title}": todo.task,
                        "{task}": todo.task,
                        "{Titel}": todo.task,
                        "{description}": todo.reference_link or "",
                        "{Beschreibung}": todo.reference_link or "",
                        "{due_date}": todo.due_date.strftime("%d.%m.%Y") if todo.due_date else "",
                        "{participant}": participant_name or "",
                        "{id}": str(todo.id),
                    },
                    "source_type": "todo",
                    "source_id": todo.id,
                    "source_label": todo.task,
                }
            )
        return contexts

    def _previous_protocol_element(self, db: Session, *, tenant_id: int, template_element_id: int | None, protocol_date: date, current_protocol_id: int):
        if template_element_id is None:
            return None
        query = (
            select(ProtocolElement)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .where(
                Protocol.tenant_id == tenant_id,
                ProtocolElement.template_element_id == template_element_id,
                Protocol.id != current_protocol_id,
                or_(
                    Protocol.protocol_date < protocol_date,
                    (Protocol.protocol_date == protocol_date) & (Protocol.id < current_protocol_id),
                ),
            )
            .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
            .limit(1)
        )
        return db.scalar(query)

    def _previous_block_payloads(self, db: Session, *, protocol_element_id: int) -> dict[tuple[int, str, int | None], dict]:
        rows = db.execute(
            select(ProtocolElementBlock, ProtocolText.content)
            .outerjoin(ProtocolText, ProtocolText.protocol_element_block_id == ProtocolElementBlock.id)
            .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
            .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
        ).all()
        payloads: dict[tuple[int, str, int | None], dict] = {}
        for row in rows:
            block = row.ProtocolElementBlock
            block_config = block.configuration_snapshot_json or {}
            source_sort_index = int(block_config.get("source_sort_index") or block.sort_index)
            repeat_source_type = str(block_config.get("repeat_source_type") or "") or None
            repeat_source_id_raw = block_config.get("repeat_source_id")
            try:
                repeat_source_id = int(repeat_source_id_raw) if repeat_source_id_raw is not None else None
            except (TypeError, ValueError):
                repeat_source_id = None
            todos = list(
                db.scalars(
                    select(ProtocolTodo)
                    .where(ProtocolTodo.protocol_element_block_id == block.id)
                    .order_by(ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
                )
            )
            payloads[self._payload_key(
                source_sort_index=source_sort_index,
                repeat_source_type=repeat_source_type,
                repeat_source_id=repeat_source_id,
            )] = {
                "text_content": row.content,
                "todos": todos,
            }
        return payloads

    def _open_todos_for_template_block(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        template_element_id: int,
        block_sort_index: int,
        protocol_date: date,
        current_protocol_id: int,
        repeat_source_type: str | None = None,
        repeat_source_id: int | None = None,
    ) -> list[ProtocolTodo]:
        latest_protocol_id = self._latest_previous_protocol_id(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            protocol_date=protocol_date,
            current_protocol_id=current_protocol_id,
        )
        if latest_protocol_id is None:
            return []
        closed_status_ids = list(
            db.scalars(select(TodoStatus.id).where(TodoStatus.code.in_(["done", "cancelled"])))
        )
        query = (
            select(ProtocolTodo, ProtocolElementBlock)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .where(
                Protocol.tenant_id == tenant_id,
                Protocol.template_id == template_id,
                ProtocolElement.template_element_id == template_element_id,
                ProtocolElementBlock.sort_index == block_sort_index,
                Protocol.id == latest_protocol_id,
            )
            .order_by(Protocol.protocol_date.desc(), Protocol.id.desc(), ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
        )
        if closed_status_ids:
            query = query.where(ProtocolTodo.todo_status_id.not_in(closed_status_ids))
        todos: list[ProtocolTodo] = []
        for todo, block in db.execute(query).all():
            block_config = block.configuration_snapshot_json or {}
            source_sort_index = int(block_config.get("source_sort_index") or block.sort_index)
            row_repeat_source_type = str(block_config.get("repeat_source_type") or "") or None
            row_repeat_source_id_raw = block_config.get("repeat_source_id")
            try:
                row_repeat_source_id = int(row_repeat_source_id_raw) if row_repeat_source_id_raw is not None else None
            except (TypeError, ValueError):
                row_repeat_source_id = None
            if source_sort_index != block_sort_index:
                continue
            if (repeat_source_type or row_repeat_source_type) and row_repeat_source_type != repeat_source_type:
                continue
            if (repeat_source_id is not None or row_repeat_source_id is not None) and row_repeat_source_id != repeat_source_id:
                continue
            todos.append(todo)
        return todos

    def _block_repeat_contexts(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        template_element_id: int,
        protocol_date: date,
        current_protocol_id: int,
        block: dict,
        legacy_repeat_config: dict,
    ) -> list[dict[str, object] | None]:
        block_config = dict(block.get("configuration_json") or {})
        effective_repeat_config = dict(block_config)
        if not block_config.get("repeat_source") and legacy_repeat_config.get("repeat_source"):
            effective_repeat_config = {
                **legacy_repeat_config,
                **block_config,
            }
        repeat_source = str(effective_repeat_config.get("repeat_source") or "none")
        if repeat_source == "event":
            return self._event_repeat_contexts(
                db,
                tenant_id=tenant_id,
                template_id=template_id,
                template_element_id=template_element_id,
                protocol_date=protocol_date,
                current_protocol_id=current_protocol_id,
                repeat_config=effective_repeat_config,
            )
        if repeat_source == "todo":
            return self._todo_repeat_contexts(
                db,
                tenant_id=tenant_id,
                template_id=template_id,
                protocol_date=protocol_date,
                current_protocol_id=current_protocol_id,
                repeat_config=effective_repeat_config,
            )
        return [None]

    def create_from_template(self, db: Session, payload: ProtocolCreateFromTemplate, *, tenant_id: int, created_by: int | None) -> int:
        template = db.get(Template, payload.template_id)
        if template is None:
            raise ValueError("Template not found")
        if template.tenant_id != tenant_id:
            raise ValueError("Template does not belong to current tenant")

        selected_document_template_id = template.document_template_id
        document_template = db.get(DocumentTemplate, selected_document_template_id) if selected_document_template_id else None
        counts = self._sequence_counts(
            db,
            tenant_id=tenant_id,
            template_id=template.id,
            protocol_date=payload.protocol_date,
            reset_month=template.cycle_reset_month,
            reset_day=template.cycle_reset_day,
        )
        protocol_number = payload.protocol_number or self._format_pattern(
            template.protocol_number_pattern,
            counts=counts,
            protocol_date=payload.protocol_date,
        )
        title = payload.title or self._format_pattern(
            template.title_pattern,
            counts=counts,
            protocol_date=payload.protocol_date,
        )
        if not protocol_number:
            raise ValueError("Protocol number is required or must be derivable from the template pattern")
        protocol = Protocol(
            tenant_id=tenant_id,
            template_id=template.id,
            template_version=template.version,
            document_template_id=selected_document_template_id,
            document_template_version=document_template.version if document_template else None,
            document_template_path_snapshot=None,
            protocol_number=protocol_number,
            title=title,
            protocol_date=payload.protocol_date,
            event_id=payload.event_id,
            status="geplant",
            created_by=created_by,
        )
        db.add(protocol)
        db.flush()

        text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "text"))
        todo_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "todo"))
        display_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "display"))
        static_text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "static_text"))
        form_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "form"))
        event_list_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "event_list"))
        bullet_list_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "bullet_list"))
        attendance_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "attendance"))
        session_date_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "session_date"))
        matrix_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "matrix"))

        template_rows = db.execute(
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template.id)
            .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
        ).all()

        visible_element_index = 0
        for template_element, definition in template_rows:
            legacy_repeat_config = template_element.configuration_json or {}
            definition_blocks = sorted(
                (definition.configuration_json or {}).get("blocks", []),
                key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0)),
            )
            generated_blocks: list[tuple[dict, dict[str, object] | None, int]] = []
            next_block_sort_index = 10
            for block in definition_blocks:
                repeat_contexts = self._block_repeat_contexts(
                    db,
                    tenant_id=tenant_id,
                    template_id=template.id,
                    template_element_id=template_element.id,
                    protocol_date=payload.protocol_date,
                    current_protocol_id=protocol.id,
                    block=block,
                    legacy_repeat_config=legacy_repeat_config if len(definition_blocks) == 1 else {},
                )
                if not repeat_contexts:
                    continue
                for repeat_context in repeat_contexts:
                    generated_blocks.append((block, repeat_context, next_block_sort_index))
                    next_block_sort_index += 10
            if not generated_blocks:
                continue
            visible_element_index += 1
            previous_element = self._previous_protocol_element(
                db,
                tenant_id=tenant_id,
                template_element_id=template_element.id,
                protocol_date=payload.protocol_date,
                current_protocol_id=protocol.id,
            )
            previous_payloads = (
                self._previous_block_payloads(db, protocol_element_id=previous_element.id)
                if previous_element is not None
                else {}
            )
            protocol_element = ProtocolElement(
                protocol_id=protocol.id,
                template_element_id=template_element.id,
                sort_index=visible_element_index * 10,
                section_name_snapshot=definition.title,
                section_order_snapshot=visible_element_index * 10,
                is_required_snapshot=False,
                is_visible_snapshot=True,
                export_visible_snapshot=True,
            )
            db.add(protocol_element)
            db.flush()

            for block, repeat_context, resolved_sort_index in generated_blocks:
                block_config = dict(block.get("configuration_json") or {})
                carry_from_last_protocol = bool(block.get("copy_from_last_protocol", False))
                repeat_source_type = str(repeat_context.get("source_type") or "") if repeat_context else ""
                repeat_source_id_raw = repeat_context.get("source_id") if repeat_context else None
                try:
                    repeat_source_id = int(repeat_source_id_raw) if repeat_source_id_raw is not None else None
                except (TypeError, ValueError):
                    repeat_source_id = None
                previous_payload = previous_payloads.get(
                    self._payload_key(
                        source_sort_index=block["sort_index"],
                        repeat_source_type=repeat_source_type or None,
                        repeat_source_id=repeat_source_id,
                    ),
                    {},
                )
                carried_text = previous_payload.get("text_content") if carry_from_last_protocol else None
                rendered_default_content = self._render_context_text(block.get("default_content"), repeat_context) or ""
                protocol_block = ProtocolElementBlock(
                    protocol_element_id=protocol_element.id,
                    template_element_block_id=None,
                    element_definition_id=definition.id,
                    element_type_id=block["element_type_id"],
                    render_type_id=block["render_type_id"],
                    title_snapshot=self._render_context_text(block["title"], repeat_context) or block["title"],
                    display_title_snapshot=self._render_context_text(block.get("title"), repeat_context),
                    description_snapshot=self._render_context_text(block.get("description"), repeat_context),
                    block_title_snapshot=self._render_context_text(block.get("block_title"), repeat_context),
                    is_editable_snapshot=block.get("is_editable", True),
                    allows_multiple_values_snapshot=block.get("allows_multiple_values", False),
                    sort_index=resolved_sort_index,
                    render_order=resolved_sort_index,
                    is_required_snapshot=False,
                    is_visible_snapshot=block.get("is_visible", True),
                    export_visible_snapshot=block.get("export_visible", True),
                    latex_template_snapshot=block.get("latex_template"),
                    configuration_snapshot_json={
                        **block_config,
                        "default_content": self._render_context_text(block.get("default_content"), repeat_context),
                        "copy_from_last_protocol": carry_from_last_protocol,
                        "left_column_heading": block_config.get("left_column_heading") or legacy_repeat_config.get("left_column_heading"),
                        "value_column_heading": block_config.get("value_column_heading") or legacy_repeat_config.get("value_column_heading"),
                        "repeat_context": (repeat_context or {}).get("tokens", {}),
                        "source_sort_index": block["sort_index"],
                        "repeat_source_type": repeat_source_type or None,
                        "repeat_source_id": repeat_source_id,
                        "repeat_source_label": (repeat_context or {}).get("source_label"),
                    },
                )
                db.add(protocol_block)
                db.flush()

                if block["element_type_id"] == text_type_id:
                    db.add(
                        ProtocolText(
                            protocol_element_block_id=protocol_block.id,
                            content=carried_text if carried_text is not None else rendered_default_content,
                        )
                    )
                elif block["element_type_id"] == static_text_type_id:
                    db.add(
                        ProtocolText(
                            protocol_element_block_id=protocol_block.id,
                            content=carried_text if carried_text is not None else rendered_default_content,
                        )
                    )
                elif block["element_type_id"] == display_type_id:
                    db.add(
                        ProtocolDisplaySnapshot(
                            protocol_element_block_id=protocol_block.id,
                            source_type=None,
                            source_id=None,
                            compiled_text=None,
                            snapshot_json={},
                        )
                    )
                elif block["element_type_id"] == bullet_list_type_id:
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "bullet_items": [],
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == form_type_id:
                    _form_cfg = protocol_block.configuration_snapshot_json or {}
                    linked_list_id = self._coerce_optional_int(_form_cfg.get("linked_list_id"))
                    # Support both new "rows" and old "field_rows" schema
                    _form_raw_rows = _form_cfg.get("rows") or _form_cfg.get("field_rows") or []
                    field_rows = (
                        []
                        if linked_list_id
                        else [
                            {
                                "id": row.get("id"),
                                "label": self._render_context_text(row.get("label") or row.get("title") or "Feld", repeat_context) or "Feld",
                                "value_type": row_value_type,
                                "sort_index": row.get("sort_index"),
                                "text_value": self._render_context_text(row.get("template_value") or "", repeat_context) or "" if row_value_type == "text" else "",
                                "participant_id": self._coerce_optional_int(row.get("template_participant_id")) if row_value_type == "participant" else None,
                                "participant_ids": self._coerce_int_list(row.get("template_participant_ids")) if row_value_type == "participants" else [],
                                "event_id": self._coerce_optional_int(row.get("template_event_id")) if row_value_type == "event" else None,
                            }
                            for row in _form_raw_rows
                            # New schema uses row_type; old schema uses value_type
                            for row_value_type in [row.get("row_type") or row.get("value_type") or "text"]
                        ]
                    )
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "linked_list_id": linked_list_id,
                        "rows": field_rows,
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == matrix_type_id:
                    _matrix_cfg = protocol_block.configuration_snapshot_json or {}
                    # Backward compat: support both old field_rows and new rows
                    _raw_rows = _matrix_cfg.get("rows") or _matrix_cfg.get("field_rows") or []
                    # Backward compat: support both old matrix_columns and new columns
                    _raw_columns = _matrix_cfg.get("columns") or _matrix_cfg.get("matrix_columns") or []

                    def _matrix_row_type(row: dict) -> str:
                        # New schema: row_type field
                        if row.get("row_type"):
                            return str(row["row_type"])
                        # Old schema: embedded_element_type_id takes precedence
                        if row.get("embedded_element_type_id"):
                            return str(row["embedded_element_type_id"])
                        # Old schema: value_type
                        return str(row.get("value_type") or "text")

                    def _matrix_row_config(row: dict) -> dict:
                        if isinstance(row.get("row_config"), dict):
                            return row["row_config"]
                        cfg: dict = {}
                        old_embedded = row.get("embedded_configuration_json")
                        if isinstance(old_embedded, dict):
                            cfg.update(old_embedded)
                        for k in ("event_tag_filter", "event_title_filter", "use_column_title_as_tag", "hide_past_events"):
                            if k in row:
                                cfg.setdefault(k, row[k])
                        return cfg

                    matrix_rows = [
                        {
                            "id": row.get("id"),
                            "label": self._render_context_text(row.get("label") or row.get("title") or "Feld", repeat_context) or "Feld",
                            "row_type": _matrix_row_type(row),
                            "locked_in_protocol": bool(
                                row.get("locked_in_protocol") if "locked_in_protocol" in row
                                else not bool(row.get("protocol_editable", True))
                            ),
                            "sort_index": row.get("sort_index"),
                            "row_config": _matrix_row_config(row),
                            "auto_source_field": row.get("auto_source_field")
                                or row.get("source_field_participant")
                                or row.get("source_field_event")
                                or row.get("source_field_list"),
                            # Keep for export_service backward compat
                            "template_value": self._render_context_text(row.get("template_value") or "", repeat_context) or "",
                            "template_participant_id": self._coerce_optional_int(row.get("template_participant_id")),
                            "template_participant_ids": self._coerce_int_list(row.get("template_participant_ids")),
                            "template_event_id": self._coerce_optional_int(row.get("template_event_id")),
                        }
                        for row in _raw_rows
                    ]

                    def _build_row_values(column: dict, rows: list) -> dict:
                        # New schema: row_overrides contains per-row preset values
                        overrides = column.get("row_overrides") or {}
                        result: dict = {}
                        for row in rows:
                            row_id = str(row.get("id") or "")
                            if row_id in overrides and isinstance(overrides[row_id], dict):
                                result[row_id] = overrides[row_id]
                            else:
                                row_type = row.get("row_type") or "text"
                                template_value = row.get("template_value") or ""
                                if row_type == "text" and str(template_value).strip():
                                    result[row_id] = {"text_value": str(template_value)}
                                elif row_type == "participant" and row.get("template_participant_id"):
                                    result[row_id] = {"participant_id": row["template_participant_id"]}
                                elif row_type == "participants" and row.get("template_participant_ids"):
                                    result[row_id] = {"participant_ids": row["template_participant_ids"]}
                                elif row_type == "event" and row.get("template_event_id"):
                                    result[row_id] = {"event_id": row["template_event_id"]}
                        return result

                    # auto_source: new schema or backward compat from matrix_column_source*
                    _old_src_type = _matrix_cfg.get("matrix_column_source") or ""
                    _auto_source = _matrix_cfg.get("auto_source") or (
                        {
                            "type": _old_src_type,
                            "list_id": _matrix_cfg.get("matrix_column_source_list_id"),
                            "event_tag_filter": _matrix_cfg.get("matrix_column_source_event_tag"),
                        }
                        if _old_src_type else None
                    )

                    def _auto_cell_value(row: dict, col_value: dict) -> dict:
                        """Map a list entry column value to a matrix cell value based on row_type."""
                        row_type = row.get("row_type") or "text"
                        ids = col_value.get("participant_ids") or []
                        pid = col_value.get("participant_id")
                        eid = col_value.get("event_id")
                        if ids:
                            if row_type == "participants":
                                return {"participant_ids": ids}
                            if row_type == "participant":
                                return {"participant_id": ids[0]}
                        if pid is not None:
                            if row_type == "participants":
                                return {"participant_ids": [pid]}
                            return {"participant_id": pid}
                        if eid is not None:
                            return {"event_id": eid}
                        text = str(col_value.get("text_value") or "").strip()
                        return {"text_value": text} if text else {}

                    _matrix_mode = _matrix_cfg.get("mode") or "manual"
                    if _matrix_mode == "auto" and isinstance(_auto_source, dict) and _auto_source.get("type") == "list":
                        _list_id = int(_auto_source.get("list_id") or 0)
                        _list_entries = (
                            list(db.scalars(
                                select(ListEntry)
                                .where(ListEntry.list_definition_id == _list_id)
                                .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
                            ))
                            if _list_id else []
                        )
                        matrix_columns = []
                        for _idx, _entry in enumerate(_list_entries):
                            _col1 = dict(_entry.column_one_value_json or {})
                            _col2 = dict(_entry.column_two_value_json or {})
                            _title = str(_col1.get("text_value") or _col2.get("text_value") or "").strip() or f"Eintrag {_entry.id}"
                            _row_values: dict = {}
                            for _row in matrix_rows:
                                _row_id = str(_row.get("id") or "")
                                _src_field = _row.get("auto_source_field") or ""
                                if _src_field == "column_one":
                                    _row_values[_row_id] = _auto_cell_value(_row, _col1)
                                elif _src_field == "column_two":
                                    _row_values[_row_id] = _auto_cell_value(_row, _col2)
                            matrix_columns.append({
                                "id": f"gen-l-{_entry.id}",
                                "title": _title,
                                "sort_index": (_idx + 1) * 10,
                                "event_tag_filter": None,
                                "row_values": _row_values,
                            })
                    else:
                        matrix_columns = [
                            {
                                "id": column.get("id"),
                                "title": self._render_context_text(column.get("title") or "", repeat_context) or "",
                                "event_tag_filter": column.get("event_tag_filter"),
                                "sort_index": column.get("sort_index"),
                                "row_values": _build_row_values(column, matrix_rows),
                            }
                            for column in _raw_columns
                        ]

                    protocol_block.configuration_snapshot_json = {
                        **_matrix_cfg,
                        "block_kind": "matrix",
                        "mode": _matrix_cfg.get("mode") or "manual",
                        "allow_column_management": bool(
                            _matrix_cfg.get("allow_column_management",
                            _matrix_cfg.get("matrix_allow_column_management", False))
                        ),
                        "auto_source": _auto_source,
                        "rows": matrix_rows,
                        "columns": matrix_columns,
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == attendance_type_id:
                    participants = list(
                        db.execute(
                            select(Participant)
                            .join(TemplateParticipant, TemplateParticipant.participant_id == Participant.id)
                            .where(TemplateParticipant.template_id == template.id)
                            .order_by(Participant.display_name.asc(), Participant.id.asc())
                        ).scalars()
                    )
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "attendance_entries": [
                            {
                                "participant_id": participant.id,
                                "participant_name": participant.display_name,
                                "status": "absent",
                            }
                            for participant in participants
                        ],
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == session_date_type_id:
                    next_event = db.get(Event, template.next_event_id) if template.next_event_id else None
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "selected_date": next_event.event_date.isoformat() if next_event else None,
                        "session_label": next_event.title if next_event else "Naechste Sitzung",
                        "session_tag": next_event.tag if next_event else "next_session",
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == event_list_type_id:
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "event_only_from_protocol_date": bool((protocol_block.configuration_snapshot_json or {}).get("event_only_from_protocol_date", True)),
                        "event_gray_past": bool((protocol_block.configuration_snapshot_json or {}).get("event_gray_past", True)),
                        "event_allow_end_date": bool((protocol_block.configuration_snapshot_json or {}).get("event_allow_end_date", False)),
                    }
                    db.add(protocol_block)

                if block["element_type_id"] == todo_type_id:
                    open_todos = self._open_todos_for_template_block(
                        db,
                        tenant_id=tenant_id,
                        template_id=template.id,
                        template_element_id=template_element.id,
                        block_sort_index=block["sort_index"],
                        protocol_date=payload.protocol_date,
                        current_protocol_id=protocol.id,
                        repeat_source_type=repeat_source_type or None,
                        repeat_source_id=repeat_source_id,
                    )
                    next_sort_index = 0
                    for open_todo in open_todos:
                        db.add(
                            ProtocolTodo(
                                protocol_element_block_id=protocol_block.id,
                                sort_index=next_sort_index,
                                task=open_todo.task,
                                assigned_user_id=open_todo.assigned_user_id,
                                assigned_participant_id=open_todo.assigned_participant_id,
                                todo_status_id=open_todo.todo_status_id,
                                due_date=open_todo.due_date,
                                due_event_id=open_todo.due_event_id,
                                due_marker=open_todo.due_marker,
                                completed_at=open_todo.completed_at,
                                reference_link=open_todo.reference_link,
                                created_by=open_todo.created_by,
                            )
                        )
                        next_sort_index += 10

        db.commit()
        db.refresh(protocol)
        protocol = self.document_template_service.snapshot_template_for_protocol(db, protocol, selected_document_template_id)
        self.access_service.add_protocol_access_for_template(
            db,
            tenant_id=tenant_id,
            template_id=template.id,
            protocol_id=protocol.id,
        )
        db.commit()
        return int(protocol.id)

    def _maybe_auto_create_next_protocol(self, db: Session, protocol: Protocol) -> None:
        template = db.get(Template, protocol.template_id)
        if template is None or not bool(template.auto_create_next_protocol):
            return
        if template.next_event_id is None:
            return
        followup_template_id = template.id
        session_date_blocks = list(
            db.scalars(
                select(ProtocolElementBlock)
                .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
                .where(ProtocolElement.protocol_id == protocol.id)
                .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc())
            )
        )
        for block in session_date_blocks:
            config = block.configuration_snapshot_json or {}
            if config.get("block_kind") != "session_date":
                continue
            raw_followup_template_id = config.get("followup_template_id")
            if raw_followup_template_id is None:
                break
            try:
                candidate_template_id = int(raw_followup_template_id)
            except (TypeError, ValueError):
                break
            candidate_template = db.get(Template, candidate_template_id)
            if candidate_template is not None and candidate_template.tenant_id == protocol.tenant_id:
                followup_template_id = candidate_template.id
            break
        next_event = db.get(Event, template.next_event_id)
        if next_event is None or next_event.event_date is None:
            return
        if next_event.event_date <= protocol.protocol_date:
            return

        existing_protocol_id = db.scalar(
            select(Protocol.id)
            .where(
                Protocol.tenant_id == protocol.tenant_id,
                Protocol.template_id == followup_template_id,
                or_(
                    Protocol.event_id == next_event.id,
                    Protocol.protocol_date == next_event.event_date,
                ),
            )
            .limit(1)
        )
        if existing_protocol_id is not None:
            return

        self.create_from_template(
            db,
            ProtocolCreateFromTemplate(
                template_id=followup_template_id,
                protocol_date=next_event.event_date,
                event_id=next_event.id,
            ),
            tenant_id=protocol.tenant_id,
            created_by=protocol.created_by,
        )
        refreshed_template = db.get(Template, template.id)
        if refreshed_template is not None and protocol.event_id:
            refreshed_template.last_event_id = protocol.event_id
            db.add(refreshed_template)
            db.commit()

    def update_protocol(self, db: Session, protocol_id: int, payload: ProtocolUpdate):
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return None
        previous_status = protocol.status
        values = payload.model_dump(exclude_unset=True)
        document_template_id = values.pop("document_template_id", None) if "document_template_id" in values else None
        if not values:
            if "document_template_id" in payload.model_fields_set:
                return self.document_template_service.snapshot_template_for_protocol(db, protocol, document_template_id)
            return protocol
        updated = self.repository.update(db, protocol, values)
        if previous_status != "abgeschlossen" and updated.status == "abgeschlossen":
            self._maybe_auto_create_next_protocol(db, updated)
            updated = self.repository.get(db, protocol_id) or updated
        if "document_template_id" in payload.model_fields_set:
            return self.document_template_service.snapshot_template_for_protocol(db, updated, document_template_id)
        return updated

    def delete_protocol(self, db: Session, protocol_id: int) -> bool:
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return False
        self.repository.delete(db, protocol)
        return True
