from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceFine,
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
    ProtocolImage,
    ProtocolTodo,
    ProtocolText,
    RenderType,
    Template,
    TemplateElement,
    TemplateParticipant,
    TodoStatus,
)
from app.services.document_template_service import DocumentTemplateService
from app.services.access_service import AccessService
from app.services.block_behavior import resolve_block_behavior
from app.repositories.participant_repository import participant_eligible_on
from app.services import list_snapshot_service
from app.services.responsible_label_service import resolve_display_section_title, resolve_responsible_label
from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.protocol import NextSessionAttendanceEntry, NextSessionRead, ProtocolCreateFromTemplate, ProtocolUpdate


def _matrix_row_type(row: dict) -> str:
    """Resolves a matrix row's type across schema generations: new schema uses `row_type`
    directly; old schema used `embedded_element_type_id` (takes precedence when present) or
    fell back to `value_type`, defaulting to "text" if none is set."""
    if row.get("row_type"):
        return str(row["row_type"])
    if row.get("embedded_element_type_id"):
        return str(row["embedded_element_type_id"])
    return str(row.get("value_type") or "text")


def _matrix_row_config(row: dict) -> dict:
    """Resolves a matrix row's config across schema generations: new schema stores a
    `row_config` dict directly; old schema spread relevant keys (event_tag_filter,
    event_title_filter, use_column_title_as_tag, hide_past_events) onto the row itself,
    alongside an `embedded_configuration_json` dict."""
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


def _matrix_build_row_values(column: dict, rows: list[dict]) -> dict:
    """Builds a matrix column's per-row preset cell values: new schema stores explicit
    per-row overrides in `row_overrides`; rows without an override fall back to the row's
    own template_value/template_participant_id/template_participant_ids/template_event_id,
    picked based on the row's type."""
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


def _matrix_auto_cell_value(row: dict, col_value: dict) -> dict:
    """Maps a list entry column value to a matrix cell value based on the row's row_type."""
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
        skip: int = 0,
        limit: int = 100,
    ):
        protocol_ids = None
        if restrict_to_assigned and user_id is not None:
            protocol_ids = self.access_service.repository.list_protocol_ids(db, user_id=user_id, tenant_id=tenant_id)
        return self.repository.list(db, tenant_id=tenant_id, query=query, status=status, protocol_ids=protocol_ids, skip=skip, limit=limit)

    def get_protocol(self, db: Session, protocol_id: int):
        return self.repository.get(db, protocol_id)

    def get_protocol_or_404_not_frozen(self, db: Session, protocol_id: int | None):
        """Shared guard for every write path that touches a protocol's content (element
        blocks, config snapshots, text blocks, tracked-change accepts, todos, ...): 404s if
        the protocol is missing, 409s if it's already abgeschlossen (permanently frozen -
        the only routes allowed to still touch it past this point are the status-revert
        endpoint and internal service code, both of which call the repository directly
        instead of going through this guard)."""
        protocol = self.get_protocol(db, protocol_id) if protocol_id else None
        if protocol is None:
            raise HTTPException(status_code=404, detail="Protocol not found")
        if protocol.status == "abgeschlossen":
            raise HTTPException(status_code=409, detail="Protocol is already abgeschlossen")
        return protocol

    def _attendance_type_id(self, db: Session) -> int | None:
        return db.scalar(select(ElementType.id).where(ElementType.code == "attendance"))

    def get_next_session_attendance(self, db: Session, tenant_id: int) -> NextSessionRead:
        """The tenant's next open protocol plus its attendance list, if it has one - used by
        the dashboard's quick-excuse tile."""
        protocol = self.repository.next_open(db, tenant_id=tenant_id)
        if protocol is None:
            return NextSessionRead(protocol=None, attendance_block_id=None, entries=[])

        attendance_type_id = self._attendance_type_id(db)
        block = None
        if attendance_type_id is not None:
            block = db.scalar(
                select(ProtocolElementBlock)
                .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
                .where(
                    ProtocolElement.protocol_id == protocol.id,
                    ProtocolElementBlock.element_type_id == attendance_type_id,
                )
                .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc())
                .limit(1)
            )

        entries: list[NextSessionAttendanceEntry] = []
        if block is not None:
            for entry in (block.configuration_snapshot_json or {}).get("attendance_entries", []):
                if entry.get("participant_id") is None:
                    continue
                entries.append(
                    NextSessionAttendanceEntry(
                        participant_id=entry["participant_id"],
                        participant_name=entry.get("participant_name") or "",
                        status=entry.get("status") or "absent",
                    )
                )
            entries.sort(key=lambda e: e.participant_name.lower())

        return NextSessionRead(protocol=protocol, attendance_block_id=block.id if block else None, entries=entries)

    def set_attendance_excused(self, db: Session, protocol_id: int, participant_id: int, excused: bool) -> bool:
        """Toggles a participant between excused and unentschuldigt (absent) in every attendance
        block of this protocol. Marking someone excused also clears any pending fine for them
        there - mirrors the protocol editor's attendance behavior (excused never carries a fine).
        Toggling back to unentschuldigt does not recreate a fine; that still requires the
        protocol editor's attendance block, which knows the configured fine amounts."""
        attendance_type_id = self._attendance_type_id(db)
        if attendance_type_id is None:
            return False
        blocks = list(
            db.scalars(
                select(ProtocolElementBlock)
                .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
                .where(
                    ProtocolElement.protocol_id == protocol_id,
                    ProtocolElementBlock.element_type_id == attendance_type_id,
                )
            )
        )
        target_status = "excused" if excused else "absent"
        found = False
        for block in blocks:
            config = block.configuration_snapshot_json or {}
            changed = False
            new_entries = []
            for entry in config.get("attendance_entries", []):
                if entry.get("participant_id") == participant_id:
                    # Build a fresh dict rather than mutating in place: SQLAlchemy compares the
                    # new JSONB value against the old one to decide whether to emit an UPDATE,
                    # and an in-place mutation would make both sides look identical, so the
                    # change would silently be dropped.
                    new_entries.append({**entry, "status": target_status})
                    changed = True
                    found = True
                else:
                    new_entries.append(entry)
            if changed:
                block.configuration_snapshot_json = {**config, "attendance_entries": new_entries}
                db.add(block)
        if not found:
            return False

        if excused:
            pending_fine = db.scalar(
                select(AttendanceFine).where(
                    AttendanceFine.protocol_id == protocol_id,
                    AttendanceFine.participant_id == participant_id,
                    AttendanceFine.status == "pending",
                )
            )
            if pending_fine is not None:
                db.delete(pending_fine)
        db.commit()
        return True

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
        # Single query with conditional aggregation for per-template counts.
        row = db.execute(
            select(
                func.count(Protocol.id).label("overall"),
                func.count(Protocol.id).filter(
                    func.extract("year", Protocol.protocol_date) == protocol_date.year,
                ).label("yearly"),
                func.count(Protocol.id).filter(
                    func.extract("year", Protocol.protocol_date) == protocol_date.year,
                    func.extract("month", Protocol.protocol_date) == protocol_date.month,
                ).label("monthly"),
                func.count(Protocol.id).filter(
                    Protocol.protocol_date >= cycle_start,
                    Protocol.protocol_date <= cycle_end,
                ).label("cycle"),
            ).where(
                Protocol.tenant_id == tenant_id,
                Protocol.template_id == template_id,
            )
        ).one()
        # Cross-template cycle count: all protocols for this tenant within cycle bounds.
        cycle_all = db.scalar(
            select(func.count(Protocol.id)).where(
                Protocol.tenant_id == tenant_id,
                Protocol.protocol_date >= cycle_start,
                Protocol.protocol_date <= cycle_end,
            )
        ) or 0
        return {
            "n": row.overall + 1,
            "n_year": row.yearly + 1,
            "n_month": row.monthly + 1,
            "n_cycle": row.cycle + 1,
            "n_cycle_all": cycle_all + 1,
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
            "n_cycle_all",
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
            "{n_cycle_all}": str(counts["n_cycle_all"]),
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

    def preview_title(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_date: date,
        fallback: str | None = None,
    ) -> str:
        """Renders Template.title_pattern for a date that doesn't have a Protocol yet - used by
        the Word-Import queue to show a template-scheme name for a not-yet-committed document.
        Read-only preview: counts reflect protocols that exist right now, so the final title
        generated by create_from_template() may differ slightly if other queue items get
        committed for the same period first."""
        template = db.get(Template, template_id)
        if template is None:
            return fallback or protocol_date.strftime("%d.%m.%Y")
        from app.models import CycleConfig

        cycle_cfg = db.get(CycleConfig, template.cycle_config_id) if template.cycle_config_id else None
        counts = self._sequence_counts(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            protocol_date=protocol_date,
            reset_month=cycle_cfg.reset_month if cycle_cfg else 12,
            reset_day=cycle_cfg.reset_day if cycle_cfg else 31,
        )
        rendered = self._format_pattern(template.title_pattern, counts=counts, protocol_date=protocol_date)
        return rendered or fallback or protocol_date.strftime("%d.%m.%Y")

    def _responsible_participant_name(self, participant: Participant | None, *, mode: str, fallback_id: int | None = None) -> str:
        if participant is None:
            return f"Teilnehmer {fallback_id}" if fallback_id else ""
        if mode == "first_name":
            return (participant.first_name or "").strip() or participant.display_name
        if mode == "last_name":
            return (participant.last_name or "").strip() or participant.display_name
        return participant.display_name

    def _template_element_responsible_label(self, db: Session, configuration_json: dict | None) -> str:
        template_config = configuration_json or {}
        responsibility = template_config.get("responsibility")
        if not isinstance(responsibility, dict):
            return ""
        assignments = responsibility.get("assignments")
        if not isinstance(assignments, list):
            return ""
        mode = str(responsibility.get("name_display_mode") or "display_name")
        names: list[str] = []
        seen_ids: set[int] = set()
        for assignment in assignments:
            if not isinstance(assignment, dict):
                continue
            try:
                participant_id = int(assignment.get("participant_id") or 0)
            except (TypeError, ValueError):
                participant_id = 0
            if not participant_id or participant_id in seen_ids:
                continue
            seen_ids.add(participant_id)
            participant = db.get(Participant, participant_id)
            participant_name = self._responsible_participant_name(participant, mode=mode, fallback_id=participant_id)
            if participant_name:
                names.append(participant_name)
        return ", ".join(names)

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

    def _with_cycle_tokens(self, context: dict[str, object] | None, cycle_tokens: dict[str, str]) -> dict[str, object] | None:
        if not cycle_tokens:
            return context
        merged = dict(context) if context else {}
        merged["tokens"] = {**cycle_tokens, **(merged.get("tokens") or {})}
        return merged

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

    def _manually_hidden_event_ids(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        template_element_id: int | None,
        current_protocol_id: int,
    ) -> set[int]:
        """Return event IDs that were manually hidden in any previous protocol for this template element."""
        if template_element_id is None:
            return set()
        previous_protocol_ids = list(
            db.scalars(
                select(Protocol.id)
                .where(
                    Protocol.tenant_id == tenant_id,
                    Protocol.template_id == template_id,
                    Protocol.id != current_protocol_id,
                )
            )
        )
        if not previous_protocol_ids:
            return set()
        hidden_ids: set[int] = set()
        rows = db.scalars(
            select(ProtocolElementBlock.configuration_snapshot_json)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(
                ProtocolElement.protocol_id.in_(previous_protocol_ids),
                ProtocolElement.template_element_id == template_element_id,
            )
        )
        for config in rows:
            if not isinstance(config, dict):
                continue
            if str(config.get("repeat_source_type") or "") != "event":
                continue
            if not config.get("manually_hidden"):
                continue
            source_id = config.get("repeat_source_id")
            if source_id is None:
                continue
            try:
                hidden_ids.add(int(source_id))
            except (TypeError, ValueError):
                continue
        return hidden_ids

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
        tag_filters = [t.strip() for t in str(repeat_config.get("event_tag_filter") or "").lower().split(",") if t.strip()]
        title_filter = str(repeat_config.get("event_title_filter") or "").strip().lower()
        description_filter = str(repeat_config.get("event_description_filter") or "").strip().lower()
        date_mode = str(repeat_config.get("event_date_mode") or "relative_window")
        window_start_days = int(repeat_config.get("event_window_start_days") or 0)
        window_end_days = int(repeat_config.get("event_window_end_days") or 14)
        include_unlisted_past = bool(repeat_config.get("event_include_unlisted_past", False))
        only_before_protocol_date = bool(repeat_config.get("event_only_before_protocol_date", False))
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
        manually_hidden_ids = self._manually_hidden_event_ids(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            template_element_id=template_element_id,
            current_protocol_id=current_protocol_id,
        )
        contexts: list[dict[str, object]] = []
        for event in db.scalars(statement):
            event_end_date = event.event_end_date or event.event_date
            event_tag_lower = (event.tag or "").lower()
            if tag_filters and not any(t in event_tag_lower for t in tag_filters):
                continue
            if title_filter and title_filter not in (event.title or "").lower():
                continue
            if description_filter and description_filter not in (event.description or "").lower():
                continue
            if event.id in manually_hidden_ids:
                continue
            if only_before_protocol_date and event.event_date > protocol_date:
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

    def _previous_protocol_element(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_element_id: int | None,
        protocol_date: date,
        current_protocol_id: int,
        status: str | None = None,
    ):
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
        )
        if status is not None:
            query = query.where(Protocol.status == status)
        query = query.order_by(Protocol.protocol_date.desc(), Protocol.id.desc()).limit(1)
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
            images = list(
                db.scalars(
                    select(ProtocolImage)
                    .where(ProtocolImage.protocol_element_block_id == block.id)
                    .order_by(ProtocolImage.sort_index.asc(), ProtocolImage.id.asc())
                )
            )
            payloads[self._payload_key(
                source_sort_index=source_sort_index,
                repeat_source_type=repeat_source_type,
                repeat_source_id=repeat_source_id,
            )] = {
                "text_content": row.content,
                "todos": todos,
                "images": images,
            }
        return payloads

    def _previous_completed_block_list_snapshots(self, db: Session, *, protocol_element_id: int) -> dict[tuple[int, str, int | None], dict]:
        """Same block-matching shape as _previous_block_payloads, but for the
        frozen list_snapshot data of the last abgeschlossen protocol - used as
        the track-changes baseline for newly-created list/form blocks (see
        create_from_template's form_type_id branch), so a fresh protocol shows
        changes since the last completed meeting instead of since its own
        creation time."""
        rows = db.execute(
            select(ProtocolElementBlock.configuration_snapshot_json)
            .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
        ).scalars()
        payloads: dict[tuple[int, str, int | None], dict] = {}
        for config in rows:
            if not isinstance(config, dict):
                continue
            source_sort_index = config.get("source_sort_index")
            if source_sort_index is None:
                continue
            repeat_source_type = str(config.get("repeat_source_type") or "") or None
            repeat_source_id_raw = config.get("repeat_source_id")
            try:
                repeat_source_id = int(repeat_source_id_raw) if repeat_source_id_raw is not None else None
            except (TypeError, ValueError):
                repeat_source_id = None
            payloads[self._payload_key(
                source_sort_index=int(source_sort_index),
                repeat_source_type=repeat_source_type,
                repeat_source_id=repeat_source_id,
            )] = {
                "list_snapshot": config.get("list_snapshot"),
                "rows": config.get("rows") if isinstance(config.get("rows"), list) else [],
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

    def _transform_field_row(self, row: dict, *, repeat_context: dict | None) -> dict:
        """Transforms a single raw ElementDefinition field-row (a "form"-block row, list or
        matrix) into the runtime row schema stored on ProtocolElementBlock
        configuration_snapshot_json: text_value/participant_id/participant_ids/event_id/
        linked_list_*, resolving the row_type vs. (legacy) value_type fallback. Shared by
        create_from_template's form_type_id branch and _build_event_repeat_form_snapshot
        (event-repeat "add block" flow) - both need byte-identical behavior since the
        latter is just a smaller, later invocation of the same transform for one freshly
        added block."""
        row_value_type = row.get("row_type") or row.get("value_type") or "text"
        row_config = row.get("row_config") or {}
        return {
            "id": row.get("id"),
            "label": (
                self._render_context_text(row.get("label") or "", repeat_context) or ""
                if row_value_type == "list_entry"
                else self._render_context_text(row.get("label") or row.get("title") or "Feld", repeat_context) or "Feld"
            ),
            "value_type": row_value_type,
            "sort_index": row.get("sort_index"),
            "text_value": self._render_context_text(row.get("template_value") or "", repeat_context) or "" if row_value_type == "text" else "",
            "participant_id": self._coerce_optional_int(row.get("template_participant_id")) if row_value_type == "participant" else None,
            "participant_ids": self._coerce_int_list(row.get("template_participant_ids")) if row_value_type == "participants" else [],
            "event_id": self._coerce_optional_int(row.get("template_event_id")) if row_value_type == "event" else None,
            "linked_list_id": self._coerce_optional_int(row_config.get("linked_list_id")) if row_value_type == "list_entry" else None,
            "linked_list_entry_id": self._coerce_optional_int(row_config.get("linked_list_entry_id")) if row_value_type == "list_entry" else None,
            "list_fixed_column": row_config.get("list_fixed_column") if row_value_type == "list_entry" else None,
        }

    def create_from_template(self, db: Session, payload: ProtocolCreateFromTemplate, *, tenant_id: int, created_by: int | None) -> int:
        template = db.get(Template, payload.template_id)
        if template is None:
            raise ValueError("Template not found")
        if template.tenant_id != tenant_id:
            raise ValueError("Template does not belong to current tenant")
        if payload.event_id is not None:
            # event_id is client-supplied - without this check a writer could link a
            # freshly created protocol to another tenant's Event.
            linked_event = db.get(Event, payload.event_id)
            if linked_event is None or linked_event.tenant_id != tenant_id:
                raise ValueError("Event does not belong to current tenant")

        selected_document_template_id = template.document_template_id
        document_template = db.get(DocumentTemplate, selected_document_template_id) if selected_document_template_id else None
        from app.models import CycleConfig
        cycle_cfg = db.get(CycleConfig, template.cycle_config_id) if template.cycle_config_id else None
        counts = self._sequence_counts(
            db,
            tenant_id=tenant_id,
            template_id=template.id,
            protocol_date=payload.protocol_date,
            reset_month=cycle_cfg.reset_month if cycle_cfg else 12,
            reset_day=cycle_cfg.reset_day if cycle_cfg else 31,
        )
        cycle_tokens: dict[str, str] = {}
        if cycle_cfg is not None:
            cycle_tokens = {
                "{cycle_name}": cycle_cfg.name,
                "{cycle_year_start}": str(counts["cycle_year_start"]),
                "{cycle_year_end}": str(counts["cycle_year_end"]),
            }
        if payload.protocol_number:
            protocol_number = payload.protocol_number
        else:
            protocol_number = None
            for bump in range(100):
                bumped = {**counts, "n": counts["n"] + bump, "n_year": counts["n_year"] + bump, "n_month": counts["n_month"] + bump, "n_cycle": counts["n_cycle"] + bump, "n_cycle_all": counts["n_cycle_all"] + bump}
                candidate = self._format_pattern(template.protocol_number_pattern, counts=bumped, protocol_date=payload.protocol_date)
                if not candidate:
                    break
                exists = db.scalar(select(Protocol.id).where(Protocol.tenant_id == tenant_id, Protocol.protocol_number == candidate))
                if not exists:
                    protocol_number = candidate
                    counts = bumped
                    break
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
        image_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "image"))

        template_rows = db.execute(
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template.id)
            .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
        ).all()

        visible_element_index = 0
        for template_element, definition in template_rows:
            legacy_repeat_config = template_element.configuration_json or {}
            responsible_label = self._template_element_responsible_label(db, legacy_repeat_config)
            element_title = self._render_context_text(definition.title, {"tokens": cycle_tokens}) if cycle_tokens else definition.title
            section_title = f"{element_title} ({responsible_label})" if responsible_label else element_title
            responsibility_config = legacy_repeat_config.get("responsibility")
            responsibility_config = responsibility_config if isinstance(responsibility_config, dict) else {}
            responsible_assignments = responsibility_config.get("assignments")
            responsible_assignments = responsible_assignments if isinstance(responsible_assignments, list) else None
            responsible_name_display_mode = str(responsibility_config.get("name_display_mode") or "display_name")
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
                    generated_blocks.append((block, self._with_cycle_tokens(repeat_context, cycle_tokens), next_block_sort_index))
                    next_block_sort_index += 10
            show_when_empty = bool((definition.configuration_json or {}).get("show_when_empty", False))
            if not generated_blocks and not show_when_empty:
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
            last_completed_element = self._previous_protocol_element(
                db,
                tenant_id=tenant_id,
                template_element_id=template_element.id,
                protocol_date=payload.protocol_date,
                current_protocol_id=protocol.id,
                status="abgeschlossen",
            )
            last_completed_list_snapshots = (
                self._previous_completed_block_list_snapshots(db, protocol_element_id=last_completed_element.id)
                if last_completed_element is not None
                else {}
            )
            protocol_element = ProtocolElement(
                protocol_id=protocol.id,
                template_element_id=template_element.id,
                sort_index=visible_element_index * 10,
                section_name_snapshot=section_title,
                element_title_snapshot=element_title,
                responsible_assignments_snapshot=responsible_assignments,
                responsible_name_display_mode=responsible_name_display_mode,
                section_order_snapshot=visible_element_index * 10,
                is_required_snapshot=False,
                is_visible_snapshot=True,
                export_visible_snapshot=True,
            )
            db.add(protocol_element)
            db.flush()

            for block, repeat_context, resolved_sort_index in generated_blocks:
                block_config = dict(block.get("configuration_json") or {})
                behavior = resolve_block_behavior(template_element.configuration_json, block)
                carry_from_last_protocol = bool(behavior["copy_from_last_protocol"])
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
                last_completed_payload = last_completed_list_snapshots.get(
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
                    is_editable_snapshot=behavior["is_editable"],
                    allows_multiple_values_snapshot=block.get("allows_multiple_values", False),
                    sort_index=resolved_sort_index,
                    render_order=resolved_sort_index,
                    is_required_snapshot=False,
                    is_visible_snapshot=behavior["is_visible"],
                    export_visible_snapshot=behavior["export_visible"],
                    latex_template_snapshot=block.get("latex_template"),
                    configuration_snapshot_json={
                        **block_config,
                        "title_as_subtitle": behavior["title_as_subtitle"],
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
                elif block["element_type_id"] == image_type_id and carry_from_last_protocol:
                    for prev_img in previous_payload.get("images", []):
                        db.add(ProtocolImage(
                            protocol_element_block_id=protocol_block.id,
                            stored_file_id=prev_img.stored_file_id,
                            sort_index=prev_img.sort_index,
                            title=prev_img.title,
                            caption=prev_img.caption,
                        ))
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
                        else [self._transform_field_row(row, repeat_context=repeat_context) for row in _form_raw_rows]
                    )
                    _last_completed_rows = last_completed_payload.get("rows") or []
                    _last_completed_rows_by_entry = {
                        row["linked_list_entry_id"]: row.get("list_snapshot")
                        for row in _last_completed_rows
                        if isinstance(row, dict) and row.get("linked_list_entry_id") is not None
                    }
                    for _field_row in field_rows:
                        if _field_row.get("linked_list_id") and _field_row.get("linked_list_entry_id"):
                            _live_row_snapshot = list_snapshot_service.compute_row_list_snapshot(
                                db, _field_row["linked_list_id"], _field_row["linked_list_entry_id"]
                            )
                            _field_row["list_snapshot"] = list_snapshot_service.tag_initial_row_snapshot(
                                _live_row_snapshot,
                                _last_completed_rows_by_entry.get(_field_row["linked_list_entry_id"]),
                                # Only tag against a real prior baseline: with no last-completed
                                # protocol at all (the very first protocol for this template),
                                # there's nothing to have changed relative to - see
                                # tag_initial_list_entries call below for the whole-list case.
                                track_changes_active=protocol.track_changes_enabled and last_completed_element is not None,
                            )
                    _whole_list_snapshot = (
                        list_snapshot_service.compute_whole_list_snapshot(db, linked_list_id) if linked_list_id else None
                    )
                    if _whole_list_snapshot is not None:
                        _last_completed_whole = last_completed_payload.get("list_snapshot")
                        _last_completed_entries = (
                            _last_completed_whole.get("entries")
                            if isinstance(_last_completed_whole, dict)
                            else None
                        )
                        _whole_list_snapshot["entries"] = list_snapshot_service.tag_initial_list_entries(
                            _whole_list_snapshot["entries"],
                            _last_completed_entries,
                            # Gate on an actual recorded snapshot existing for THIS block, not
                            # just on a last-completed protocol existing: a protocol completed
                            # before the list_snapshot feature shipped has no 'list_snapshot' on
                            # its blocks at all, which looks identical to "never captured" - if
                            # we tagged against that, every entry would come back "added" against
                            # a baseline that was simply never recorded, not one that was empty.
                            track_changes_active=protocol.track_changes_enabled and _last_completed_whole is not None,
                        )
                    protocol_block.configuration_snapshot_json = {
                        **(protocol_block.configuration_snapshot_json or {}),
                        "linked_list_id": linked_list_id,
                        "rows": field_rows,
                        **({"list_snapshot": _whole_list_snapshot} if _whole_list_snapshot is not None else {}),
                    }
                    db.add(protocol_block)
                elif block["element_type_id"] == matrix_type_id:
                    _matrix_cfg = protocol_block.configuration_snapshot_json or {}
                    # Backward compat: support both old field_rows and new rows
                    _raw_rows = _matrix_cfg.get("rows") or _matrix_cfg.get("field_rows") or []
                    # Backward compat: support both old matrix_columns and new columns
                    _raw_columns = _matrix_cfg.get("columns") or _matrix_cfg.get("matrix_columns") or []

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
                                    _row_values[_row_id] = _matrix_auto_cell_value(_row, _col1)
                                elif _src_field == "column_two":
                                    _row_values[_row_id] = _matrix_auto_cell_value(_row, _col2)
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
                                "row_values": _matrix_build_row_values(column, matrix_rows),
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
                            .where(
                                TemplateParticipant.template_id == template.id,
                                TemplateParticipant.exclude_from_attendance.is_(False),
                                participant_eligible_on(payload.protocol_date),
                            )
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

    def _freeze_responsible_titles(self, db: Session, protocol_id: int, *, commit: bool = True) -> None:
        """Called right when a protocol transitions to abgeschlossen: resolves each
        list-linked responsible name one last time and bakes it into section_name_snapshot
        for good, so it keeps showing what the user last saw instead of reverting to the
        stale value from protocol-creation time."""
        elements = db.scalars(
            select(ProtocolElement).where(
                ProtocolElement.protocol_id == protocol_id,
                ProtocolElement.responsible_assignments_snapshot.is_not(None),
            )
        ).all()
        changed = False
        for element in elements:
            if not element.element_title_snapshot:
                continue
            label = resolve_responsible_label(
                db, element.responsible_assignments_snapshot, element.responsible_name_display_mode, live=True
            )
            element.section_name_snapshot = f"{element.element_title_snapshot} ({label})" if label else element.element_title_snapshot
            db.add(element)
            changed = True
        if changed:
            if commit:
                db.commit()
            else:
                db.flush()

    def _clear_tracked_changes(self, db: Session, protocol_id: int, *, commit: bool = True) -> None:
        """Called once at vorbereitet -> durchgefuehrt (mirrors _freeze_responsible_titles):
        this is the point where every track-changes mark ever made on this protocol -
        regardless of the toggle's on/off history - permanently disappears. Todos created
        during tracking and then deleted before this point never had a pending_delete row
        (they hard-delete immediately, see ProtocolTodoService.delete_todo); anything still
        pending_delete here is a pre-existing todo that really gets removed only now."""
        todos = db.scalars(
            select(ProtocolTodo)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(ProtocolElement.protocol_id == protocol_id)
        ).all()
        for todo in todos:
            if todo.pending_delete:
                db.delete(todo)
            elif todo.tracked_change is not None or todo.tracked_change_before_json is not None:
                todo.tracked_change = None
                todo.tracked_change_before_json = None
                db.add(todo)

        texts = db.scalars(
            select(ProtocolText)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolText.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(ProtocolElement.protocol_id == protocol_id)
        ).all()
        for protocol_text in texts:
            if protocol_text.tracked_dirty or protocol_text.tracked_baseline_content is not None:
                protocol_text.tracked_dirty = False
                protocol_text.tracked_baseline_content = None
                db.add(protocol_text)

        if commit:
            db.commit()
        else:
            db.flush()
        list_snapshot_service.clear_tracked_changes_for_protocol(db, protocol_id, commit=commit)

    # Full lifecycle in order. Verified against the DB's own
    # ck_protocol_status CHECK constraint (see models/entities.py) - these are the only
    # four values a protocol.status can ever hold.
    _STATUS_ORDER = ["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"]

    def _validate_status_transition(self, previous_status: str, new_status: str) -> None:
        """Rejects anything that isn't a real state-machine move. Design decision (see audit
        finding "Statusübergänge sind keine validierte Zustandsmaschine"): forward jumps of
        more than one stage ARE legitimate here - word_import_service.commit() deliberately
        creates a protocol and takes it straight from 'geplant' to 'abgeschlossen' for
        historical imports, and the frontend's own step-by-step buttons are just the single-
        step special case of the same forward move. So forward skips are allowed, but
        _run_status_transition_hooks below replays every intermediate stage's hook (in
        particular _clear_tracked_changes) so a skip can no longer leave stale tracked-change
        markers behind the way the un-validated string field used to. Backward moves are only
        ever issued by the single-step /protocols/{id}/revert-status endpoint (see
        api/routes/protocols.py _PREVIOUS_STATUS) - no caller anywhere needs to jump back more
        than one stage, so that direction is rejected with 409 instead of silently allowed."""
        if previous_status not in self._STATUS_ORDER or new_status not in self._STATUS_ORDER:
            raise HTTPException(status_code=400, detail=f"Unknown protocol status '{new_status}'")
        prev_idx = self._STATUS_ORDER.index(previous_status)
        new_idx = self._STATUS_ORDER.index(new_status)
        if new_idx < prev_idx - 1:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot move protocol status from '{previous_status}' back to '{new_status}' in one step",
            )

    def _run_status_transition_hooks(self, db: Session, protocol_id: int, previous_status: str, updated):
        """Replays every stage-change hook between previous_status and updated.status, in
        order - so a validated forward skip (e.g. geplant -> abgeschlossen for Word-Import)
        still fires every hook a step-by-step transition would have fired instead of silently
        skipping them. No-op for backward moves (single-step revert only reuses already-frozen
        data, nothing to (re-)run).

        The status change itself (already applied via repository.update(..., commit=False))
        and every hook below run uncommitted until the single db.commit() at the end, so a
        failure mid-sequence rolls back the whole transition instead of leaving the protocol
        with a new status but an incomplete freeze. _maybe_auto_create_next_protocol is a
        best-effort follow-up outside that atomic unit - its own failure shouldn't undo an
        already-successful, already-committed status transition."""
        prev_idx = self._STATUS_ORDER.index(previous_status)
        new_idx = self._STATUS_ORDER.index(updated.status)
        crossed_into_abgeschlossen = False
        if new_idx > prev_idx:
            for idx in range(prev_idx, new_idx):
                stage_from, stage_to = self._STATUS_ORDER[idx], self._STATUS_ORDER[idx + 1]
                if stage_from == "vorbereitet" and stage_to == "durchgeführt":
                    self._clear_tracked_changes(db, protocol_id, commit=False)
                if stage_to == "abgeschlossen":
                    self._freeze_responsible_titles(db, protocol_id, commit=False)
                    list_snapshot_service.freeze_list_snapshots_for_protocol(db, protocol_id, commit=False)
                    crossed_into_abgeschlossen = True
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        if crossed_into_abgeschlossen:
            self._maybe_auto_create_next_protocol(db, updated)
        return self.repository.get(db, protocol_id) or updated

    def update_protocol(self, db: Session, protocol_id: int, payload: ProtocolUpdate):
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return None
        previous_status = protocol.status
        values = payload.model_dump(exclude_unset=True)
        document_template_id = values.pop("document_template_id", None) if "document_template_id" in values else None
        if values.get("event_id") is not None:
            # event_id is client-supplied - without this check a writer could re-link an
            # existing protocol to another tenant's Event (see create_from_template above).
            linked_event = db.get(Event, values["event_id"])
            if linked_event is None or linked_event.tenant_id != protocol.tenant_id:
                raise ValueError("Event does not belong to current tenant")
        new_status = values.get("status")
        if new_status is not None and new_status != previous_status:
            self._validate_status_transition(previous_status, new_status)
        if not values:
            if "document_template_id" in payload.model_fields_set:
                return self.document_template_service.snapshot_template_for_protocol(db, protocol, document_template_id)
            return protocol
        has_status_transition = new_status is not None and new_status != previous_status
        updated = self.repository.update(db, protocol, values, commit=not has_status_transition)
        if has_status_transition:
            updated = self._run_status_transition_hooks(db, protocol_id, previous_status, updated)
        if "document_template_id" in payload.model_fields_set:
            return self.document_template_service.snapshot_template_for_protocol(db, updated, document_template_id)
        return updated

    def delete_protocol(self, db: Session, protocol_id: int) -> bool:
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return False
        self.get_protocol_or_404_not_frozen(db, protocol_id)
        self.repository.delete(db, protocol)
        return True

    def _build_event_repeat_form_snapshot(self, db: Session, *, raw_config: dict, repeat_context: dict) -> dict:
        """Same rows/value_type transform as create_from_template's form_type_id branch
        (raw ElementDefinition row schema -> runtime schema with text_value/participant_id/
        participant_ids/etc.), for a freshly-added single event-repeat "form" block. There
        is no "last completed protocol" to diff track-changes against here (this block is
        brand new to this protocol), so track_changes_active is always False - equivalent
        to leaving each row/entry untagged."""
        linked_list_id = self._coerce_optional_int(raw_config.get("linked_list_id"))
        raw_rows = raw_config.get("rows") or raw_config.get("field_rows") or []
        field_rows = (
            []
            if linked_list_id
            else [self._transform_field_row(row, repeat_context=repeat_context) for row in raw_rows]
        )
        for field_row in field_rows:
            if field_row.get("linked_list_id") and field_row.get("linked_list_entry_id"):
                live_row_snapshot = list_snapshot_service.compute_row_list_snapshot(
                    db, field_row["linked_list_id"], field_row["linked_list_entry_id"]
                )
                field_row["list_snapshot"] = list_snapshot_service.tag_initial_row_snapshot(
                    live_row_snapshot, None, track_changes_active=False
                )
        whole_list_snapshot = list_snapshot_service.compute_whole_list_snapshot(db, linked_list_id) if linked_list_id else None
        if whole_list_snapshot is not None:
            whole_list_snapshot["entries"] = list_snapshot_service.tag_initial_list_entries(
                whole_list_snapshot["entries"], None, track_changes_active=False
            )
        return {
            "linked_list_id": linked_list_id,
            "rows": field_rows,
            **({"list_snapshot": whole_list_snapshot} if whole_list_snapshot is not None else {}),
        }

    def add_event_block_to_element(
        self,
        db: Session,
        *,
        protocol_element_id: int,
        event_id: int,
        tenant_id: int,
        block_sort_index: int | None = None,
    ) -> ProtocolElementBlock:
        """Manually add an auto-generated event block to an existing protocol element."""
        protocol_element = db.get(ProtocolElement, protocol_element_id)
        if protocol_element is None:
            raise ValueError("Protocol element not found")

        event = db.get(Event, event_id)
        if event is None or event.tenant_id != tenant_id:
            # event_id is client-supplied - without this check a writer in one tenant could
            # embed another tenant's Event title/date/description into their own protocol.
            raise ValueError("Event not found")

        # Load element definition from the template element
        if protocol_element.template_element_id is None:
            raise ValueError("Protocol element has no template element")

        template_element = db.get(TemplateElement, protocol_element.template_element_id)
        if template_element is None:
            raise ValueError("Template element not found")

        definition = db.get(ElementDefinition, template_element.element_definition_id)
        if definition is None:
            raise ValueError("Element definition not found")

        # Find the block template with repeat_source: "event"
        legacy_repeat_config = template_element.configuration_json or {}
        definition_blocks = sorted(
            (definition.configuration_json or {}).get("blocks", []),
            key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0)),
        )

        event_block_template = None
        for block in definition_blocks:
            block_config = dict(block.get("configuration_json") or {})
            effective = dict(block_config)
            if not block_config.get("repeat_source") and legacy_repeat_config.get("repeat_source"):
                effective = {**legacy_repeat_config, **block_config}
            if str(effective.get("repeat_source") or "") != "event":
                continue
            if block_sort_index is None:
                # No specific target requested (e.g. the manual "add event block" UI
                # action) - keep the old behavior of using the first event-repeat block
                # template found on this element.
                event_block_template = block
                break
            if block.get("sort_index") == block_sort_index:
                event_block_template = block
                break

        if event_block_template is None:
            raise ValueError("No event repeat block template found for this element")

        # Build event context (same as _event_repeat_contexts output)
        event_end_date = event.event_end_date or event.event_date
        date_range = (
            event.event_date.strftime("%d.%m.%Y")
            if event_end_date == event.event_date
            else f"{event.event_date.strftime('%d.%m.%Y')} - {event_end_date.strftime('%d.%m.%Y')}"
        )
        repeat_context: dict[str, object] = {
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

        # Determine next sort index
        max_sort = db.scalar(
            select(func.max(ProtocolElementBlock.sort_index))
            .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
        ) or 0
        next_sort_index = int(max_sort) + 10

        block_config = dict(event_block_template.get("configuration_json") or {})
        behavior = resolve_block_behavior(template_element.configuration_json, event_block_template)

        text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "text"))
        static_text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "static_text"))
        form_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "form"))

        rendered_default_content = self._render_context_text(event_block_template.get("default_content"), repeat_context) or ""
        form_snapshot = (
            self._build_event_repeat_form_snapshot(db, raw_config=block_config, repeat_context=repeat_context)
            if event_block_template["element_type_id"] == form_type_id
            else {}
        )

        protocol_block = ProtocolElementBlock(
            protocol_element_id=protocol_element_id,
            template_element_block_id=None,
            element_definition_id=definition.id,
            element_type_id=event_block_template["element_type_id"],
            render_type_id=event_block_template["render_type_id"],
            title_snapshot=self._render_context_text(event_block_template["title"], repeat_context) or event_block_template["title"],
            display_title_snapshot=self._render_context_text(event_block_template.get("title"), repeat_context),
            description_snapshot=self._render_context_text(event_block_template.get("description"), repeat_context),
            block_title_snapshot=self._render_context_text(event_block_template.get("block_title"), repeat_context),
            is_editable_snapshot=behavior["is_editable"],
            allows_multiple_values_snapshot=event_block_template.get("allows_multiple_values", False),
            sort_index=next_sort_index,
            render_order=next_sort_index,
            is_required_snapshot=False,
            is_visible_snapshot=behavior["is_visible"],
            export_visible_snapshot=behavior["export_visible"],
            latex_template_snapshot=event_block_template.get("latex_template"),
            configuration_snapshot_json={
                **block_config,
                "title_as_subtitle": behavior["title_as_subtitle"],
                "default_content": rendered_default_content,
                "copy_from_last_protocol": bool(behavior["copy_from_last_protocol"]),
                "left_column_heading": block_config.get("left_column_heading") or legacy_repeat_config.get("left_column_heading"),
                "value_column_heading": block_config.get("value_column_heading") or legacy_repeat_config.get("value_column_heading"),
                "repeat_context": (repeat_context.get("tokens") or {}),
                "source_sort_index": event_block_template["sort_index"],
                "repeat_source_type": "event",
                "repeat_source_id": event.id,
                "repeat_source_label": event.title or "",
                **form_snapshot,
            },
        )
        db.add(protocol_block)
        db.flush()

        if event_block_template["element_type_id"] in (text_type_id, static_text_type_id):
            db.add(ProtocolText(
                protocol_element_block_id=protocol_block.id,
                content=rendered_default_content,
            ))

        db.commit()
        db.refresh(protocol_block)
        return protocol_block

    # ── Session notes / quick-todos ───────────────────────────────────────────

    _SESSION_ELEMENT_NAME = "Sitzungsnotizen"
    _SESSION_ELEMENT_SORT = 9990

    def _get_or_create_session_element(self, db: Session, *, protocol_id: int) -> ProtocolElement:
        """Find or create the special 'Sitzungsnotizen' protocol element."""
        existing = db.scalar(
            select(ProtocolElement).where(
                ProtocolElement.protocol_id == protocol_id,
                ProtocolElement.section_name_snapshot == self._SESSION_ELEMENT_NAME,
            )
        )
        if existing is not None:
            return existing
        element = ProtocolElement(
            protocol_id=protocol_id,
            template_element_id=None,
            sort_index=self._SESSION_ELEMENT_SORT,
            section_name_snapshot=self._SESSION_ELEMENT_NAME,
            section_order_snapshot=self._SESSION_ELEMENT_SORT,
            is_required_snapshot=False,
            is_visible_snapshot=True,
            export_visible_snapshot=True,
        )
        db.add(element)
        db.flush()
        return element

    def _get_or_create_session_block(
        self,
        db: Session,
        *,
        session_element: ProtocolElement,
        tag: str,
    ) -> ProtocolElementBlock:
        """Find or create a todo block inside the session element for the given tag."""
        tag_lower = tag.strip().lower()
        existing = db.scalar(
            select(ProtocolElementBlock).where(
                ProtocolElementBlock.protocol_element_id == session_element.id,
                ProtocolElementBlock.block_title_snapshot == tag,
            )
        )
        if existing is not None:
            return existing

        todo_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "todo"))
        render_type_id = db.scalar(select(RenderType.id).where(RenderType.code == "todo_list"))
        if not todo_type_id or not render_type_id:
            raise ValueError("Required element/render types not found")

        # Place new blocks after existing ones
        max_sort = db.scalar(
            select(func.max(ProtocolElementBlock.sort_index))
            .where(ProtocolElementBlock.protocol_element_id == session_element.id)
        ) or 0
        sort_index = int(max_sort) + 10

        block = ProtocolElementBlock(
            protocol_element_id=session_element.id,
            template_element_block_id=None,
            element_definition_id=None,
            element_type_id=todo_type_id,
            render_type_id=render_type_id,
            title_snapshot=tag,
            display_title_snapshot=tag,
            block_title_snapshot=tag,
            is_editable_snapshot=True,
            allows_multiple_values_snapshot=True,
            sort_index=sort_index,
            render_order=sort_index,
            is_required_snapshot=False,
            is_visible_snapshot=True,
            export_visible_snapshot=True,
            configuration_snapshot_json={
                "quick_todos": True,
                "quick_todo_tag": tag_lower,
            },
        )
        db.add(block)
        db.flush()
        return block

    def create_quick_todo(
        self,
        db: Session,
        *,
        protocol_id: int,
        task: str,
        tag: str,
        created_by: int | None,
    ) -> tuple[ProtocolElementBlock, ProtocolTodo]:
        """Create a quick todo in the session element, auto-creating the element+block if needed."""
        session_element = self._get_or_create_session_element(db, protocol_id=protocol_id)
        session_block = self._get_or_create_session_block(db, session_element=session_element, tag=tag)
        tag_lower = tag.strip().lower()
        sort_index = int(
            db.scalar(
                select(func.count(ProtocolTodo.id))
                .where(ProtocolTodo.protocol_element_block_id == session_block.id)
            ) or 0
        ) * 10
        todo = ProtocolTodo(
            protocol_element_block_id=session_block.id,
            sort_index=sort_index,
            task=task,
            todo_status_id=1,
            tags=[tag_lower],
            created_by=created_by,
        )
        db.add(todo)
        db.commit()
        db.refresh(todo)
        db.refresh(session_block)
        return session_block, todo
