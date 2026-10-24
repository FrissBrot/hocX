"""Anliegen: Liste unter «Arbeiten», Erstell-Popup und Anzeige im Protokolleditor.

Lesen wie Protokolle/Vorlagen (eingeschränkte Leser nur für ihre Vorlagen), Schreiben ab
Schreibrolle im eigenen Mandanten. Logik in app/services/agenda_item_service.py."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.redis_client import publish_best_effort
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models.entities import (
    AgendaItem,
    Protocol,
    ProtocolElement,
    Template,
    TemplateElement,
    UserAgendaTemplatePreference,
)
from app.schemas.agenda import (
    AgendaItemCreate,
    AgendaItemPostpone,
    AgendaItemRead,
    AgendaItemUpdate,
    AgendaProtocolRef,
    AgendaSchedule,
    AgendaTemplateOption,
    AgendaTemplatePreference,
    ProtocolAgendaItemCreate,
    ProtocolAgendaItemRead,
)
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.agenda_item_service import AgendaItemFrozenError, AgendaItemService, Schedule
from app.services.audit_service import AuditService
from app.services.collaboration_service import protocol_channel

router = APIRouter()
service = AgendaItemService()
access_service = AccessService()
audit = AuditService()


def _schedule(payload: AgendaSchedule) -> Schedule:
    return Schedule(kind=payload.kind, month=payload.month)


def _readable_template_ids(db: Session, user: CurrentUser) -> set[int] | None:
    """None = alle Vorlagen des Mandanten, sonst nur die zugewiesenen (eingeschränkte Leser)."""
    if access_service.is_restricted_reader(db, user):
        return set(access_service.repository.list_template_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id))
    return None


def _get_item_or_404(db: Session, item_id: uuid.UUID, user: CurrentUser, *, for_write: bool = False) -> AgendaItem:
    item = public_id_service.get_by_public_id(db, AgendaItem, item_id, tenant_id=user.current_tenant_id)
    if item is None or not access_service.can_read_template(db, user, item.template_id):
        raise HTTPException(status_code=404, detail="Agenda item not found")
    if for_write and service.is_frozen(db, item):
        raise HTTPException(status_code=409, detail="Agenda item belongs to a closed protocol")
    return item


def _get_template_or_404(db: Session, template_id: uuid.UUID, user: CurrentUser) -> Template:
    template = public_id_service.get_by_public_id(db, Template, template_id, tenant_id=user.current_tenant_id)
    if template is None or not access_service.can_read_template(db, user, template.id):
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def _resolve_point(db: Session, template: Template, point_id: uuid.UUID | None) -> int | None:
    if point_id is None:
        return None
    # nosemgrep: public-id-lookup-without-tenant -- template_element hat keine tenant_id; Zugehörigkeit zur (mandantengeprüften) Vorlage folgt direkt
    element = public_id_service.get_by_public_id(db, TemplateElement, point_id)
    if element is None or element.template_id != template.id:
        raise HTTPException(status_code=404, detail="Template element not found")
    return element.id


def _affected_protocol_ids(db: Session, item: AgendaItem) -> set[int]:
    ids = {item.protocol_id} if item.protocol_id else set()
    target = service.target_protocol_ids(db, [item.id]).get(item.id) if item.protocol_id is None else None
    if target:
        ids.add(target)
    return ids


def _broadcast(protocol_ids: set[int], user: CurrentUser) -> None:
    """Offene Editoren der betroffenen Protokolle laden ihre Anliegen neu."""
    for protocol_id in protocol_ids:
        publish_best_effort(
            protocol_channel(protocol_id),
            json.dumps({
                "type": "field_update",
                "field_key": "agenda-items",
                "patch": None,
                "user_id": None,
                "display_name": user.display_name,
            }),
        )


def _protocol_visibility(db: Session, user: CurrentUser):
    """Welche Protokolle die Liste nennen darf - wie die Protokollliste: eingeschränkte Leser nur
    ihre zugewiesenen, übrige Leser nur abgeschlossene (Security-Review 2026-10-24)."""
    if user.current_role != "reader":
        return lambda protocol: True
    if access_service.is_restricted_reader(db, user):
        allowed = set(access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id))
        return lambda protocol: protocol.id in allowed
    return lambda protocol: protocol.status == "abgeschlossen"


def _build_reads(db: Session, items: list[AgendaItem], user: CurrentUser) -> list[AgendaItemRead]:
    if not items:
        return []
    visible = _protocol_visibility(db, user)
    template_ids = {item.template_id for item in items}
    templates = {row.id: row for row in db.scalars(select(Template).where(Template.id.in_(template_ids))).all()}
    point_ids = {item.template_element_id for item in items if item.template_element_id}
    points = (
        {row.id: row for row in db.scalars(select(TemplateElement).where(TemplateElement.id.in_(point_ids))).all()}
        if point_ids
        else {}
    )
    targets = service.target_protocol_ids(db, [item.id for item in items if item.protocol_id is None])
    protocol_ids = {item.protocol_id for item in items if item.protocol_id} | {pid for pid in targets.values() if pid}
    protocols = (
        {row.id: row for row in db.scalars(select(Protocol).where(Protocol.id.in_(protocol_ids))).all()}
        if protocol_ids
        else {}
    )
    creators = service.creator_names(db, items)
    result: list[AgendaItemRead] = []
    for item in items:
        protocol_id = item.protocol_id or targets.get(item.id)
        protocol = protocols.get(protocol_id) if protocol_id else None
        if protocol is None:
            state = "waiting"
        elif item.protocol_id and protocol.status in ("durchgeführt", "abgeschlossen"):
            state = "treated"
        else:
            state = "scheduled"
        template = templates[item.template_id]
        point = points.get(item.template_element_id) if item.template_element_id else None
        result.append(AgendaItemRead(
            id=item.public_id,
            title=item.title,
            body=item.body,
            template_id=template.public_id,
            template_name=template.name,
            template_element_id=point.public_id if point else None,
            template_element_name=point.section_name if point else None,
            schedule_kind=item.schedule_kind,
            scheduled_month=item.scheduled_month,
            earliest_date=item.earliest_date,
            postponed_count=item.postponed_count,
            state=state,
            protocol=AgendaProtocolRef(
                id=protocol.public_id,
                protocol_number=protocol.protocol_number,
                title=protocol.title,
                protocol_date=protocol.protocol_date,
                status=protocol.status,
            ) if protocol and visible(protocol) else None,
            is_bound=item.protocol_id is not None,
            can_edit=not (item.protocol_id and protocol is not None and protocol.status == "abgeschlossen"),
            created_by_name=creators.get(item.created_by) if item.created_by else None,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ))
    return result


def _read_one(db: Session, item: AgendaItem, user: CurrentUser) -> AgendaItemRead:
    return _build_reads(db, [item], user)[0]


def _write_error(exc: Exception, fallback: str) -> HTTPException:
    if isinstance(exc, AgendaItemFrozenError):
        return HTTPException(status_code=409, detail="Agenda item belongs to a closed protocol")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=fallback)


# ── Liste und Erstell-Popup ──────────────────────────────────────────────


@router.get("/agenda-items", response_model=list[AgendaItemRead])
def list_agenda_items(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    items = service.list_for_tenant(db, user.current_tenant_id, template_ids=_readable_template_ids(db, user))
    return _build_reads(db, items, user)


@router.get("/agenda-items/templates", response_model=list[AgendaTemplateOption])
def list_agenda_templates(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return service.templates_with_points(db, user.current_tenant_id, template_ids=_readable_template_ids(db, user))


@router.get("/agenda-items/template-preference", response_model=AgendaTemplatePreference)
def get_agenda_template_preference(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    row = db.get(UserAgendaTemplatePreference, (user.user_id, user.current_tenant_id))
    template = db.get(Template, row.template_id) if row and row.template_id else None
    if template is None or template.tenant_id != user.current_tenant_id or template.status != "active":
        return {"template_id": None}
    return {"template_id": template.public_id}


@router.put("/agenda-items/template-preference", status_code=status.HTTP_204_NO_CONTENT)
def save_agenda_template_preference(
    payload: AgendaTemplatePreference,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    template_id = _get_template_or_404(db, payload.template_id, user).id if payload.template_id else None
    db.execute(
        pg_insert(UserAgendaTemplatePreference)
        .values(user_id=user.user_id, tenant_id=user.current_tenant_id, template_id=template_id)
        .on_conflict_do_update(index_elements=["user_id", "tenant_id"], set_={"template_id": template_id})
    )
    db.commit()


@router.post("/agenda-items", response_model=AgendaItemRead, status_code=status.HTTP_201_CREATED)
def create_agenda_item(
    payload: AgendaItemCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    template = _get_template_or_404(db, payload.template_id, user)
    point_id = _resolve_point(db, template, payload.template_element_id)
    try:
        item = service.create(
            db,
            tenant_id=user.current_tenant_id,
            template=template,
            template_element_id=point_id,
            title=payload.title,
            body=payload.body,
            schedule=_schedule(payload.schedule),
            created_by=user.user_id,
        )
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _write_error(exc, "Agenda item could not be created") from exc
    audit.log(db, action="agenda_item.created", actor=user, entity_type="agenda_item", entity_id=item.id)
    _broadcast(_affected_protocol_ids(db, item), user)
    return _read_one(db, item, user)


@router.patch("/agenda-items/{item_id}", response_model=AgendaItemRead)
def update_agenda_item(
    item_id: uuid.UUID,
    payload: AgendaItemUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    item = _get_item_or_404(db, item_id, user, for_write=True)
    fields = set(payload.model_fields_set)
    template = _get_template_or_404(db, payload.template_id, user) if payload.template_id else None
    point_id = None
    if "template_element_id" in fields:
        point_template = template or db.get(Template, item.template_id)
        point_id = _resolve_point(db, point_template, payload.template_element_id)
    if "template_id" in fields and template is None:
        fields.discard("template_id")
    if "schedule" in fields and payload.schedule is None:
        fields.discard("schedule")
    before = _affected_protocol_ids(db, item)
    try:
        item = service.update(
            db,
            item,
            fields=fields,
            title=payload.title,
            body=payload.body,
            template=template,
            template_element_id=point_id,
            schedule=_schedule(payload.schedule) if payload.schedule else None,
        )
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _write_error(exc, "Agenda item could not be updated") from exc
    _broadcast(before | _affected_protocol_ids(db, item), user)
    return _read_one(db, item, user)


@router.post("/agenda-items/{item_id}/postpone", response_model=AgendaItemRead)
def postpone_agenda_item(
    item_id: uuid.UUID,
    payload: AgendaItemPostpone,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    item = _get_item_or_404(db, item_id, user, for_write=True)
    before = _affected_protocol_ids(db, item)
    try:
        item = service.postpone(db, item, _schedule(payload.schedule))
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _write_error(exc, "Agenda item could not be postponed") from exc
    audit.log(db, action="agenda_item.postponed", actor=user, entity_type="agenda_item", entity_id=item.id,
              details={"schedule_kind": item.schedule_kind, "earliest_date": item.earliest_date.isoformat()})
    _broadcast(before | _affected_protocol_ids(db, item), user)
    return _read_one(db, item, user)


@router.delete("/agenda-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agenda_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    item = _get_item_or_404(db, item_id, user, for_write=True)
    before = _affected_protocol_ids(db, item)
    internal_id = item.id
    try:
        service.delete(db, item)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _write_error(exc, "Agenda item could not be deleted") from exc
    audit.log(db, action="agenda_item.deleted", actor=user, entity_type="agenda_item", entity_id=internal_id)
    _broadcast(before, user)


# ── Protokolleditor ──────────────────────────────────────────────────────


def _get_protocol_or_404(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> Protocol:
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    # 404 statt 403 auch für nicht zugewiesene Protokolle: kein Existenz-Orakel.
    if protocol is None or not access_service.can_read_protocol(db, user, protocol.id):
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


def _protocol_reads(db: Session, protocol: Protocol, items: list[AgendaItem]) -> list[ProtocolAgendaItemRead]:
    placements = service.placements(db, protocol, items)
    element_public_ids = public_id_service.resolve_public_ids(
        db, ProtocolElement, [pid for pid in placements.values() if pid]
    )
    editable = protocol.status != "abgeschlossen"
    return [
        ProtocolAgendaItemRead(
            id=item.public_id,
            title=item.title,
            body=item.body,
            protocol_element_id=element_public_ids.get(placements.get(item.id)) if placements.get(item.id) else None,
            postponed_count=item.postponed_count,
            can_edit=editable,
        )
        for item in items
    ]


@router.get("/protocols/{protocol_id}/agenda-items", response_model=list[ProtocolAgendaItemRead])
def list_protocol_agenda_items(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    return _protocol_reads(db, protocol, service.items_for_protocol(db, protocol))


@router.post(
    "/protocols/{protocol_id}/agenda-items",
    response_model=ProtocolAgendaItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protocol_agenda_item(
    protocol_id: uuid.UUID,
    payload: ProtocolAgendaItemCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    element = None
    if payload.protocol_element_id is not None:
        # nosemgrep: public-id-lookup-without-tenant -- protocol_element hat keine tenant_id; Zugehörigkeit zum (mandantengeprüften) Protokoll folgt direkt
        element = public_id_service.get_by_public_id(db, ProtocolElement, payload.protocol_element_id)
        if element is None or element.protocol_id != protocol.id:
            raise HTTPException(status_code=404, detail="Protocol element not found")
    if protocol.status == "abgeschlossen":
        raise HTTPException(status_code=409, detail="Protocol is already abgeschlossen")
    try:
        item = service.create_in_protocol(
            db, protocol=protocol, protocol_element=element, title=payload.title, body=payload.body, created_by=user.user_id,
        )
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _write_error(exc, "Agenda item could not be created") from exc
    audit.log(db, action="agenda_item.created", actor=user, entity_type="agenda_item", entity_id=item.id)
    _broadcast({protocol.id}, user)
    return _protocol_reads(db, protocol, [item])[0]
