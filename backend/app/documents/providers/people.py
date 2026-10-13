"""Personen: Anwesenheit einer Sitzung, Anwesenheitsmatrix eines Zeitraums, Mitgliederliste,
Präsenzliste zum Ausdrucken, Ein- und Austritte.

Mitgliederdaten (Namen, E-Mail, Rollen) sind wie in ``GET /api/participants`` nur für
schreibberechtigte Rollen (Katalog: access="writer"). Anwesenheiten aus Protokollen folgen dem
Protokoll-Leserecht."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from app.documents.catalog import (
    AttendanceMatrixParams,
    AttendanceSheetParams,
    BlockSpec,
    EntryExitParams,
    MemberListParams,
    PeriodParams,
    ProtocolRefParams,
)
from app.documents.context import BuildContext, DocumentNotFoundError, format_date
from app.documents.model import (
    AttendanceBlock,
    AttendanceEntry,
    AttendanceMatrixBlock,
    AttendanceSheetBlock,
    Cell,
    EntryExitBlock,
    EntryExitItem,
    MemberListBlock,
    TableData,
    TableGroup,
    TableRow,
)
from app.documents.providers.common import col, sort_key, spec_fields, text_cell
from app.models import ElementType, Participant, Protocol, ProtocolElement, ProtocolElementBlock, Role, Template, TemplateParticipant

ATTENDANCE_STATUSES = ("present", "late", "excused", "absent")


def resolve_period(ctx: BuildContext, params: PeriodParams) -> tuple[date, date] | None:
    """Zeitraum aus Zyklus (relativ zu heute, wie die Statistik) oder festen Daten."""
    from app.services.statistics_common import chart_cycle_bounds

    if params.cycle_config_id is not None:
        try:
            bounds = chart_cycle_bounds(ctx.db, ctx.tenant_id, params.cycle_config_id, params.cycle_offset)
        except ValueError as exc:
            raise DocumentNotFoundError("CycleConfig") from exc
        if bounds is not None:
            return bounds
    if params.date_from is not None or params.date_to is not None:
        return (params.date_from or date.min, params.date_to or date.max)
    return None


def attendance_entries(ctx: BuildContext, config: dict) -> list[AttendanceEntry]:
    entries: list[AttendanceEntry] = []
    for entry in (config or {}).get("attendance_entries") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("participant_name")
        if not name and entry.get("participant_id"):
            participant = ctx.entity_by_ref(Participant, entry["participant_id"])
            name = participant.display_name if participant else None
        status = entry.get("status")
        entries.append(AttendanceEntry(name=str(name or "–"), status=status if status in ATTENDANCE_STATUSES else None))
    return entries


def _attendance_type_id(ctx: BuildContext) -> int | None:
    return ctx.db.scalar(select(ElementType.id).where(ElementType.code == "attendance"))


def protocol_attendance_configs(ctx: BuildContext, protocol: Protocol) -> list[dict]:
    type_id = _attendance_type_id(ctx)
    if not type_id:
        return []
    return [
        config or {}
        for config in ctx.db.scalars(
            select(ProtocolElementBlock.configuration_snapshot_json)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(ProtocolElement.protocol_id == protocol.id, ProtocolElementBlock.element_type_id == type_id)
            .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc())
        )
    ]


def _protocol_from_params(ctx: BuildContext, protocol_ref: Any) -> Protocol | None:
    protocol = ctx.require_entity(Protocol, protocol_ref) if protocol_ref else ctx.protocol
    if protocol is not None:
        ctx.ensure_can_read_protocol(protocol.id)
    return protocol


def provide_attendance(ctx: BuildContext, spec: BlockSpec, params: ProtocolRefParams):
    protocol = _protocol_from_params(ctx, params.protocol_id)
    entries: list[AttendanceEntry] = []
    if protocol is not None:
        for config in protocol_attendance_configs(ctx, protocol):
            entries.extend(attendance_entries(ctx, config))
    return [AttendanceBlock(**spec_fields(spec), entries=entries)]


def provide_attendance_matrix(ctx: BuildContext, spec: BlockSpec, params: AttendanceMatrixParams):
    type_id = _attendance_type_id(ctx)
    bounds = resolve_period(ctx, params)
    statement = (
        select(Protocol.id, Protocol.protocol_date, ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
        .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
        .where(
            Protocol.tenant_id == ctx.tenant_id,
            Protocol.status.in_(["durchgeführt", "abgeschlossen"]),
            ProtocolElementBlock.element_type_id == (type_id or -1),
        )
        .order_by(Protocol.protocol_date.asc(), Protocol.id.asc())
    )
    if bounds is not None:
        statement = statement.where(Protocol.protocol_date >= bounds[0], Protocol.protocol_date <= bounds[1])
    if params.template_id is not None:
        template = ctx.require_entity(Template, params.template_id)
        statement = statement.where(Protocol.template_id == template.id)

    sessions: list[tuple[int, date]] = []
    statuses: dict[tuple[str, int], str] = {}
    names: dict[str, str] = {}
    for protocol_id, protocol_date, config in ctx.db.execute(statement).all():
        if ctx.user is not None:
            from app.services.access_service import AccessService

            if not AccessService().can_read_protocol(ctx.db, ctx.user, protocol_id):
                continue
        if (protocol_id, protocol_date) not in sessions:
            sessions.append((protocol_id, protocol_date))
        for entry in (config or {}).get("attendance_entries") or []:
            if not isinstance(entry, dict):
                continue
            key = f"id:{entry.get('participant_id')}" if entry.get("participant_id") is not None else f"name:{entry.get('participant_name')}"
            names[key] = str(entry.get("participant_name") or names.get(key) or "–")
            status = entry.get("status")
            if status in ATTENDANCE_STATUSES:
                statuses[(key, protocol_id)] = status
    people = sorted(names, key=lambda key: sort_key(names[key]))
    cells = [[statuses.get((key, protocol_id)) for protocol_id, _ in sessions] for key in people]
    rates: list[str] = []
    if params.show_rates:
        for row in cells:
            recorded = [status for status in row if status]
            attended = sum(1 for status in recorded if status in ("present", "late"))
            rates.append(f"{round(attended / len(recorded) * 100)}%" if recorded else "–")
    return [
        AttendanceMatrixBlock(
            **spec_fields(spec),
            sessions=[protocol_date.strftime("%d.%m.%y") for _, protocol_date in sessions],
            people=[names[key] for key in people],
            cells=cells,
            rates=rates,
        )
    ]


def _members(ctx: BuildContext, *, active_only: bool, template_ref: Any = None) -> list[Participant]:
    statement = select(Participant).where(Participant.tenant_id == ctx.tenant_id)
    if active_only:
        statement = statement.where(Participant.is_active.is_(True))
    if template_ref is not None:
        template = ctx.require_entity(Template, template_ref)
        statement = statement.join(TemplateParticipant, TemplateParticipant.participant_id == Participant.id).where(TemplateParticipant.template_id == template.id)
    return sorted(ctx.db.scalars(statement), key=lambda participant: sort_key(participant.display_name))


def provide_member_list(ctx: BuildContext, spec: BlockSpec, params: MemberListParams):
    members = _members(ctx, active_only=params.active_only, template_ref=params.template_id)
    roles = dict(ctx.db.execute(select(Role.id, Role.code)).all())
    columns = [col("name", "col.name", width="fill")]
    labels = {"email": "col.email", "role": "col.role", "joined_at": "col.joined", "left_at": "col.left", "status": "col.status"}
    columns += [col(key, labels[key]) for key in params.columns]
    rows: list[TableRow] = []
    for member in members:
        cells = [text_cell(member.display_name)]
        for key in params.columns:
            if key == "email":
                cells.append(text_cell(member.email or ""))
            elif key == "role":
                code = roles.get(member.role_id, "")
                cells.append(Cell(k="text", v="", note_key=f"role.{code}") if code else text_cell(""))
            elif key == "joined_at":
                cells.append(text_cell(format_date(member.joined_at)))
            elif key == "left_at":
                cells.append(text_cell(format_date(member.left_at)))
            elif key == "status":
                cells.append(Cell(k="text", v="", note_key="memberStatus.active" if member.is_active else "memberStatus.inactive"))
        rows.append(TableRow(cells=cells, muted=not member.is_active))
    return [MemberListBlock(**spec_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else []))]


def provide_attendance_sheet(ctx: BuildContext, spec: BlockSpec, params: AttendanceSheetParams):
    names: list[str] = []
    if params.source == "protocol":
        protocol = _protocol_from_params(ctx, params.protocol_id)
        if protocol is not None:
            for config in protocol_attendance_configs(ctx, protocol):
                names.extend(entry.name for entry in attendance_entries(ctx, config))
            if not names:
                names = [member.display_name for member in _members(ctx, active_only=True, template_ref=protocol.template_id)]
    elif params.source == "template":
        names = [member.display_name for member in _members(ctx, active_only=True, template_ref=params.template_id)] if params.template_id else []
    else:
        names = [member.display_name for member in _members(ctx, active_only=True)]
    return [AttendanceSheetBlock(**spec_fields(spec), names=names, columns=[label for label in params.columns if label.strip()], blank_rows=params.blank_rows)]


def entry_exit_from_config(config: dict) -> tuple[list[EntryExitItem], list[EntryExitItem]]:
    entries = (config or {}).get("entries") or []
    joins = [EntryExitItem(name=str(entry.get("participant_name") or "–"), date=format_date(entry.get("date")) or None) for entry in entries if isinstance(entry, dict) and entry.get("type") == "join" and not entry.get("hidden")]
    leaves = [EntryExitItem(name=str(entry.get("participant_name") or "–"), date=format_date(entry.get("date")) or None) for entry in entries if isinstance(entry, dict) and entry.get("type") == "leave" and not entry.get("hidden")]
    return joins, leaves


def provide_entry_exit(ctx: BuildContext, spec: BlockSpec, params: EntryExitParams):
    start = params.date_from or date.min
    end = params.date_to or date.max
    members = list(ctx.db.scalars(select(Participant).where(Participant.tenant_id == ctx.tenant_id)))
    joins = sorted(
        (member for member in members if member.joined_at and start <= member.joined_at <= end),
        key=lambda member: (member.joined_at, sort_key(member.display_name)),
    )
    leaves = sorted(
        (member for member in members if member.left_at and start <= member.left_at <= end),
        key=lambda member: (member.left_at, sort_key(member.display_name)),
    )
    return [
        EntryExitBlock(
            **spec_fields(spec),
            joins=[EntryExitItem(name=member.display_name, date=format_date(member.joined_at)) for member in joins],
            leaves=[EntryExitItem(name=member.display_name, date=format_date(member.left_at)) for member in leaves],
        )
    ]
